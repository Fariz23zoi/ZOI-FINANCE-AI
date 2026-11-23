"""Middleware otorisasi.

Dijalankan sebelum SEMUA handler. Pengguna yang tidak ada di tabel ``users``
atau yang tidak aktif tidak pernah mencapai handler mana pun, dan
percobaannya dicatat di ``audit_logs``.

Otorisasi memakai Telegram ID numerik, bukan username — username bisa diganti
kapan saja oleh pemiliknya.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, User as TgUser

from app.database.models import AuditAction
from app.database.repositories import audit_repo, user_repo
from app.database.session import session_scope
from app.utils.logger import get_logger

logger = get_logger(__name__)

PESAN_TOLAK = (
    "🔒 Anda belum terdaftar di ZOI FINANCE AI.\n\n"
    "Bot ini hanya untuk anggota yang terdaftar. Bila Anda seharusnya punya "
    "akses, minta administrator menambahkan Telegram ID Anda."
)

PESAN_NONAKTIF = (
    "🔒 Akun Anda tidak aktif.\n\n"
    "Hubungi administrator untuk mengaktifkannya kembali."
)


class AuthMiddleware(BaseMiddleware):
    """Izinkan hanya anggota terdaftar dan aktif."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        tg_user: TgUser | None = data.get("event_from_user")

        if tg_user is None or tg_user.is_bot:
            return None

        async with session_scope() as session:
            user = await user_repo.get_by_telegram_id(session, tg_user.id)

            if user is None:
                # Dicatat beserta Telegram ID-nya meski orang ini tidak ada di
                # tabel users — satu-satunya cara tahu ada yang mencoba masuk.
                await audit_repo.log(
                    session,
                    action=AuditAction.UNAUTHORIZED_ACCESS,
                    telegram_id=tg_user.id,
                    details={
                        "username": tg_user.username,
                        "first_name": tg_user.first_name,
                        "alasan": "tidak_terdaftar",
                    },
                )
                logger.warning("Akses ditolak: telegram_id=%s (tidak terdaftar)", tg_user.id)
                await _balas(event, PESAN_TOLAK)
                return None

            if not user.is_active:
                await audit_repo.log(
                    session,
                    action=AuditAction.UNAUTHORIZED_ACCESS,
                    user_id=user.id,
                    telegram_id=tg_user.id,
                    details={"alasan": "tidak_aktif"},
                )
                logger.warning("Akses ditolak: telegram_id=%s (tidak aktif)", tg_user.id)
                await _balas(event, PESAN_NONAKTIF)
                return None

            # Segarkan nama tampil bila pengguna mengubahnya di Telegram.
            # Hanya informatif; tidak memengaruhi hak akses.
            nama = " ".join(filter(None, [tg_user.first_name, tg_user.last_name])).strip()
            await user_repo.touch_profile(session, user, nama or user.full_name, tg_user.username)

            # Lepaskan dari session supaya objek tetap bisa dibaca handler
            # setelah session ditutup (expire_on_commit=False sudah diatur,
            # tetapi melepas eksplisit membuat niatnya jelas).
            session.expunge(user)

        data["user"] = user
        data["is_admin"] = user.is_admin
        return await handler(event, data)


async def _balas(event: TelegramObject, teks: str) -> None:
    """Balas ke pengirim, apa pun jenis event-nya."""
    try:
        if isinstance(event, Message):
            await event.answer(teks)
        elif isinstance(event, CallbackQuery):
            await event.answer(teks, show_alert=True)
    except Exception as exc:  # pragma: no cover - kegagalan jaringan Telegram
        from app.utils.sanitizer import sanitize_exception

        logger.warning("Gagal mengirim penolakan: %s", sanitize_exception(exc))
