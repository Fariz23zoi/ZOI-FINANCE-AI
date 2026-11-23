"""seed categories and settings

Menyemai kategori awal berbahasa Indonesia dan baris pengaturan tunggal.

Idempoten: memakai ``ON CONFLICT DO NOTHING`` pada PostgreSQL dan
``INSERT OR IGNORE`` pada SQLite, sehingga migrasi bisa dijalankan ulang
tanpa menggandakan data.

Nilai ditulis sebagai literal SQL, bukan sebagai parameter terikat. Alasannya
ditemukan lewat pengujian: dalam mode offline (``alembic upgrade --sql``),
parameter terikat pada ``sa.text()`` dirender menjadi ``NULL``, sehingga
seluruh INSERT gagal dengan "null value in column name violates not-null
constraint". Mode offline itulah yang dipakai untuk menghasilkan
``migrations/sql/001_003_skema_awal.sql``, jalur termudah untuk memasang skema
dari HP lewat SQL Editor Supabase.

Literal di sini aman dari injeksi: nilainya konstanta di file ini, bukan
masukan pengguna, dan tanda kutip tunggal tetap di-escape.

Kategori "Lain-lain" ada di kedua jenis dan merupakan tujuan aman ketika AI
tidak yakin — dengan begitu pencatatan tidak pernah gagal hanya karena
kategori tidak dikenal.

Revision ID: 002
Revises: 001
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

KATEGORI_PENGELUARAN = [
    "Makanan & Minuman",
    "Transportasi",
    "Belanja Harian",
    "Tagihan & Utilitas",
    "Kesehatan",
    "Pendidikan",
    "Rumah Tangga",
    "Komunikasi & Pulsa",
    "Hiburan",
    "Sosial & Keluarga",
    "Pekerjaan",
    "Lain-lain",
]

KATEGORI_PEMASUKAN = [
    "Gaji",
    "Usaha",
    "Penjualan",
    "Bonus",
    "Hadiah",
    "Pinjaman Masuk",
    "Lain-lain",
]


def _literal(teks: str) -> str:
    """Bungkus teks menjadi literal string SQL dengan kutip ter-escape."""
    return "'" + teks.replace("'", "''") + "'"


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    prefix = "INSERT INTO" if is_pg else "INSERT OR IGNORE INTO"
    abaikan_kat = "ON CONFLICT (name, transaction_type) DO NOTHING" if is_pg else ""
    abaikan_set = "ON CONFLICT (id) DO NOTHING" if is_pg else ""

    for jenis, daftar in (
        ("expense", KATEGORI_PENGELUARAN),
        ("income", KATEGORI_PEMASUKAN),
    ):
        for nama in daftar:
            bind.execute(
                sa.text(
                    f"{prefix} categories (name, transaction_type, is_active) "
                    f"VALUES ({_literal(nama)}, {_literal(jenis)}, true) {abaikan_kat}"
                )
            )

    # Baris pengaturan tunggal. Saldo awal sengaja 0: aturan ZOI menyatakan
    # saldo awal harus dikonfigurasi manual oleh administrator, bukan diisi
    # dengan angka tebakan.
    bind.execute(
        sa.text(
            f"{prefix} account_settings "
            "(id, initial_balance, currency, timezone, member_can_export) "
            f"VALUES (1, 0, 'IDR', 'Asia/Jakarta', true) {abaikan_set}"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()

    # Hanya hapus kategori yang belum pernah dipakai, supaya downgrade tidak
    # pernah merusak catatan keuangan yang sudah ada.
    bind.execute(
        sa.text(
            "DELETE FROM categories WHERE id NOT IN "
            "(SELECT DISTINCT category_id FROM transactions)"
        )
    )
    bind.execute(sa.text("DELETE FROM account_settings WHERE id = 1"))
