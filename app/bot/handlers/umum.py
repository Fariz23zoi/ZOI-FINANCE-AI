"""Handler perintah umum: /start, /bantuan, /saldo, /hariini, /bulanan."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from app.bot import views
from app.database.models import User
from app.database.repositories import transaction_repo
from app.database.session import session_scope
from app.services import balance_service, permission_service
from app.utils.dates import local_today, month_bounds
from app.utils.logger import get_logger

router = Router(name="umum")
logger = get_logger(__name__)


@router.message(CommandStart())
async def cmd_start(message: Message, user: User) -> None:
    """Sambutan plus bantuan.

    Pengguna yang sampai ke sini sudah lolos middleware otorisasi, jadi
    sambutannya boleh langsung menyapa dengan nama.
    """
    sapaan = (
        f"Selamat datang, <b>{user.full_name}</b>.\n"
        f"Peran Anda: <b>{user.role.value}</b>\n\n"
    )
    await message.answer(sapaan + views.bantuan(user.is_admin))


@router.message(Command("bantuan", "help"))
async def cmd_bantuan(message: Message, user: User) -> None:
    await message.answer(views.bantuan(user.is_admin))


@router.message(Command("saldo"))
async def cmd_saldo(message: Message, user: User) -> None:
    permission_service.boleh_lihat(user)

    async with session_scope() as session:
        saldo = await balance_service.hitung_saldo(session)
        bulan = await balance_service.rekap_bulan_ini(session)

    await message.answer(views.saldo_bersama(saldo, bulan))

    # Pemeriksaan kuota dipasang di sini dan di /excel, bukan lewat penjadwal
    # terpisah: ini saat pengguna memang sedang melihat angka, jadi peringatan
    # kuota muncul tepat ketika relevan.
    from app.services.quota_service import periksa_dan_peringatkan

    await periksa_dan_peringatkan(message.bot, user)


@router.message(Command("hariini"))
async def cmd_hariini(message: Message, user: User) -> None:
    permission_service.boleh_lihat(user)
    hari = local_today()

    async with session_scope() as session:
        transaksi = await transaction_repo.list_by_date_range(session, hari, hari)
        rekap = await balance_service.rekap_periode(session, hari, hari)

    from app.utils.dates import format_date_id

    await message.answer(
        views.daftar_transaksi(f"Transaksi {format_date_id(hari)}", transaksi, rekap)
    )


@router.message(Command("bulanan"))
async def cmd_bulanan(message: Message, user: User) -> None:
    permission_service.boleh_lihat(user)

    async with session_scope() as session:
        baris = await balance_service.rekap_bulanan(session)

    await message.answer(views.rekap_bulanan(baris))


@router.message(Command("bulanini"))
async def cmd_bulan_ini(message: Message, user: User) -> None:
    """Daftar transaksi bulan ini. Bukan perintah wajib, tapi sering dicari."""
    permission_service.boleh_lihat(user)
    awal, akhir = month_bounds(local_today())

    async with session_scope() as session:
        transaksi = await transaction_repo.list_by_date_range(session, awal, akhir)
        rekap = await balance_service.rekap_periode(session, awal, akhir)

    from app.utils.dates import format_month_id

    await message.answer(
        views.daftar_transaksi(f"Transaksi {format_month_id(awal)}", transaksi, rekap)
    )
