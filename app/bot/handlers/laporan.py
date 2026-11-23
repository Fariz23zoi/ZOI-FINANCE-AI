"""Handler /excel — buat dan kirim laporan lima sheet."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message

from app.database.models import AuditAction, User
from app.database.repositories import audit_repo
from app.database.session import session_scope
from app.excel import generator
from app.services import report_service
from app.utils.dates import JAKARTA
from app.utils.logger import get_logger

router = Router(name="laporan")
logger = get_logger(__name__)


@router.message(Command("excel"))
async def cmd_excel(message: Message, user: User) -> None:
    """Hasilkan laporan Excel terbaru dan kirim lewat Telegram.

    Selalu dibuat ulang dari PostgreSQL saat perintah dijalankan; tidak ada
    file yang di-cache. PostgreSQL adalah sumber kebenaran, Excel hanya
    laporan yang dihasilkan darinya.
    """
    menunggu = await message.answer("⏳ Menyusun laporan Excel...")

    async with session_scope() as session:
        # Pemeriksaan izin ekspor ada di dalam report_service.kumpulkan.
        data = await report_service.kumpulkan(session, user=user)

    if not data.semua_transaksi:
        await menunggu.edit_text(
            "Belum ada transaksi untuk dilaporkan. Catat transaksi dulu, "
            "lalu jalankan /excel lagi."
        )
        return

    path = generator.simpan(data)

    from datetime import datetime

    stempel = datetime.now(JAKARTA).strftime("%d %B %Y %H:%M")

    await message.answer_document(
        FSInputFile(path, filename=path.name),
        caption=(
            f"📊 <b>Laporan ZOI FINANCE AI</b>\n"
            f"Dibuat: {stempel} WIB\n"
            f"{len(data.semua_transaksi)} transaksi · "
            f"5 sheet (Dashboard, Transaksi, Pemasukan, Pengeluaran, Rekap Bulanan)"
        ),
    )
    await menunggu.delete()

    async with session_scope() as session:
        await audit_repo.log(
            session,
            action=AuditAction.EXPORT_GENERATED,
            user_id=user.id,
            telegram_id=user.telegram_id,
            details={"jumlah_transaksi": len(data.semua_transaksi), "file": path.name},
        )

    logger.info("Laporan Excel dikirim ke user %s (%s baris)", user.id, len(data.semua_transaksi))

    # Laporan dibaca lengkap = saat yang tepat memeriksa kuota.
    from app.services.quota_service import periksa_dan_peringatkan

    await periksa_dan_peringatkan(message.bot, user)

    # File dihapus setelah terkirim. Disk Lunafy hanya 512 MB, dan laporan
    # bisa dibuat ulang kapan saja dari database — menyimpannya hanya memakan
    # kuota disk yang dibutuhkan untuk dependensi.
    try:
        path.unlink(missing_ok=True)
    except OSError:  # pragma: no cover
        pass
