"""Fixture test.

Secara default seluruh test berjalan di **SQLite in-memory**, tanpa kredensial
dan tanpa jaringan — bisa dijalankan di Termux. Untuk menjalankan test yang
sama di PostgreSQL:

    ZOI_TEST_DATABASE_URL=postgresql+asyncpg://user:pass@host/db pytest

Catatan penting tentang presisi uang. SQLite tidak punya tipe DECIMAL; ia
menyimpan kolom NUMERIC sebagai float dan SQLAlchemy mengubahnya kembali ke
Decimal saat dibaca. Untuk nilai Rupiah dengan dua desimal, double
merepresentasikannya tepat, jadi test di SQLite sahih. Tapi **jaminan presisi
sesungguhnya ada di PostgreSQL NUMERIC**, jadi sebelum rilis jalankan juga
suite ini dengan ZOI_TEST_DATABASE_URL yang menunjuk ke PostgreSQL.
"""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio

# Konfigurasi dipasang SEBELUM app.config diimpor oleh modul mana pun.
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456789:TESTTESTTESTTESTTESTTESTTESTTESTTES")
os.environ.setdefault("ADMIN_TELEGRAM_ID", "100000001")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("OPENROUTER_MODELS", "meta-llama/llama-3.3-70b-instruct:free")
os.environ.setdefault("OPENROUTER_API_KEY", "test-or-key")
os.environ.setdefault("GEMINI_API_KEY", "test-gm-key")
os.environ.setdefault("TIMEZONE", "Asia/Jakarta")

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.database.models import (  # noqa: E402
    AccountSettings,
    Base,
    Category,
    TransactionType,
    User,
    UserRole,
)

TEST_DB_URL = os.environ.get("ZOI_TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")

KATEGORI_PENGELUARAN = [
    "Makanan & Minuman", "Transportasi", "Belanja Harian", "Tagihan & Utilitas",
    "Kesehatan", "Komunikasi & Pulsa", "Hiburan", "Lain-lain",
]
KATEGORI_PEMASUKAN = ["Gaji", "Usaha", "Penjualan", "Bonus", "Lain-lain"]


@pytest_asyncio.fixture
async def engine():
    e = create_async_engine(TEST_DB_URL)
    async with e.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield e
    async with e.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await e.dispose()


@pytest_asyncio.fixture
async def session(engine):
    """Session yang commit sungguhan, supaya perilaku transaksi ikut teruji."""
    maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with maker() as s:
        yield s


@pytest_asyncio.fixture
async def seeded(session):
    """Database dengan pengaturan, kategori, satu admin, dan satu member.

    Meniru hasil migrasi 002 dan 003.
    """
    session.add(
        AccountSettings(
            id=1,
            initial_balance=Decimal("1000000"),
            currency="IDR",
            timezone="Asia/Jakarta",
            member_can_export=True,
        )
    )
    for nama in KATEGORI_PENGELUARAN:
        session.add(Category(name=nama, transaction_type=TransactionType.EXPENSE))
    for nama in KATEGORI_PEMASUKAN:
        session.add(Category(name=nama, transaction_type=TransactionType.INCOME))

    admin = User(
        telegram_id=100000001, full_name="Admin Uji", role=UserRole.ADMIN, is_active=True
    )
    member = User(
        telegram_id=100000002, full_name="Member Uji", role=UserRole.MEMBER, is_active=True
    )
    nonaktif = User(
        telegram_id=100000003, full_name="Mantan Anggota", role=UserRole.MEMBER, is_active=False
    )
    session.add_all([admin, member, nonaktif])

    await session.commit()
    return {"session": session, "admin": admin, "member": member, "nonaktif": nonaktif}


@pytest.fixture
def hari_ini() -> date:
    """Tanggal tetap, supaya test tidak bergantung pada hari kalender nyata."""
    return date(2026, 11, 23)
