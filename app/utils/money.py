"""Penanganan uang Rupiah.

Aturan keras: uang SELALU Decimal, NEVER float. Satu operasi float pada nilai
uang bisa menimbulkan selisih yang tidak pernah bisa dijelaskan ke anggota lain.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Optional

#: Dua angka desimal — sesuai NUMERIC(18, 2) di PostgreSQL.
SEN = Decimal("0.01")


def to_decimal(value) -> Decimal:
    """Ubah nilai apa pun menjadi Decimal uang yang aman.

    Nilai float sengaja dilewatkan ``str()`` lebih dulu supaya tidak mewarisi
    galat biner float (``Decimal(0.1)`` menghasilkan 0.1000000000000000055...,
    sedangkan ``Decimal(str(0.1))`` menghasilkan tepat 0.1).

    :raises ValueError: bila nilai tidak bisa ditafsirkan sebagai angka.
    """
    if isinstance(value, Decimal):
        dec = value
    else:
        try:
            dec = Decimal(str(value).strip())
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError(f"Bukan nilai uang yang sah: {value!r}") from exc

    if not dec.is_finite():
        raise ValueError(f"Nilai uang tidak terbatas: {value!r}")

    return dec.quantize(SEN, rounding=ROUND_HALF_UP)


def format_rupiah(value, with_prefix: bool = True) -> str:
    """Format nilai menjadi Rupiah gaya Indonesia.

    Pemisah ribuan titik, desimal koma, dan ``,00`` disembunyikan karena
    transaksi Rupiah sehari-hari hampir selalu bulat.

    Example:
        >>> format_rupiah(Decimal("2000"))
        'Rp2.000'
        >>> format_rupiah(Decimal("1500000.50"))
        'Rp1.500.000,50'
        >>> format_rupiah(Decimal("-2000"))
        '-Rp2.000'
    """
    dec = to_decimal(value)
    negatif = dec < 0
    dec = abs(dec)

    rupiah = int(dec)
    sen = int((dec - rupiah) * 100)

    teks = f"{rupiah:,}".replace(",", ".")
    if sen:
        teks = f"{teks},{sen:02d}"

    if with_prefix:
        teks = f"Rp{teks}"
    return f"-{teks}" if negatif else teks


def parse_indonesian_amount(text: str) -> Optional[Decimal]:
    """Baca jumlah uang dari tulisan Indonesia sehari-hari.

    Menangani pengali ("ribu", "rb", "k", "juta", "jt", "m"), pemisah ribuan
    titik, dan desimal koma.

    Bagian tersulit adalah titik: dalam penulisan Indonesia titik adalah
    pemisah ribuan ("500.000" = lima ratus ribu), tetapi orang juga menulis
    "1.5 juta" dengan maksud satu setengah juta. Aturan yang dipakai:
    titik dianggap pemisah ribuan hanya bila diikuti tepat tiga angka
    dan tidak ada pengali; selain itu dianggap desimal.

    :return: Decimal, atau None bila tidak ada angka yang bisa dibaca.

    Example:
        >>> parse_indonesian_amount("2 ribu")
        Decimal('2000.00')
        >>> parse_indonesian_amount("25rb")
        Decimal('25000.00')
        >>> parse_indonesian_amount("1,5 juta")
        Decimal('1500000.00')
        >>> parse_indonesian_amount("500.000")
        Decimal('500000.00')
    """
    import re

    if not text:
        return None

    lowered = text.lower().strip()

    pengali = {
        "ribu": 1_000, "rb": 1_000, "rbu": 1_000, "k": 1_000, "ribuan": 1_000,
        "juta": 1_000_000, "jt": 1_000_000, "jtan": 1_000_000,
        "miliar": 1_000_000_000, "milyar": 1_000_000_000, "m": 1_000_000_000,
    }

    pola = (
        r"(?<![\d.,])"
        r"(\d{1,3}(?:\.\d{3})+|\d+(?:[.,]\d+)?)"
        r"\s*"
        r"(ribu(?:an)?|rb(?:u)?|juta(?:n)?|jt(?:an)?|miliar|milyar|[km])?"
        r"(?![\w])"
    )

    cocok = re.search(pola, lowered)
    if not cocok:
        return None

    angka_mentah, satuan = cocok.group(1), cocok.group(2)

    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", angka_mentah) and not satuan:
        # Titik sebagai pemisah ribuan: "500.000"
        bersih = angka_mentah.replace(".", "")
    else:
        # Titik atau koma sebagai desimal: "1,5 juta" / "1.5 juta"
        bersih = angka_mentah.replace(".", "X").replace(",", ".")
        if bersih.count("X") == 1 and "." not in bersih:
            bersih = bersih.replace("X", ".")
        else:
            bersih = bersih.replace("X", "")

    try:
        nilai = Decimal(bersih)
    except InvalidOperation:
        return None

    if satuan:
        nilai *= pengali[satuan]

    if nilai <= 0:
        return None

    return to_decimal(nilai)
