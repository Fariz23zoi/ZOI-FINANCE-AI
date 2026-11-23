"""Perlindungan data sebelum teks dikirim ke provider AI.

Aturan ZOI bagian 15: jangan pernah mengirim kunci API, password, PIN,
kredensial bank, atau informasi pribadi sensitif ke provider AI, dan kirim
hanya informasi minimum yang diperlukan untuk parsing.

Yang dikirim ke provider hanyalah teks transaksi — tanpa ``telegram_id``,
tanpa nama anggota, tanpa saldo, tanpa riwayat. Modul ini adalah lapisan
terakhir sebelum teks itu keluar.

Dua tingkat:

* **Tolak** — pesan tampak memuat kredensial. Lebih baik menolak dan
  menawarkan entri manual daripada mengirim rahasia ke pihak ketiga.
* **Redaksi** — pesan tampak memuat nomor panjang (kartu/rekening). Nomornya
  diganti ``[nomor]``; sisa pesan tetap bisa diparsing.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

#: Kata yang menandakan pesan kemungkinan memuat kredensial.
#: Dicocokkan sebagai kata utuh agar "pinjam" tidak tertangkap oleh "pin".
KATA_KREDENSIAL = (
    "pin", "password", "sandi", "kata sandi", "otp", "cvv", "cvc",
    "kode verifikasi", "kode otp", "mpin", "token bank", "api key", "apikey",
    "secret key", "seed phrase", "private key", "m-pin", "pin atm",
)

#: Deret 12+ digit: panjang nomor kartu (13–19) dan rekening bank Indonesia.
POLA_NOMOR_PANJANG = re.compile(r"\b\d(?:[ -]?\d){11,23}\b")

#: Pola kunci API yang umum.
POLA_KUNCI_API = re.compile(r"\b(sk-[A-Za-z0-9_-]{8,}|AIza[A-Za-z0-9_-]{10,}|ghp_[A-Za-z0-9]{20,})\b")


def periksa(teks: str) -> Tuple[bool, Optional[str], str]:
    """Periksa dan bersihkan teks sebelum dikirim ke AI.

    :return: ``(aman, alasan_penolakan, teks_bersih)``.
             Bila ``aman`` False, ``teks_bersih`` tidak boleh dikirim ke mana
             pun dan pemanggil harus menawarkan entri manual.

    Example:
        >>> periksa("beli bensin 30rb")[0]
        True
        >>> periksa("pin atm saya 123456")[0]
        False
        >>> periksa("transfer ke 1234567890123456 sebesar 50rb")[2]
        'transfer ke [nomor] sebesar 50rb'
    """
    if not teks or not teks.strip():
        return False, "Pesan kosong.", ""

    rendah = teks.lower()

    # Diperiksa lebih dulu daripada kata kunci umum supaya alasan penolakan
    # yang dilihat pengguna tepat ("kunci API", bukan "PIN atau password").
    if POLA_KUNCI_API.search(teks):
        return (
            False,
            "Pesan ini sepertinya memuat kunci API. Pesan seperti ini tidak dikirim "
            "ke layanan AI. Gunakan /catat untuk mencatat transaksinya.",
            "",
        )

    for kata in KATA_KREDENSIAL:
        if re.search(rf"(?<![\w]){re.escape(kata)}(?![\w])", rendah):
            return (
                False,
                "Pesan ini sepertinya memuat data rahasia (seperti PIN, password, "
                "atau kode OTP). Demi keamanan, pesan seperti ini tidak dikirim ke "
                "layanan AI. Silakan catat transaksinya lewat /catat tanpa menyertakan "
                "data rahasia.",
                "",
            )

    bersih = POLA_NOMOR_PANJANG.sub("[nomor]", teks)

    return True, None, bersih
