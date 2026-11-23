"""Penulisan jejak audit.

Tidak ada fungsi penghapusan di modul ini — dan itu disengaja. Jejak audit
yang bisa dihapus dari dalam aplikasi tidak ada gunanya sebagai jejak audit.
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AuditLog


async def log(
    session: AsyncSession,
    *,
    action: str,
    user_id: Optional[int] = None,
    telegram_id: Optional[int] = None,
    transaction_id: Optional[int] = None,
    details: Optional[dict] = None,
) -> AuditLog:
    """Catat satu kejadian.

    Pemanggil WAJIB memakai session yang sama dengan perubahan yang dicatat,
    supaya keduanya masuk dalam satu commit. Kalau transaksi dibatalkan, baris
    auditnya ikut dibatalkan — jejak audit tidak bisa menyimpang dari datanya.

    ``telegram_id`` tetap dicatat meski orang itu tidak ada di ``users``: itu
    satu-satunya cara mengetahui ada yang mencoba masuk tanpa izin.
    """
    entri = AuditLog(
        action=action,
        user_id=user_id,
        telegram_id=telegram_id,
        transaction_id=transaction_id,
        details=details,
    )
    session.add(entri)
    return entri


async def list_recent(session: AsyncSession, limit: int = 50) -> List[AuditLog]:
    hasil = await session.execute(
        select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    )
    return list(hasil.scalars())


async def list_by_transaction(session: AsyncSession, transaction_id: int) -> List[AuditLog]:
    hasil = await session.execute(
        select(AuditLog)
        .where(AuditLog.transaction_id == transaction_id)
        .order_by(AuditLog.id.asc())
    )
    return list(hasil.scalars())
