"""pinned message id

Menyimpan nomor pesan tersemat per anggota, untuk papan saldo yang selalu
terlihat di bagian atas percakapan Telegram.

Disimpan di database, bukan di memori proses. Lunafy memasang ulang
dependensi dan menjalankan ulang proses setiap kali server naik; nomor pesan
yang hanya ada di memori akan hilang di situ, dan bot akan mengirim pesan
baru setiap restart alih-alih memperbarui yang lama.

Per anggota, bukan satu untuk semua: buku kasnya bersama, tapi setiap
anggota punya percakapan pribadinya sendiri dengan bot, dan nomor pesan
hanya berlaku di dalam satu percakapan.

BigInteger: nomor pesan Telegram tidak dijamin muat di INTEGER.

Revision ID: 004
Revises: 003
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("pinned_message_id", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "pinned_message_id")
