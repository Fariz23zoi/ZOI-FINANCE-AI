"""Uji router AI: empat tingkat, fallback, dan penjagaan zero-cost.

Seluruh permintaan HTTP dipalsukan dengan ``httpx.MockTransport``, jadi test
ini tidak pernah menyentuh jaringan dan tidak memakai kuota apa pun.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest

from app.ai import router as ai_router
from app.ai.errors import AIInvalidResponse
from app.database.models import TransactionType

HARI_INI = date(2026, 11, 23)
KAT_KELUAR = ["Transportasi", "Makanan & Minuman", "Lain-lain"]
KAT_MASUK = ["Gaji", "Penjualan", "Lain-lain"]

#: Kalimat yang tidak bisa diselesaikan pra-parser, sehingga memaksa jalur AI.
BUTUH_AI = "keperluan mendadak 45 ribu"

JAWABAN = {
    "type": "expense",
    "amount": 45000,
    "category": "Lain-lain",
    "description": "Keperluan mendadak",
    "location": None,
    "date": "2026-11-23",
}


def _balas_openrouter(isi: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": isi}}]})


def _balas_gemini(isi: str) -> httpx.Response:
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": isi}]}}]})


def _transport(perilaku_or, perilaku_gm):
    """Transport palsu; setiap perilaku bisa berupa Response atau Exception."""
    dipanggil = {"openrouter": 0, "gemini": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        nama = "openrouter" if "openrouter" in request.url.host else "gemini"
        dipanggil[nama] += 1
        perilaku = perilaku_or if nama == "openrouter" else perilaku_gm
        if isinstance(perilaku, Exception):
            raise perilaku
        return perilaku

    return httpx.MockTransport(handler), dipanggil


async def _jalankan(perilaku_or, perilaku_gm, teks=BUTUH_AI):
    ai_router.reset_cooldown()
    transport, dipanggil = _transport(perilaku_or, perilaku_gm)

    asli = httpx.AsyncClient

    class ClientUji(asli):
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            super().__init__(*a, **kw)

    with patch.object(httpx, "AsyncClient", ClientUji):
        hasil, penolakan = await ai_router.parse_transaksi(
            teks, KAT_KELUAR, KAT_MASUK, hari_ini=HARI_INI
        )
    return hasil, penolakan, dipanggil


class TestTingkatSatuPraParser:
    async def test_pra_parser_cukup_maka_ai_tidak_dipanggil(self):
        """Ini inti penghematan: kalimat sehari-hari tidak memakai kuota AI."""
        hasil, _, dipanggil = await _jalankan(
            _balas_openrouter(json.dumps(JAWABAN)),
            _balas_gemini(json.dumps(JAWABAN)),
            teks="Beli bensin 30rb",
        )
        assert hasil.berhasil
        assert hasil.sumber == "parser"
        assert hasil.parsed.amount == Decimal("30000.00")
        assert dipanggil == {"openrouter": 0, "gemini": 0}

    async def test_contoh_spesifikasi_utama_tidak_perlu_ai(self):
        hasil, _, dipanggil = await _jalankan(
            httpx.ConnectError("mati"),
            httpx.ConnectError("mati"),
            teks="Bayar parkir motor 2 ribu di pasar Ciamis",
        )
        assert hasil.berhasil
        assert hasil.sumber == "parser"
        assert hasil.parsed.location == "Pasar Ciamis"
        assert dipanggil["openrouter"] == 0


class TestFallbackProvider:
    async def test_openrouter_berhasil(self):
        hasil, _, dipanggil = await _jalankan(
            _balas_openrouter(json.dumps(JAWABAN)), httpx.ConnectError("mati")
        )
        assert hasil.sumber == "openrouter"
        assert hasil.parsed.amount == Decimal("45000.00")
        assert dipanggil["gemini"] == 0

    @pytest.mark.parametrize("status", [429, 402, 500, 503, 401, 403, 404])
    async def test_openrouter_gagal_turun_ke_gemini(self, status):
        hasil, _, dipanggil = await _jalankan(
            httpx.Response(status, text="gagal"), _balas_gemini(json.dumps(JAWABAN))
        )
        assert hasil.sumber == "gemini"
        assert hasil.berhasil
        assert dipanggil["gemini"] >= 1

    async def test_openrouter_tidak_terjangkau_turun_ke_gemini(self):
        hasil, _, _ = await _jalankan(
            httpx.ConnectError("mati"), _balas_gemini(json.dumps(JAWABAN))
        )
        assert hasil.sumber == "gemini"

    async def test_kuota_habis_memicu_cooldown(self):
        """Aturan ZOI: jangan terus mengirim permintaan setelah kuota habis."""
        ai_router.reset_cooldown()
        transport, dipanggil = _transport(
            httpx.Response(429, text="rate limited"), _balas_gemini(json.dumps(JAWABAN))
        )
        asli = httpx.AsyncClient

        class C(asli):
            def __init__(self, *a, **kw):
                kw["transport"] = transport
                super().__init__(*a, **kw)

        with patch.object(httpx, "AsyncClient", C):
            await ai_router.parse_transaksi(BUTUH_AI, KAT_KELUAR, KAT_MASUK, hari_ini=HARI_INI)
            panggilan_pertama = dipanggil["openrouter"]
            # Permintaan kedua: OpenRouter harus dilewati karena cooldown.
            await ai_router.parse_transaksi(BUTUH_AI, KAT_KELUAR, KAT_MASUK, hari_ini=HARI_INI)

        assert dipanggil["openrouter"] == panggilan_pertama


class TestKeduanyaGagal:
    async def test_jatuh_ke_pra_parser_bila_cukup(self):
        """Tebakan lemah masih lebih berguna daripada tidak ada apa-apa."""
        hasil, _, _ = await _jalankan(httpx.ConnectError("mati"), httpx.ConnectError("mati"))
        assert hasil.berhasil
        assert hasil.sumber == "parser"
        assert hasil.parsed.amount == Decimal("45000.00")
        # Tebakan jenisnya ditandai supaya bisa diberitahu ke pengguna.
        assert "transaction_type" in hasil.parsed.kurang

    async def test_gagal_total_bila_tanpa_jumlah(self):
        """Tanpa jumlah, transaksi tidak bermakna; tawarkan entri manual."""
        hasil, penolakan, _ = await _jalankan(
            httpx.ConnectError("mati"), httpx.ConnectError("mati"),
            teks="beli sesuatu di pasar",
        )
        assert not hasil.berhasil
        assert hasil.parsed is None
        assert penolakan is None
        assert hasil.sumber == "gagal"

    async def test_jawaban_sampah_dari_keduanya(self):
        hasil, _, _ = await _jalankan(
            _balas_openrouter("maaf saya tidak bisa membantu"),
            _balas_gemini("tentu! tapi saya tidak mengerti"),
        )
        # Jatuh ke pra-parser, bukan menyimpan sampah.
        assert hasil.sumber == "parser"


class TestPerlindunganData:
    async def test_pesan_berisi_pin_tidak_pernah_dikirim(self):
        hasil, penolakan, dipanggil = await _jalankan(
            _balas_openrouter(json.dumps(JAWABAN)),
            _balas_gemini(json.dumps(JAWABAN)),
            teks="pin atm 123456 bayar 20rb",
        )
        assert penolakan is not None
        assert hasil.parsed is None
        assert dipanggil == {"openrouter": 0, "gemini": 0}


class TestPembersihanJawaban:
    @pytest.mark.parametrize(
        "isi",
        [
            json.dumps(JAWABAN),
            f"```json\n{json.dumps(JAWABAN)}\n```",
            f"```\n{json.dumps(JAWABAN)}\n```",
            f"Tentu! Ini hasilnya: {json.dumps(JAWABAN)} Semoga membantu.",
        ],
    )
    async def test_markdown_fence_dan_kalimat_pengantar_dibersihkan(self, isi):
        """Model gratis sering mengabaikan instruksi 'JSON saja'."""
        hasil, _, _ = await _jalankan(_balas_openrouter(isi), httpx.ConnectError("mati"))
        assert hasil.berhasil
        assert hasil.parsed.amount == Decimal("45000.00")

    def test_kurung_kurawal_di_dalam_string_tidak_memotong_json(self):
        isi = json.dumps({**JAWABAN, "description": "Makan {siang} di luar"})
        hasil = ai_router._ke_parsed(isi, "uji", HARI_INI, Decimal("999999999"))
        assert hasil.description == "Makan {siang} di luar"


class TestValidasiJawaban:
    @pytest.mark.parametrize(
        "jawaban",
        [
            "bukan json sama sekali",
            '{"type":"transfer","amount":1000}',          # jenis tidak sah
            '{"type":"expense","amount":null}',            # jumlah tidak ada
            '{"type":"expense","amount":-5000}',           # negatif
            '{"type":"expense","amount":0}',               # nol
            '{"type":"expense","amount":"abc"}',           # bukan angka
            '{"type":"expense","amount":99999999999999}',  # melampaui batas
            '["bukan","objek"]',                           # bukan objek
        ],
    )
    def test_jawaban_tidak_sah_ditolak(self, jawaban):
        with pytest.raises(AIInvalidResponse):
            ai_router._ke_parsed(jawaban, "uji", HARI_INI, Decimal("999999999"))

    def test_jumlah_jadi_decimal_bukan_float(self):
        hasil = ai_router._ke_parsed(
            '{"type":"expense","amount":45000.55}', "uji", HARI_INI, Decimal("999999999")
        )
        assert isinstance(hasil.amount, Decimal)
        assert hasil.amount == Decimal("45000.55")

    def test_tanggal_tidak_terbaca_jatuh_ke_hari_ini(self):
        """Tanggal rusak bukan alasan menggagalkan transaksi."""
        hasil = ai_router._ke_parsed(
            '{"type":"expense","amount":1000,"date":"bukan-tanggal"}',
            "uji", HARI_INI, Decimal("999999999"),
        )
        assert hasil.transaction_date == HARI_INI

    def test_null_sebagai_string_dianggap_kosong(self):
        """Model gratis kadang menulis "null" sebagai teks, bukan null JSON."""
        hasil = ai_router._ke_parsed(
            '{"type":"expense","amount":1000,"location":"null","description":"-"}',
            "uji", HARI_INI, Decimal("999999999"),
        )
        assert hasil.location is None
        assert hasil.description is None

    def test_jenis_pemasukan_dibaca_benar(self):
        hasil = ai_router._ke_parsed(
            '{"type":"income","amount":750000,"category":"Penjualan"}',
            "uji", HARI_INI, Decimal("999999999"),
        )
        assert hasil.transaction_type == TransactionType.INCOME
