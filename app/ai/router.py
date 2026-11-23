"""Router AI: empat tingkat, zero-cost.

Urutan: pra-parser regex (Rp0) → OpenRouter model gratis → Gemini free tier →
entri manual. Rinciannya di docs/ARCHITECTURE.md bagian 5.

Pola *exponential backoff* dengan *jitter* dan *deadline* total diadaptasi
dari RibasomR/finance-bot (MIT, Copyright (c) 2025-2026 RibasomR); lihat
docs/THIRD_PARTY_NOTICES.md. Bagian proxy pada kode aslinya memakai argumen
``proxies=`` yang sudah dihapus di httpx ≥ 0.28 (diverifikasi pada 0.28.1),
jadi penanganan klien HTTP di sini ditulis ulang.

Aturan zero-cost yang dipegang modul ini:

* Tidak ada jalur kode yang berpindah ke model berbayar, menyalakan billing,
  atau membeli kredit.
* Kuota habis = TURUN ke tingkat berikutnya, bukan naik ke model berbayar.
* Provider yang kuotanya habis masuk masa cooldown supaya tidak dihujani
  permintaan yang pasti gagal.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import time
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Sequence, Tuple

import httpx

from app.ai import gemini, openrouter
from app.ai.errors import (
    AIConfigError,
    AIError,
    AIInvalidResponse,
    AIQuotaExceeded,
    AITemporaryError,
)
from app.ai.parser import parse as parse_regex
from app.ai.prompt import build_prompt
from app.ai.schema import ParsedTransaction
from app.ai.scrub import periksa as periksa_scrub
from app.config import get_settings
from app.database.models import TransactionType
from app.utils.dates import local_today
from app.utils.logger import get_logger
from app.utils.money import to_decimal
from app.utils.sanitizer import sanitize_exception, sanitize_text

logger = get_logger(__name__)

#: Batas waktu seluruh upaya AI. Pengguna sedang menunggu di Telegram;
#: lebih baik jatuh ke entri manual daripada membuatnya menunggu lama.
DEADLINE_TOTAL = 25.0
TIMEOUT_PER_PERMINTAAN = 10.0
MAKS_PERCOBAAN = 2
MAKS_PANJANG_TEKS = 500

#: Lama provider dilewati setelah kuotanya dinyatakan habis.
COOLDOWN_KUOTA = 900.0  # 15 menit
COOLDOWN_KONFIGURASI = 3600.0  # 1 jam: salah konfigurasi tidak sembuh sendiri

#: Cooldown per provider. Di memori saja — hilang saat restart, dan itu tidak
#: masalah: paling buruk satu permintaan terbuang untuk menemukan kembali
#: bahwa kuotanya masih habis.
_cooldown: Dict[str, float] = {}


class HasilAI:
    """Hasil upaya parsing berikut catatan apa yang terjadi."""

    def __init__(
        self,
        parsed: Optional[ParsedTransaction],
        sumber: str,
        catatan: Optional[List[str]] = None,
    ) -> None:
        self.parsed = parsed
        self.sumber = sumber
        self.catatan = catatan or []

    @property
    def berhasil(self) -> bool:
        return self.parsed is not None and self.parsed.lengkap


def _backoff(percobaan: int, dasar: float = 0.5, jitter: float = 0.2) -> float:
    """Jeda eksponensial dengan jitter: 0,5s · 1s · 2s ±20%.

    Jitter mencegah beberapa permintaan yang gagal bersamaan mencoba ulang
    pada detik yang sama.
    """
    tunda = dasar * (2**percobaan)
    return tunda + tunda * jitter * (2 * random.random() - 1)


def _dalam_cooldown(nama: str) -> bool:
    sampai = _cooldown.get(nama, 0.0)
    if sampai > time.monotonic():
        return True
    _cooldown.pop(nama, None)
    return False


def _mulai_cooldown(nama: str, detik: float) -> None:
    _cooldown[nama] = time.monotonic() + detik
    logger.warning("Provider %s masuk cooldown %.0f detik.", nama, detik)


def reset_cooldown() -> None:
    """Kosongkan cooldown. Dipakai oleh test."""
    _cooldown.clear()


def _bersihkan_json(teks: str) -> str:
    """Ambil objek JSON dari jawaban model.

    Model gratis sering mengabaikan instruksi "JSON saja" dan membungkus
    jawabannya dalam markdown fence atau menambahkan kalimat pengantar, jadi
    pembersihan ini tetap diperlukan walaupun prompt sudah memintanya.
    """
    bersih = teks.strip()

    if "```" in bersih:
        cocok = re.search(r"```(?:json)?\s*(.*?)```", bersih, re.DOTALL)
        if cocok:
            bersih = cocok.group(1).strip()

    # Ambil objek JSON pertama yang seimbang kurung kurawalnya.
    mulai = bersih.find("{")
    if mulai == -1:
        return bersih

    kedalaman = 0
    dalam_string = False
    escape = False
    for i in range(mulai, len(bersih)):
        c = bersih[i]
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"':
            dalam_string = not dalam_string
            continue
        if dalam_string:
            continue
        if c == "{":
            kedalaman += 1
        elif c == "}":
            kedalaman -= 1
            if kedalaman == 0:
                return bersih[mulai : i + 1]

    return bersih[mulai:]


def _ke_parsed(
    isi: str, sumber: str, hari_ini: date, batas_jumlah: Decimal
) -> ParsedTransaction:
    """Ubah jawaban AI menjadi ParsedTransaction yang sudah divalidasi.

    Validasi di sini tidak opsional: jawaban model adalah masukan dari luar
    yang tidak dipercaya. Jumlah dikonversi lewat ``Decimal(str(...))`` agar
    angka JSON tidak pernah menjadi float.
    """
    mentah = _bersihkan_json(isi)

    try:
        data = json.loads(mentah)
    except json.JSONDecodeError as exc:
        raise AIInvalidResponse(
            f"Jawaban AI bukan JSON yang sah: {sanitize_text(str(exc))}"
        ) from exc

    if not isinstance(data, dict):
        raise AIInvalidResponse("Jawaban AI bukan objek JSON.")

    jenis_mentah = str(data.get("type") or "").strip().lower()
    if jenis_mentah not in ("income", "expense"):
        raise AIInvalidResponse(f"Jenis transaksi tidak sah: {jenis_mentah!r}")
    jenis = TransactionType(jenis_mentah)

    jumlah_mentah = data.get("amount")
    if jumlah_mentah is None or jumlah_mentah == "":
        raise AIInvalidResponse("AI tidak menentukan jumlah.")

    try:
        jumlah = to_decimal(jumlah_mentah)
    except (ValueError, InvalidOperation) as exc:
        raise AIInvalidResponse(f"Jumlah dari AI tidak sah: {jumlah_mentah!r}") from exc

    if jumlah <= 0:
        raise AIInvalidResponse("Jumlah dari AI harus lebih besar dari nol.")
    if jumlah > batas_jumlah:
        raise AIInvalidResponse(f"Jumlah dari AI melampaui batas: {jumlah}")

    tanggal = hari_ini
    tanggal_mentah = data.get("date")
    if tanggal_mentah:
        try:
            tanggal = date.fromisoformat(str(tanggal_mentah)[:10])
        except ValueError:
            # Tanggal yang tidak terbaca bukan alasan menggagalkan transaksi;
            # pengguna masih melihat tanggalnya di layar konfirmasi.
            logger.info("Tanggal dari AI tidak terbaca: %r", tanggal_mentah)

    def _teks(kunci: str, maks: int) -> Optional[str]:
        nilai = data.get(kunci)
        if nilai is None:
            return None
        s = str(nilai).strip()
        if not s or s.lower() in ("null", "none", "-"):
            return None
        return s[:maks]

    return ParsedTransaction(
        transaction_type=jenis,
        amount=jumlah,
        category=_teks("category", 100),
        description=_teks("description", 500),
        location=_teks("location", 255),
        transaction_date=tanggal,
        sumber=sumber,
    )


async def _coba_provider(
    client: httpx.AsyncClient,
    nama: str,
    fungsi,
    api_key: str,
    model_list: Sequence[str],
    prompt: str,
    hari_ini: date,
    batas_jumlah: Decimal,
    mulai: float,
    catatan: List[str],
) -> Optional[ParsedTransaction]:
    """Coba satu provider dengan seluruh modelnya.

    Mengembalikan None (bukan exception) bila provider ini tidak berhasil,
    supaya pemanggil bisa lanjut ke tingkat berikutnya.
    """
    if _dalam_cooldown(nama):
        catatan.append(f"{nama}: dilewati (cooldown)")
        return None
    if not api_key:
        catatan.append(f"{nama}: dilewati (kunci API tidak diatur)")
        return None

    for model in model_list:
        for percobaan in range(MAKS_PERCOBAAN):
            terpakai = time.monotonic() - mulai
            if terpakai >= DEADLINE_TOTAL:
                catatan.append(f"{nama}: batas waktu total {DEADLINE_TOTAL:.0f}s terlampaui")
                return None

            timeout = min(TIMEOUT_PER_PERMINTAAN, DEADLINE_TOTAL - terpakai)

            try:
                isi = await fungsi(
                    client, api_key=api_key, model=model, prompt=prompt, timeout=timeout
                )
                hasil = _ke_parsed(isi, nama, hari_ini, batas_jumlah)
                logger.info("Parsing berhasil lewat %s (%s).", nama, model)
                return hasil

            except AIQuotaExceeded as exc:
                # Kuota habis: TURUN ke tingkat berikutnya. Tidak pernah naik
                # ke model berbayar.
                catatan.append(f"{nama}: kuota habis")
                logger.warning("Kuota %s habis: %s", nama, exc)
                _mulai_cooldown(nama, COOLDOWN_KUOTA)
                return None

            except AIConfigError as exc:
                # Tidak layak dicoba ulang: konfigurasi tidak akan berubah
                # sendiri di antara dua percobaan.
                catatan.append(f"{nama}: konfigurasi salah")
                logger.error("Konfigurasi %s salah: %s", nama, exc)
                _mulai_cooldown(nama, COOLDOWN_KONFIGURASI)
                return None

            except (AITemporaryError, AIInvalidResponse) as exc:
                catatan.append(f"{nama}/{model}: {type(exc).__name__}")
                logger.info(
                    "Percobaan %s gagal (%s): %s", nama, model, sanitize_exception(exc)
                )
                if percobaan < MAKS_PERCOBAAN - 1:
                    jeda = _backoff(percobaan)
                    if (time.monotonic() - mulai) + jeda < DEADLINE_TOTAL:
                        await asyncio.sleep(jeda)
                        continue
                break  # coba model berikutnya

            except Exception as exc:  # pragma: no cover
                catatan.append(f"{nama}: galat tak terduga")
                logger.exception("Galat tak terduga pada %s: %s", nama, sanitize_exception(exc))
                break

    return None


async def parse_transaksi(
    teks: str,
    kategori_pengeluaran: Sequence[str],
    kategori_pemasukan: Sequence[str],
    hari_ini: Optional[date] = None,
) -> Tuple[HasilAI, Optional[str]]:
    """Parse pesan menjadi calon transaksi melalui empat tingkat.

    :return: ``(hasil, pesan_penolakan)``. ``pesan_penolakan`` hanya terisi
             bila pesan ditolak oleh pemeriksaan data sensitif; dalam kasus itu
             tidak ada apa pun yang dikirim ke provider AI mana pun.
    """
    s = get_settings()
    hari_ini = hari_ini or local_today(s.tzinfo)
    catatan: List[str] = []

    # Tingkat 0: perlindungan data. Dijalankan sebelum apa pun dikirim keluar.
    aman, alasan, bersih = periksa_scrub(teks)
    if not aman:
        logger.info("Pesan ditolak oleh pemeriksaan data sensitif.")
        return HasilAI(None, "ditolak", ["scrub: pesan memuat data sensitif"]), alasan

    if len(bersih) > MAKS_PANJANG_TEKS:
        bersih = bersih[:MAKS_PANJANG_TEKS]
        catatan.append(f"teks dipotong ke {MAKS_PANJANG_TEKS} karakter")

    # Tingkat 1: pra-parser regex. Rp0, deterministik, selalu dicoba dulu.
    hasil_regex = parse_regex(bersih, hari_ini=hari_ini)
    if hasil_regex.lengkap and not hasil_regex.kurang:
        logger.info("Parsing berhasil lewat pra-parser regex (tanpa biaya AI).")
        return HasilAI(hasil_regex, "parser", ["parser: lengkap"]), None

    catatan.append(
        "parser: belum lengkap"
        + (f" (kurang: {', '.join(hasil_regex.kurang)})" if hasil_regex.kurang else "")
    )

    prompt = build_prompt(bersih, hari_ini.isoformat(), kategori_pengeluaran, kategori_pemasukan)
    mulai = time.monotonic()

    # Tingkat 2 dan 3: provider AI.
    async with httpx.AsyncClient() as client:
        for nama, fungsi, key, model_list in (
            (openrouter.NAMA, openrouter.minta, s.openrouter_api_key, s.openrouter_model_list),
            (gemini.NAMA, gemini.minta, s.gemini_api_key, s.gemini_model_list),
        ):
            hasil = await _coba_provider(
                client, nama, fungsi, key, model_list, prompt, hari_ini,
                s.max_transaction_amount, mulai, catatan,
            )
            if hasil is not None and hasil.lengkap:
                return HasilAI(hasil, nama, catatan), None

    # Tingkat 4: kedua provider gagal.
    #
    # Bila pra-parser tadi menghasilkan jumlah dan jenis, pakai itu — tebakan
    # yang lemah masih lebih berguna daripada tidak ada apa-apa, dan pengguna
    # tetap melihatnya di layar konfirmasi sebelum tersimpan. Field yang lemah
    # tercatat di `kurang` sehingga handler bisa menandainya.
    if hasil_regex.lengkap:
        catatan.append("AI tidak tersedia; memakai hasil pra-parser")
        logger.info("Kedua provider AI gagal; memakai hasil pra-parser regex.")
        return HasilAI(hasil_regex, "parser", catatan), None

    logger.warning("Semua tingkat parsing gagal. Catatan: %s", "; ".join(catatan))
    return HasilAI(None, "gagal", catatan), None
