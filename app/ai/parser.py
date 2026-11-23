"""Pra-parser bahasa Indonesia — tingkat pertama, biaya Rp0.

Pendekatannya ditiru dari ``parse_natural_operation`` di
nikamurkaa/finance-helper (regex deterministik untuk teks bebas), ditulis
ulang sepenuhnya untuk bahasa Indonesia.

Alasan tingkat ini ada dan dijalankan LEBIH DULU, bukan hanya demi
penghematan: regex itu deterministik dan bisa diuji penuh. Kalimat yang paling
sering dipakai sehari-hari ("beli bensin 30rb") karena itu tidak pernah
bergantung pada ketersediaan layanan luar. Ketika kedua provider AI mati,
tingkat ini tetap jalan.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Optional

from app.ai.schema import ParsedTransaction
from app.database.models import TransactionType
from app.utils.dates import local_today, parse_indonesian_date
from app.utils.money import parse_indonesian_amount

#: Kata yang menandai uang MASUK.
KATA_PEMASUKAN = (
    "dapat", "dapet", "terima", "diterima", "masuk", "pemasukan", "penghasilan",
    "gajian", "gaji", "bonus", "untung", "laba", "hasil penjualan", "terjual",
    "dibayar", "honor", "komisi", "thr", "hadiah", "dikasih", "dikasi",
    "transferan masuk", "pendapatan", "omzet", "setoran",
)

#: Kata yang menandai uang KELUAR.
KATA_PENGELUARAN = (
    "bayar", "beli", "belanja", "keluar", "pengeluaran", "biaya", "ongkos",
    "sewa", "iuran", "cicilan", "angsuran", "isi", "top up", "topup", "jajan",
    "makan", "traktir", "servis", "service", "perbaikan", "tagihan", "setor",
    "sedekah", "zakat", "donasi", "pinjam", "bensin", "pulsa",
)

#: Petunjuk kategori. Kunci = nama kategori hasil seed migrasi 002.
#: Pemetaan ini hanya tebakan awal; bila gagal, ``category_repo.resolve``
#: memakai "Lain-lain" sehingga transaksi tidak pernah gagal karena kategori.
PETUNJUK_KATEGORI = {
    "Makanan & Minuman": (
        "makan", "makanan", "minum", "minuman", "nasi", "sarapan", "makan siang",
        "makan malam", "jajan", "kopi", "ngopi", "teh", "snack", "gorengan",
        "warteg", "warung", "bakso", "mie", "ayam", "sate", "martabak", "kue",
        "roti", "es ", "jus", "catering", "lauk",
    ),
    "Transportasi": (
        "parkir", "bensin", "pertalite", "pertamax", "solar", "bbm", "ojek",
        "ojol", "gojek", "grab", "angkot", "bus", "kereta", "tiket", "tol",
        "transport", "travel", "taksi", "taxi", "becak", "ongkos jalan",
        "servis motor", "ganti oli", "oli", "tambal ban", "cuci motor",
    ),
    "Belanja Harian": (
        "beras", "gula", "minyak goreng", "telur", "sayur", "buah", "daging",
        "ikan", "bumbu", "sembako", "pasar", "belanja harian", "belanja bulanan",
        "indomaret", "alfamart", "supermarket", "galon", "gas", "lpg",
    ),
    "Tagihan & Utilitas": (
        "listrik", "pln", "token listrik", "air", "pdam", "wifi", "internet",
        "indihome", "tagihan", "iuran", "sampah", "keamanan", "bpjs",
    ),
    "Kesehatan": (
        "obat", "apotek", "dokter", "periksa", "rumah sakit", "puskesmas",
        "klinik", "vitamin", "berobat", "kesehatan", "gigi", "lab",
    ),
    "Pendidikan": (
        "sekolah", "spp", "kuliah", "buku", "alat tulis", "les", "bimbel",
        "seragam", "pendidikan", "kursus", "ujian", "lks",
    ),
    "Rumah Tangga": (
        "sabun", "deterjen", "sikat", "pel", "perabot", "perkakas", "lampu",
        "cat", "semen", "paku", "renovasi", "perbaikan rumah", "sapu",
        "tisu", "pasta gigi", "shampo", "sampo",
    ),
    "Komunikasi & Pulsa": (
        "pulsa", "kuota", "paket data", "telkomsel", "indosat", "xl ", "axis",
        "tri ", "smartfren", "isi pulsa", "nelpon",
    ),
    "Hiburan": (
        "nonton", "bioskop", "film", "game", "langganan", "netflix", "spotify",
        "youtube premium", "wisata", "liburan", "rekreasi", "karaoke", "hiburan",
    ),
    "Sosial & Keluarga": (
        "hajatan", "kondangan", "nyumbang", "sumbangan", "sedekah", "zakat",
        "infaq", "donasi", "arisan", "kado", "hadiah untuk", "jenguk",
        "takziah", "keluarga", "anak", "istri", "suami", "orang tua",
    ),
    "Pekerjaan": (
        "alat kerja", "seragam kerja", "fotokopi", "print", "materai",
        "administrasi", "pekerjaan", "proyek", "lembur", "dinas",
    ),
    "Gaji": ("gaji", "gajian", "upah", "salary", "payroll"),
    "Usaha": ("usaha", "dagang", "toko", "warung saya", "omzet", "jualan"),
    "Penjualan": ("jual", "terjual", "penjualan", "laku", "hasil penjualan"),
    "Bonus": ("bonus", "thr", "insentif", "komisi", "tunjangan"),
    "Hadiah": ("hadiah", "dikasih", "dikasi", "angpao", "hibah"),
    "Pinjaman Masuk": ("pinjam", "pinjaman", "hutang", "utang", "ngutang"),
}

#: Pola lokasi: "di <tempat>" sampai akhir kalimat atau tanda baca.
POLA_LOKASI = re.compile(
    r"\bdi\s+((?:(?!\b(?:harga|seharga|sebesar|senilai)\b)[\w.'-]+(?:\s+|$)){1,4})",
    re.IGNORECASE,
)

#: Kata yang tidak boleh dianggap nama lokasi.
BUKAN_LOKASI = {
    "rumah", "sini", "situ", "sana", "atas", "bawah", "dalam", "luar", "jalan",
    "mana", "tempat", "waktu", "hari", "bulan", "tahun", "pasar",
}


def _tentukan_jenis(teks: str) -> Optional[TransactionType]:
    """Tentukan pemasukan atau pengeluaran dari kata kunci.

    Bila keduanya muncul, yang posisinya lebih awal menang — dalam bahasa
    Indonesia kata kerja utama hampir selalu di depan ("bayar utang" adalah
    pengeluaran meski memuat kata "utang").
    """
    posisi_masuk = min(
        (teks.find(k) for k in KATA_PEMASUKAN if k in teks), default=-1
    )
    posisi_keluar = min(
        (teks.find(k) for k in KATA_PENGELUARAN if k in teks), default=-1
    )

    if posisi_masuk == -1 and posisi_keluar == -1:
        return None
    if posisi_keluar == -1:
        return TransactionType.INCOME
    if posisi_masuk == -1:
        return TransactionType.EXPENSE

    return TransactionType.EXPENSE if posisi_keluar <= posisi_masuk else TransactionType.INCOME


def _tebak_kategori(teks: str, jenis: TransactionType) -> Optional[str]:
    """Tebak kategori dari petunjuk kata kunci.

    Hanya kategori yang sejenis yang dipertimbangkan, supaya "jual" tidak
    pernah menjadi kategori pengeluaran. Petunjuk terpanjang yang cocok
    dimenangkan ("hasil penjualan" mengalahkan "jual").
    """
    kategori_pemasukan = {"Gaji", "Usaha", "Penjualan", "Bonus", "Hadiah", "Pinjaman Masuk"}

    terbaik: Optional[str] = None
    panjang_terbaik = 0

    for kategori, petunjuk in PETUNJUK_KATEGORI.items():
        sejenis = (
            kategori in kategori_pemasukan
            if jenis == TransactionType.INCOME
            else kategori not in kategori_pemasukan
        )
        if not sejenis:
            continue

        for p in petunjuk:
            if p in teks and len(p) > panjang_terbaik:
                terbaik, panjang_terbaik = kategori, len(p)

    return terbaik


def _ambil_lokasi(teks_asli: str) -> Optional[str]:
    """Ambil lokasi dari pola "di <tempat>".

    Dikembalikan dengan kapitalisasi judul karena ini nama tempat.
    "di pasar Ciamis" -> "Pasar Ciamis".
    """
    cocok = POLA_LOKASI.search(teks_asli)
    if not cocok:
        return None

    mentah = cocok.group(1).strip(" .,;:")
    if not mentah:
        return None

    kata = [k for k in mentah.split() if k]

    # Buang token angka dan satuan jumlah di ujung. Pola lokasi berjalan pada
    # teks asli yang masih memuat jumlah, sehingga "di apotek kimia farma
    # 35 ribu" akan menyeret "35" ke dalam nama lokasi bila tidak dipangkas.
    _SATUAN = {"ribu", "ribuan", "rb", "rbu", "juta", "jutaan", "jt", "jtan",
               "miliar", "milyar", "k", "m", "rp"}
    while kata and (
        re.fullmatch(
            r"[\d.,]+(?:ribu(?:an)?|rb(?:u)?|juta(?:n)?|jt(?:an)?|miliar|milyar|[km])?",
            kata[-1],
            re.IGNORECASE,
        )
        or kata[-1].lower() in _SATUAN
        or kata[-1].lower() in BUKAN_LOKASI
    ):
        kata.pop()

    if not kata:
        return None

    # Kalau satu kata dan kata itu generik, bukan lokasi yang berguna.
    if len(kata) == 1 and kata[0].lower() in BUKAN_LOKASI:
        return None

    hasil = " ".join(kata)
    if len(hasil) < 3 or len(hasil) > 100:
        return None

    return " ".join(w if w.isupper() else w.capitalize() for w in hasil.split())


def _buat_deskripsi(teks_asli: str) -> Optional[str]:
    """Susun deskripsi dari pesan asli dengan membuang bagian jumlah dan waktu.

    Yang tersisa adalah inti kegiatannya: "Bayar parkir motor 2 ribu di pasar
    Ciamis" menjadi "Bayar parkir motor".
    """
    hasil = teks_asli

    # Buang angka beserta satuannya.
    hasil = re.sub(
        r"\b\d{1,3}(?:\.\d{3})+|\b\d+(?:[.,]\d+)?\s*"
        r"(?:ribu(?:an)?|rb(?:u)?|juta(?:n)?|jt(?:an)?|miliar|milyar|[km])?\b",
        " ",
        hasil,
        flags=re.IGNORECASE,
    )
    # Buang kata waktu relatif.
    hasil = re.sub(
        r"\b(hari\s+ini|kemarin\s+lusa|kemarin|kemaren|besok|lusa|tadi(\s+\w+)?|"
        r"sekarang|\d+\s+hari\s+(?:yang\s+)?lalu)\b",
        " ",
        hasil,
        flags=re.IGNORECASE,
    )
    # Buang bagian lokasi.
    hasil = POLA_LOKASI.sub(" ", hasil)
    # Buang penanda harga yang menggantung.
    hasil = re.sub(
        r"\b(rp|seharga|sebesar|senilai|harga|sejumlah|total)\b", " ", hasil, flags=re.IGNORECASE
    )

    hasil = re.sub(r"[\s,;:.]+", " ", hasil).strip(" -.,")

    if len(hasil) < 2:
        return None

    return hasil[0].upper() + hasil[1:] if hasil else None


def parse(teks: str, hari_ini: Optional[date] = None) -> ParsedTransaction:
    """Parse pesan Indonesia menjadi calon transaksi, tanpa biaya.

    Tidak pernah melempar exception dan tidak pernah mengarang nilai: field
    yang tidak bisa ditentukan dibiarkan None dan dicatat di ``kurang``,
    sehingga pemanggil bisa memilih naik ke tingkat AI atau menanyakannya ke
    pengguna.

    Example:
        >>> h = parse("Bayar parkir motor 2 ribu di pasar Ciamis")
        >>> h.transaction_type.value, str(h.amount), h.location
        ('expense', '2000.00', 'Pasar Ciamis')
    """
    hasil = ParsedTransaction(sumber="parser")

    if not teks or not teks.strip():
        hasil.kurang = ["transaction_type", "amount"]
        return hasil

    asli = teks.strip()
    rendah = asli.lower()

    hasil.amount = parse_indonesian_amount(rendah)
    hasil.transaction_type = _tentukan_jenis(rendah)

    # Default pengeluaran bila ada jumlah tapi tidak ada kata kerja yang
    # mengisyaratkan arah. Dalam pemakaian sehari-hari mayoritas catatan adalah
    # pengeluaran — tapi ini tetap dicatat di `kurang` supaya tingkat AI
    # berikutnya tahu bahwa tebakan ini lemah, dan pengguna melihatnya di
    # layar konfirmasi sebelum tersimpan.
    if hasil.transaction_type is None and hasil.amount is not None:
        hasil.transaction_type = TransactionType.EXPENSE
        hasil.kurang.append("transaction_type")

    if hasil.transaction_type is not None:
        hasil.category = _tebak_kategori(rendah, hasil.transaction_type)
        if hasil.category is None:
            hasil.kurang.append("category")

    hasil.transaction_date = parse_indonesian_date(rendah, today=hari_ini) or (
        hari_ini or local_today()
    )
    hasil.location = _ambil_lokasi(asli)
    hasil.description = _buat_deskripsi(asli)

    if hasil.amount is None:
        hasil.kurang.append("amount")

    return hasil
