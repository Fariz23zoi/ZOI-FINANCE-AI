"""Prompt untuk provider AI.

Instruksi "balas JSON saja, tanpa backtick" ditiru dari alainrk/pago, yang
menyatakannya secara eksplisit di prompt-nya. Itu mengurangi pekerjaan
pembersihan keluaran — meski ``router.py`` tetap membersihkan markdown fence
karena model gratis sering mengabaikan instruksi format.

Prompt sengaja TIDAK memuat identitas pengguna, saldo, atau riwayat: hanya
teks transaksi dan daftar kategori. Lihat app/ai/scrub.py.
"""

from __future__ import annotations

from typing import Sequence

SYSTEM_PROMPT = (
    "Anda adalah mesin ekstraksi data transaksi keuangan berbahasa Indonesia. "
    "Anda hanya mengeluarkan JSON."
)

_TEMPLATE = """Ekstrak data transaksi keuangan dari pesan bahasa Indonesia berikut.

PESAN:
{teks}

TANGGAL HARI INI: {hari_ini}

KATEGORI PENGELUARAN yang tersedia:
{kategori_pengeluaran}

KATEGORI PEMASUKAN yang tersedia:
{kategori_pemasukan}

ATURAN:
1. "type" harus "expense" (uang keluar) atau "income" (uang masuk).
2. "amount" adalah angka dalam Rupiah, tanpa pemisah ribuan dan tanpa simbol.
   Pahami satuan Indonesia: "2 ribu" = 2000, "25rb" = 25000, "1 juta" = 1000000,
   "1,5 juta" = 1500000, "500.000" = 500000. Titik adalah pemisah ribuan;
   koma adalah desimal.
3. "category" HARUS salah satu nama dari daftar di atas yang sesuai jenisnya.
   Bila tidak ada yang cocok, pakai "Lain-lain".
4. "description" adalah ringkasan singkat kegiatannya dalam bahasa Indonesia,
   tanpa jumlah dan tanpa tanggal. Contoh: "Bayar parkir motor".
5. "location" adalah nama tempat bila disebut (biasanya setelah kata "di"),
   atau null bila tidak ada.
6. "date" dalam format YYYY-MM-DD. Pahami kata relatif terhadap TANGGAL HARI
   INI: "hari ini", "kemarin", "kemarin lusa", "N hari lalu". Bila tanggal
   tidak disebut, pakai TANGGAL HARI INI.
7. Bila jumlah uang tidak dapat ditentukan, set "amount" ke null. JANGAN
   mengarang angka.

Balas HANYA dengan objek JSON tanpa sintaks markdown. Jawaban Anda adalah
teks biasa berisi JSON yang langsung bisa diparse; jangan sertakan tiga
backtick atau penanda apa pun.

{{"type":"expense","amount":2000,"category":"Transportasi","description":"Bayar parkir motor","location":"Pasar Ciamis","date":"{hari_ini}"}}"""


def build_prompt(
    teks: str,
    hari_ini: str,
    kategori_pengeluaran: Sequence[str],
    kategori_pemasukan: Sequence[str],
) -> str:
    """Susun prompt ekstraksi.

    Daftar kategori dikirim apa adanya dari database sehingga model tidak
    pernah mengarang kategori yang tidak kita punya — kalau toh terjadi,
    ``category_repo.resolve`` masih menjatuhkannya ke "Lain-lain".
    """
    return _TEMPLATE.format(
        teks=teks.strip(),
        hari_ini=hari_ini,
        kategori_pengeluaran="\n".join(f"- {k}" for k in kategori_pengeluaran),
        kategori_pemasukan="\n".join(f"- {k}" for k in kategori_pemasukan),
    )
