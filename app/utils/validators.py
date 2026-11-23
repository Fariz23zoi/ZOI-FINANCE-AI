"""Validasi dan sanitasi input pengguna.

Pola validasi jumlah berbasis Decimal diadaptasi dari RibasomR/finance-bot
(MIT, Copyright (c) 2025-2026 RibasomR) dan disesuaikan untuk Rupiah —
batas atas mengikuti NUMERIC(18,2) dan pesan galat berbahasa Indonesia.
"""

from __future__ import annotations

import html
import re
import time
from collections import defaultdict, deque
from decimal import Decimal
from typing import Deque, Dict, Optional, Tuple

from app.utils.money import to_decimal

#: Batas atas sesuai NUMERIC(18, 2) dengan ruang aman.
BATAS_MUTLAK = Decimal("999999999999.99")


def bersihkan_teks(text: Optional[str], maks: Optional[int] = None) -> str:
    """Bersihkan teks pengguna sebelum disimpan atau ditampilkan.

    Melakukan escape HTML (aiogram mengirim pesan dengan parse_mode HTML,
    sehingga "<b>" dari pengguna bisa merusak format pesan) dan membuang
    karakter kontrol.
    """
    if not text:
        return ""

    hasil = html.escape(str(text).strip())
    hasil = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", hasil)
    hasil = re.sub(r"\s{3,}", " ", hasil)

    if maks and len(hasil) > maks:
        hasil = hasil[:maks].rstrip()
    return hasil


def validasi_jumlah(
    nilai, batas_maks: Optional[Decimal] = None
) -> Tuple[bool, Optional[Decimal], Optional[str]]:
    """Validasi jumlah uang.

    :return: ``(valid, jumlah, pesan_galat)``. Bila valid, ``pesan_galat`` None.

    Example:
        >>> validasi_jumlah("2000")[:2]
        (True, Decimal('2000.00'))
        >>> validasi_jumlah("-5")[0]
        False
    """
    batas = batas_maks if batas_maks is not None else BATAS_MUTLAK

    try:
        jumlah = to_decimal(nilai)
    except ValueError:
        return False, None, "Jumlah tidak dikenali. Tulis angkanya saja, misalnya 25000 atau 25rb."

    if jumlah <= 0:
        return False, None, "Jumlah harus lebih besar dari nol."
    if jumlah > batas:
        from app.utils.money import format_rupiah

        return False, None, f"Jumlah terlalu besar. Maksimum {format_rupiah(batas)}."

    return True, jumlah, None


def validasi_telegram_id(nilai) -> Tuple[bool, Optional[int], Optional[str]]:
    """Validasi Telegram ID numerik.

    Username ditolak secara eksplisit: username bisa diganti kapan saja oleh
    pemiliknya, sehingga tidak aman sebagai dasar otorisasi.
    """
    teks = str(nilai).strip()

    if teks.startswith("@") or not teks.lstrip("-").isdigit():
        return False, None, (
            "Masukkan Telegram ID numerik, bukan username. "
            "Anggota bisa melihat ID-nya dengan mengirim pesan ke @userinfobot."
        )

    tid = int(teks)
    if tid <= 0:
        return False, None, "Telegram ID harus berupa angka positif."
    if tid > 2**63 - 1:
        return False, None, "Telegram ID di luar jangkauan yang sah."

    return True, tid, None


class RateLimiter:
    """Pembatas laju sederhana berbasis memori (sliding window).

    Sengaja tanpa Redis: untuk 2–3 pengguna, Redis hanya menambah
    infrastruktur yang harus dirawat. Lihat docs/REPOSITORY_AUDIT.md bagian 9
    ("Jangan dipakai": Redis untuk rate limiting).

    Konsekuensi yang diterima: hitungan ter-reset saat proses restart. Untuk
    tiga pengguna yang saling mengenal, itu tidak berisiko.
    """

    def __init__(self, maks_permintaan: int = 20, jendela_detik: int = 60) -> None:
        self.maks = maks_permintaan
        self.jendela = jendela_detik
        self._jejak: Dict[int, Deque[float]] = defaultdict(deque)

    def diizinkan(self, user_id: int) -> bool:
        """True bila pengguna masih dalam batas; mencatat permintaan ini."""
        sekarang = time.monotonic()
        jejak = self._jejak[user_id]

        while jejak and sekarang - jejak[0] > self.jendela:
            jejak.popleft()

        if len(jejak) >= self.maks:
            return False

        jejak.append(sekarang)
        return True

    def sisa_detik(self, user_id: int) -> int:
        """Perkiraan detik sampai pengguna boleh mengirim lagi."""
        jejak = self._jejak.get(user_id)
        if not jejak:
            return 0
        return max(0, int(self.jendela - (time.monotonic() - jejak[0])) + 1)
