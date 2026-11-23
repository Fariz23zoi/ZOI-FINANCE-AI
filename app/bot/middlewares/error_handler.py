"""Middleware penanganan galat.

Pola diadaptasi dari RibasomR/finance-bot (MIT, Copyright (c) 2025-2026
RibasomR): setiap exception disanitasi sebelum masuk log. Lihat
docs/THIRD_PARTY_NOTICES.md.

Aturan penting: pengguna tidak boleh pernah menerima pesan yang mengaku
sesuatu tersimpan ketika sebenarnya gagal (aturan ZOI #8 dan #12). Karena itu
pesan galat di bawah selalu menyatakan bahwa data TIDAK tersimpan.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message, TelegramObject

from sqlalchemy.exc import DBAPIError

from app.services.permission_service import PermissionDenied
from app.utils.logger import get_logger
from app.utils.sanitizer import sanitize_exception

logger = get_logger(__name__)

PESAN_GALAT = (
    "⚠️ Terjadi kesalahan dan permintaan Anda TIDAK tersimpan.\n\n"
    "Silakan coba lagi. Bila terus gagal, hubungi administrator."
)

PESAN_READ_ONLY = (
    "⚠️ Database sedang <b>read-only</b>, jadi transaksi Anda "
    "<b>TIDAK tersimpan</b>.\n\n"
    "Ini terjadi bila kuota Supabase paket Free terlampaui, atau proyeknya "
    "sedang dijeda. Catatan lama tetap utuh dan masih bisa dibaca.\n\n"
    "Hubungi administrator untuk memeriksa dashboard Supabase."
)


class ErrorHandlerMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)

        except PermissionDenied as exc:
            # Bukan bug, dan aman ditampilkan apa adanya: seluruh pesan
            # PermissionDenied berasal dari string literal di
            # app/services/permission_service.py yang ditulis untuk dibaca
            # pengguna. Tidak ada nilai dari luar yang masuk ke dalamnya.
            await _balas(event, f"🔒 {exc}")
            return None

        except DBAPIError as exc:
            # Supabase paket Free mengubah proyek menjadi read-only begitu
            # ukuran database melewati 500 MB, dan proyek yang dijeda juga
            # menolak penulisan. Keduanya muncul sebagai galat database biasa,
            # jadi tanpa pemeriksaan ini pengguna hanya melihat "terjadi
            # kesalahan" dan tidak tahu bahwa penyebabnya bisa ditindaklanjuti.
            pesan = str(getattr(exc, "orig", exc)).lower()
            if "read-only" in pesan or "read only" in pesan:
                logger.error("Database read-only: penulisan ditolak.")
                await _balas(event, PESAN_READ_ONLY)
            else:
                logger.exception("Galat database: %s", sanitize_exception(exc))
                await _balas(event, PESAN_GALAT)
            return None

        except TelegramAPIError as exc:
            # Galat dari sisi Telegram — biasanya pesan sudah terhapus atau
            # tidak berubah. Tidak ada gunanya mengirim pesan lagi.
            logger.warning("Galat API Telegram: %s", sanitize_exception(exc))
            return None

        except Exception as exc:
            logger.exception("Galat tidak tertangani: %s", sanitize_exception(exc))
            await _balas(event, PESAN_GALAT)
            return None


async def _balas(event: TelegramObject, teks: str) -> None:
    try:
        if isinstance(event, Message):
            await event.answer(teks)
        elif isinstance(event, CallbackQuery):
            await event.answer(teks[:200], show_alert=True)
            if event.message:
                await event.message.answer(teks)
    except Exception:  # pragma: no cover
        pass
