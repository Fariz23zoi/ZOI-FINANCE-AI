"""Akses data anggota.

Repository hanya berisi query. Keputusan izin ada di
``app/services/permission_service.py`` — lihat docs/ARCHITECTURE.md bagian 3.
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User, UserRole


async def get_by_telegram_id(session: AsyncSession, telegram_id: int) -> Optional[User]:
    """Cari anggota berdasarkan Telegram ID numerik.

    Dipakai oleh middleware otorisasi pada setiap pesan masuk.
    """
    hasil = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return hasil.scalar_one_or_none()


async def get_by_id(session: AsyncSession, user_id: int) -> Optional[User]:
    return await session.get(User, user_id)


async def list_all(session: AsyncSession, hanya_aktif: bool = False) -> List[User]:
    stmt = select(User).order_by(User.role, User.full_name)
    if hanya_aktif:
        stmt = stmt.where(User.is_active.is_(True))
    hasil = await session.execute(stmt)
    return list(hasil.scalars())


async def create(
    session: AsyncSession,
    telegram_id: int,
    full_name: str,
    role: UserRole = UserRole.MEMBER,
    username: Optional[str] = None,
) -> User:
    user = User(
        telegram_id=telegram_id,
        full_name=full_name,
        username=username,
        role=role,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def set_role(session: AsyncSession, user_id: int, role: UserRole) -> None:
    """Ubah peran. Lewat ORM supaya objek di memori ikut benar."""
    user = await session.get(User, user_id)
    if user is not None:
        user.role = role
        await session.flush()


async def set_active(session: AsyncSession, user_id: int, aktif: bool) -> None:
    """Aktifkan atau nonaktifkan anggota.

    Anggota tidak pernah dihapus: ``Transaction.created_by`` memakai
    ``ON DELETE RESTRICT``, dan catatan keuangan lamanya harus tetap sah.
    """
    user = await session.get(User, user_id)
    if user is not None:
        user.is_active = aktif
        await session.flush()


async def touch_profile(
    session: AsyncSession, user: User, full_name: str, username: Optional[str]
) -> None:
    """Segarkan nama tampil dari Telegram bila berubah.

    Hanya informatif. Otorisasi tetap memakai ``telegram_id``, jadi perubahan
    nama atau username tidak pernah memengaruhi hak akses.
    """
    berubah = False
    if full_name and full_name != user.full_name:
        user.full_name = full_name
        berubah = True
    if username != user.username:
        user.username = username
        berubah = True
    if berubah:
        await session.flush()


async def count_admins(session: AsyncSession) -> int:
    """Jumlah admin aktif.

    Dipakai untuk mencegah admin terakhir menurunkan atau menonaktifkan
    dirinya sendiri — kalau itu terjadi, tidak ada lagi yang bisa mengelola
    anggota atau menghapus transaksi.
    """
    hasil = await session.execute(
        select(func.count())
        .select_from(User)
        .where(User.role == UserRole.ADMIN, User.is_active.is_(True))
    )
    return int(hasil.scalar_one())


async def set_pinned_message_id(
    session: AsyncSession, user_id: int, message_id: Optional[int]
) -> None:
    """Simpan nomor pesan papan saldo yang disemat.

    Dipakai lewat ORM, bukan UPDATE massal: objek User yang sedang dipegang
    pemanggil harus ikut berubah. UPDATE massal meninggalkannya menampilkan
    nomor lama, sehingga pembaruan berikutnya menyunting pesan yang salah.
    """
    pengguna = await session.get(User, user_id)
    if pengguna is None:
        return
    pengguna.pinned_message_id = message_id
    await session.flush()
