"""Alur /catat terpandu — entri manual langkah demi langkah.

Ini jalan keluar yang dijanjikan aturan ZOI bagian 8: ketika kedua provider AI
gagal, pengguna tetap bisa mencatat transaksi. Alur ini tidak memakai AI sama
sekali, jadi selalu tersedia.

Berbeda dari jalur AI, di sini pengguna sendiri yang mengisi setiap field,
sehingga tidak ada yang perlu "dikonfirmasi ulang" — ringkasan tetap
ditampilkan sebelum penyimpanan agar pengguna bisa membatalkan.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot import views
from app.config import get_settings
from app.database.models import TransactionType, User
from app.database.repositories import category_repo
from app.database.session import session_scope
from app.services import balance_service, permission_service, pin_service
from app.services import transaction_service as ts
from app.utils.dates import local_today
from app.utils.logger import get_logger
from app.utils.money import format_rupiah, parse_indonesian_amount
from app.utils.validators import bersihkan_teks, validasi_jumlah

router = Router(name="manual")
logger = get_logger(__name__)

from app.bot.states import CatatManual  # noqa: E402


@router.message(Command("catat"))
async def mulai(message: Message, user: User, state: FSMContext) -> None:
    permission_service.boleh_tambah(user)
    await state.clear()

    b = InlineKeyboardBuilder()
    b.button(text="💸 Pengeluaran", callback_data="mn:type:expense")
    b.button(text="💰 Pemasukan", callback_data="mn:type:income")
    b.button(text="❌ Batal", callback_data="mn:cancel")
    b.adjust(2, 1)

    await state.set_state(CatatManual.pilih_jenis)
    await message.answer(
        "📝 <b>Catat transaksi</b>\n\nJenis transaksinya apa?", reply_markup=b.as_markup()
    )


@router.callback_query(F.data == "mn:cancel")
async def batal(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("❌ Dibatalkan. Tidak ada yang disimpan.")
    await callback.answer()


@router.callback_query(CatatManual.pilih_jenis, F.data.startswith("mn:type:"))
async def pilih_jenis(callback: CallbackQuery, state: FSMContext) -> None:
    jenis = callback.data.split(":")[2]
    await state.update_data(jenis=jenis)
    await state.set_state(CatatManual.isi_jumlah)

    await callback.message.edit_text(
        f"💵 Berapa jumlahnya?\n\n"
        f"Jenis: <b>{'Pemasukan' if jenis == 'income' else 'Pengeluaran'}</b>\n\n"
        "Contoh: <code>25000</code>, <code>25rb</code>, <code>1,5 juta</code>"
    )
    await callback.answer()


@router.message(CatatManual.isi_jumlah, F.text)
async def isi_jumlah(message: Message, state: FSMContext) -> None:
    jumlah = parse_indonesian_amount(message.text)

    if jumlah is None:
        await message.answer(
            "❌ Jumlah tidak terbaca. Tulis angkanya saja, contoh: <code>25000</code>"
        )
        return

    valid, jumlah, galat = validasi_jumlah(jumlah, get_settings().max_transaction_amount)
    if not valid:
        await message.answer(f"❌ {galat}")
        return

    data = await state.get_data()
    jenis = TransactionType(data["jenis"])
    await state.update_data(jumlah=str(jumlah))

    async with session_scope() as session:
        kategori = await category_repo.list_by_type(session, jenis)

    b = InlineKeyboardBuilder()
    for k in kategori:
        b.button(text=k.name, callback_data=f"mn:cat:{k.id}")
    b.button(text="❌ Batal", callback_data="mn:cancel")
    b.adjust(2)

    await state.set_state(CatatManual.pilih_kategori)
    await message.answer(
        f"Jumlah: <b>{format_rupiah(jumlah)}</b>\n\n🏷 Pilih kategorinya:",
        reply_markup=b.as_markup(),
    )


@router.callback_query(CatatManual.pilih_kategori, F.data.startswith("mn:cat:"))
async def pilih_kategori(callback: CallbackQuery, state: FSMContext) -> None:
    category_id = int(callback.data.split(":")[2])

    async with session_scope() as session:
        kategori = await category_repo.get_by_id(session, category_id)
        nama = kategori.name if kategori else None

    if nama is None:
        await callback.answer("Kategori tidak ditemukan.", show_alert=True)
        return

    await state.update_data(kategori=nama)
    await state.set_state(CatatManual.isi_keterangan)

    b = InlineKeyboardBuilder()
    b.button(text="➡️ Lewati", callback_data="mn:skip")
    b.button(text="❌ Batal", callback_data="mn:cancel")
    b.adjust(2)

    await callback.message.edit_text(
        f"🏷 Kategori: <b>{nama}</b>\n\n📝 Tulis keterangannya, atau lewati.",
        reply_markup=b.as_markup(),
    )
    await callback.answer()


async def _simpan(target, user: User, state: FSMContext, keterangan: str | None) -> None:
    """Simpan hasil alur manual."""
    data = await state.get_data()
    await state.clear()

    from decimal import Decimal

    async with session_scope() as session:
        trx = await ts.simpan_langsung(
            session,
            user=user,
            transaction_type=TransactionType(data["jenis"]),
            amount=Decimal(data["jumlah"]),
            kategori_nama=data.get("kategori"),
            transaction_date=local_today(),
            description=keterangan,
            sumber="manual",
        )
        saldo = await balance_service.hitung_saldo(session)
        kategori = await category_repo.get_by_id(session, trx.category_id)
        teks = views.tersimpan(trx, saldo, kategori.name if kategori else "-")

    # Hanya setelah commit berhasil.
    if hasattr(target, "edit_text"):
        await target.edit_text(teks)
    else:
        await target.answer(teks)

    await pin_service.segarkan(target.bot)


@router.callback_query(CatatManual.isi_keterangan, F.data == "mn:skip")
async def lewati_keterangan(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    await _simpan(callback.message, user, state, None)
    await callback.answer()


@router.message(CatatManual.isi_keterangan, F.text)
async def isi_keterangan(message: Message, user: User, state: FSMContext) -> None:
    teks = bersihkan_teks(message.text, 500)
    await _simpan(message, user, state, teks or None)
