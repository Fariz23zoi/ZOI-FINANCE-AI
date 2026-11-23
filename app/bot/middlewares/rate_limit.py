"""Middleware pembatas laju.

Berbasis memori, tanpa Redis. Untuk 2–3 pengguna, Redis hanya menambah
infrastruktur yang harus dirawat dan satu titik kegagalan lagi — lihat
docs/REPOSITORY_AUDIT.md bagian 9.

Tujuannya bukan menahan serangan (middleware auth sudah menolak orang luar),
melainkan mencegah satu anggota membanjiri kuota AI gratis karena menekan
tombol berulang kali.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.utils.logger import get_logger
from app.utils.validators import RateLimiter

logger = get_logger(__name__)


class RateLimitMiddleware(BaseMiddleware):
    def __init__(self, maks_permintaan: int = 20, jendela_detik: int = 60) -> None:
        super().__init__()
        self._limiter = RateLimiter(maks_permintaan, jendela_detik)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        if tg_user is None:
            return await handler(event, data)

        if not self._limiter.diizinkan(tg_user.id):
            sisa = self._limiter.sisa_detik(tg_user.id)
            logger.info("Rate limit untuk telegram_id=%s", tg_user.id)
            teks = f"⏳ Terlalu banyak permintaan. Coba lagi dalam {sisa} detik."
            if isinstance(event, Message):
                await event.answer(teks)
            elif isinstance(event, CallbackQuery):
                await event.answer(teks, show_alert=True)
            return None

        return await handler(event, data)
