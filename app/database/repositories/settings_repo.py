"""Akses data pengaturan buku kas (baris tunggal, id=1)."""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AccountSettings

ID_TUNGGAL = 1


async def get(session: AsyncSession) -> Optional[AccountSettings]:
    """Ambil baris pengaturan.

    Mengembalikan None hanya bila migrasi 002 belum dijalankan. Pemanggil
    harus menangani itu dengan pesan jelas, bukan dengan menebak nilai
    default — saldo awal yang ditebak akan membuat seluruh saldo salah.
    """
    return await session.get(AccountSettings, ID_TUNGGAL)


async def set_initial_balance(session: AsyncSession, saldo: Decimal) -> bool:
    hasil = await session.execute(
        update(AccountSettings)
        .where(AccountSettings.id == ID_TUNGGAL)
        .values(initial_balance=saldo)
    )
    return bool(hasil.rowcount)


async def set_member_can_export(session: AsyncSession, boleh: bool) -> bool:
    hasil = await session.execute(
        update(AccountSettings)
        .where(AccountSettings.id == ID_TUNGGAL)
        .values(member_can_export=boleh)
    )
    return bool(hasil.rowcount)
