"""Akses data kategori."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Category, TransactionType

#: Kategori tujuan aman ketika kategori hasil AI tidak dikenali.
NAMA_FALLBACK = "Lain-lain"


async def list_by_type(
    session: AsyncSession, jenis: TransactionType, hanya_aktif: bool = True
) -> List[Category]:
    stmt = select(Category).where(Category.transaction_type == jenis)
    if hanya_aktif:
        stmt = stmt.where(Category.is_active.is_(True))
    hasil = await session.execute(stmt.order_by(Category.name))
    return list(hasil.scalars())


async def get_by_id(session: AsyncSession, category_id: int) -> Optional[Category]:
    return await session.get(Category, category_id)


async def find_by_name(
    session: AsyncSession, nama: str, jenis: TransactionType
) -> Optional[Category]:
    """Cari kategori berdasarkan nama, toleran terhadap variasi penulisan.

    Tiga tahap, dari paling ketat ke paling longgar:

    1. sama persis (tidak peduli huruf besar/kecil)
    2. nama kategori memuat teks pencarian
    3. teks pencarian memuat nama kategori

    Tahap 2 dan 3 perlu karena keluaran AI tidak selalu sama persis dengan
    daftar kita: AI bisa menjawab "Transportasi / Parkir" atau "transport".
    Pencocokan longgar lebih baik daripada menolak transaksi — dan kalau
    semuanya gagal, ``get_fallback`` tetap memberi kategori yang sah.
    """
    if not nama:
        return None

    bersih = nama.strip().lower()
    kandidat = await list_by_type(session, jenis)

    for k in kandidat:
        if k.name.lower() == bersih:
            return k
    for k in kandidat:
        if bersih in k.name.lower():
            return k
    for k in kandidat:
        if k.name.lower() in bersih:
            return k
    return None


async def get_fallback(session: AsyncSession, jenis: TransactionType) -> Optional[Category]:
    """Ambil kategori "Lain-lain" untuk jenis tertentu."""
    hasil = await session.execute(
        select(Category).where(
            func.lower(Category.name) == NAMA_FALLBACK.lower(),
            Category.transaction_type == jenis,
        )
    )
    return hasil.scalar_one_or_none()


async def resolve(
    session: AsyncSession, nama: Optional[str], jenis: TransactionType
) -> Optional[Category]:
    """Tentukan kategori dari nama, jatuh ke "Lain-lain" bila tidak ketemu."""
    if nama:
        cocok = await find_by_name(session, nama, jenis)
        if cocok:
            return cocok
    return await get_fallback(session, jenis)
