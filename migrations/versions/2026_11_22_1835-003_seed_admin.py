"""seed admin

Mendaftarkan administrator pertama dari ADMIN_TELEGRAM_ID.

Ini satu-satunya cara admin masuk ke sistem: tidak ada perintah Telegram yang
bisa mengangkat diri sendiri menjadi admin, dan tidak ada admin bawaan. Tanpa
langkah ini bot akan menolak semua orang — itu memang disengaja, karena bot
keuangan yang menerima siapa saja lebih berbahaya daripada bot yang menolak
pemiliknya.

Idempoten: menjalankan ulang tidak menggandakan baris, dan bila Telegram ID
sudah ada, perannya dinaikkan menjadi admin.

Ditulis sebagai SATU pernyataan ``INSERT ... ON CONFLICT DO UPDATE``, bukan
"SELECT dulu lalu pilih INSERT atau UPDATE". Alasannya ditemukan lewat
pengujian: dalam mode offline (``alembic upgrade --sql``) Alembic tidak bisa
membaca hasil query, sehingga versi bercabang menghasilkan
``SELECT id FROM users WHERE telegram_id = NULL`` lalu melewatkan INSERT-nya
sama sekali — gagal tanpa pesan error apa pun. Satu pernyataan juga bebas dari
kondisi balapan bila dua proses migrasi berjalan bersamaan.

``ON CONFLICT`` didukung PostgreSQL maupun SQLite (3.24+), jadi pernyataannya
sama untuk keduanya.

Revision ID: 003
Revises: 002
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from app.config import get_settings

    # Dibaca dari konfigurasi, dan ditulis sebagai literal supaya mode offline
    # (--sql) menghasilkan pernyataan yang benar. Nilainya sudah divalidasi
    # sebagai integer positif oleh app/config.py, jadi tidak ada risiko
    # injeksi dari interpolasi ini.
    admin_id = int(get_settings().admin_telegram_id)

    op.get_bind().execute(
        sa.text(
            "INSERT INTO users (telegram_id, full_name, role, is_active) "
            f"VALUES ({admin_id}, 'Administrator', 'admin', true) "
            "ON CONFLICT (telegram_id) DO UPDATE "
            "SET role = 'admin', is_active = true"
        )
    )


def downgrade() -> None:
    from app.config import get_settings

    admin_id = int(get_settings().admin_telegram_id)
    bind = op.get_bind()

    # Jangan hapus bila admin sudah pernah mencatat transaksi: created_by
    # memakai ON DELETE RESTRICT, dan catatan keuangan tidak boleh hilang.
    punya_transaksi = bind.execute(
        sa.text(
            "SELECT 1 FROM transactions t JOIN users u ON u.id = t.created_by "
            "WHERE u.telegram_id = :tid LIMIT 1"
        ),
        {"tid": admin_id},
    ).first()

    if not punya_transaksi:
        bind.execute(
            sa.text("DELETE FROM users WHERE telegram_id = :tid"), {"tid": admin_id}
        )
