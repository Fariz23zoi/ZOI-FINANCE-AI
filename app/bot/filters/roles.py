"""Filter peran untuk aiogram.

PENTING: filter ini hanya untuk UX — menentukan handler mana yang menanggapi
dan memberi pesan yang ramah. Keputusan keamanan sesungguhnya ada di
``app/services/permission_service.py`` dan dipanggil ulang di dalam service.
Jangan pernah mengandalkan filter saja untuk menjaga hak akses.
"""

from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import TelegramObject

from app.database.models import User


class IsAdmin(BaseFilter):
    """Lolos bila pengguna adalah admin aktif."""

    async def __call__(self, event: TelegramObject, user: User | None = None, **kwargs) -> bool:
        return bool(user and user.is_active and user.is_admin)


class IsMember(BaseFilter):
    """Lolos bila pengguna adalah anggota aktif (termasuk admin)."""

    async def __call__(self, event: TelegramObject, user: User | None = None, **kwargs) -> bool:
        return bool(user and user.is_active)
