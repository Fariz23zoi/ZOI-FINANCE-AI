"""Bootstrap ZOI FINANCE AI.

Urutan startup disusun supaya kegagalan terdeteksi SEBELUM bot mulai menerima
pesan. Bot yang berjalan tanpa database akan menerima transaksi dan tidak bisa
menyimpannya, dan aturan ZOI melarang mengaku transaksi tersimpan kalau tidak.

Long polling dipakai, bukan webhook. Di Lunafy, port dialokasikan atas
permintaan dengan biaya per bulan dan web server tidak diizinkan, jadi webhook
bukan pilihan — dan untuk bot 2–3 pengguna, long polling memang sudah cukup.
"""

from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from app.config import get_settings
from app.bot.handlers import ROUTERS
from app.bot.middlewares import (
    AuthMiddleware,
    ErrorHandlerMiddleware,
    RateLimitMiddleware,
)
from app.database.session import check_connection, dispose_engine, keepalive_ping
from app.utils.logger import get_logger, setup_logging

logger = get_logger(__name__)

PERINTAH = [
    BotCommand(command="catat", description="Catat transaksi langkah demi langkah"),
    BotCommand(command="saldo", description="Saldo bersama"),
    BotCommand(command="hariini", description="Transaksi hari ini"),
    BotCommand(command="bulanan", description="Rekap bulanan"),
    BotCommand(command="edit", description="Ubah transaksi"),
    BotCommand(command="anggota", description="Daftar anggota"),
    BotCommand(command="excel", description="Laporan Excel"),
    BotCommand(command="hapus", description="Hapus transaksi (admin)"),
    BotCommand(command="bantuan", description="Bantuan"),
]


def buat_dispatcher() -> Dispatcher:
    """Susun Dispatcher beserta middleware dan router.

    Urutan middleware penting:

    1. ``ErrorHandlerMiddleware`` terluar — menangkap apa pun dari lapisan
       dalam, termasuk dari middleware auth.
    2. ``AuthMiddleware`` — pengguna tak dikenal tidak pernah mencapai lapisan
       berikutnya, dan percobaannya tercatat.
    3. ``RateLimitMiddleware`` terdalam — hanya membatasi pengguna yang sudah
       terotorisasi, sehingga orang luar tidak bisa menghabiskan kuotanya.
    """
    s = get_settings()
    dp = Dispatcher()

    for lapisan in (dp.message, dp.callback_query):
        lapisan.middleware(ErrorHandlerMiddleware())
        lapisan.middleware(AuthMiddleware())
        lapisan.middleware(
            RateLimitMiddleware(s.rate_limit_requests, s.rate_limit_window_seconds)
        )

    for r in ROUTERS:
        dp.include_router(r)

    return dp


async def _loop_keepalive(jeda_jam: int) -> None:
    """Sentuh database secara berkala agar proyek Supabase tidak dijeda.

    Supabase menjeda proyek paket Free yang aktivitas databasenya rendah
    selama 7 hari; menurut dokumentasinya, beberapa query pengguna per hari
    sudah cukup untuk mencegahnya. Bot yang dipakai sehari-hari otomatis
    memenuhi itu — tugas ini melindungi kasus ketika tidak ada yang mencatat
    apa pun selama seminggu, misalnya saat semua anggota sedang pergi.

    Satu query ringan per beberapa jam jauh lebih murah daripada memulihkan
    proyek yang dijeda, dan jauh lebih murah daripada kehilangannya setelah
    jendela 90 hari.
    """
    jeda = jeda_jam * 3600
    while True:
        await asyncio.sleep(jeda)
        try:
            await keepalive_ping()
        except Exception as exc:  # pragma: no cover
            from app.utils.sanitizer import sanitize_exception

            logger.warning("Keepalive gagal: %s", sanitize_exception(exc))


async def main() -> None:
    """Jalankan bot."""
    s = get_settings()
    setup_logging(s.log_level)

    logger.info("ZOI FINANCE AI — Smart Finance. Simple Control.")
    logger.info("Zona waktu: %s · Mata uang: %s", s.timezone, s.currency)
    logger.info(
        "AI: OpenRouter=%s (%d model gratis) · Gemini=%s (%d model)",
        "aktif" if s.openrouter_api_key else "tidak diatur",
        len(s.openrouter_model_list),
        "aktif" if s.gemini_api_key else "tidak diatur",
        len(s.gemini_model_list),
    )

    # Database diperiksa SEBELUM polling dimulai.
    if not await check_connection():
        logger.critical(
            "Tidak bisa terhubung ke database. Bot tidak dijalankan.\n"
            "Periksa DATABASE_URL, dan pastikan migrasi sudah dijalankan "
            "(alembic upgrade head)."
        )
        raise SystemExit(1)
    logger.info("Koneksi database OK.")

    bot = Bot(
        token=s.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = buat_dispatcher()

    try:
        saya = await bot.get_me()
        logger.info("Terhubung sebagai @%s (id=%s)", saya.username, saya.id)

        await bot.set_my_commands(PERINTAH)

        # drop_pending_updates: setelah restart, update yang menumpuk saat bot
        # mati dibuang. Memprosesnya bisa membuat tombol konfirmasi lama
        # ditekan ulang; perlindungan klaim atomik tetap menjaga dari transaksi
        # ganda, tapi membuang update yang basi lebih bersih.
        await bot.delete_webhook(drop_pending_updates=True)

        tugas_keepalive = None
        if s.keepalive_hours > 0 and not s.is_sqlite:
            tugas_keepalive = asyncio.create_task(_loop_keepalive(s.keepalive_hours))
            logger.info("Keepalive database tiap %s jam.", s.keepalive_hours)

        logger.info("Mulai long polling.")
        try:
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        finally:
            if tugas_keepalive is not None:
                tugas_keepalive.cancel()

    finally:
        logger.info("Menghentikan bot...")
        await bot.session.close()
        await dispose_engine()
        logger.info("Selesai.")
