"""Alur /edit — mengubah transaksi yang SUDAH tersimpan.

Berbeda dari edit pada layar konfirmasi (``app/bot/handlers/catat.py``), yang
mengubah calon transaksi sebelum masuk buku kas. Di sini catatannya sudah
memengaruhi saldo bersama, jadi setiap perubahan:

* diperiksa haknya di ``permission_service.boleh_edit`` — admin boleh semua,
  member hanya miliknya sendiri;
* menulis ``audit_logs`` dengan nilai sebelum dan sesudah, dalam transaksi
  database yang sama;
* menampilkan saldo terbaru setelahnya, supaya pengaruh perubahannya terlihat
  langsung dan tidak perlu dipercaya begitu saja.

Jenis transaksi (pemasukan/pengeluaran) sengaja tidak bisa diubah di sini —
lihat alasannya di ``app/bot/keyboards/confirm.py:field_transaksi``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import confirm as kb
from app.bot.states import EditTransaksi
from app.config import get_settings
from app.database.models import Transaction, User
from app.database.repositories import category_repo, transaction_repo
from app.database.session import session_scope
from app.services import balance_service, permission_service, pin_service
from app.services import transaction_service as ts
from app.utils.dates import format_date_id, local_today, parse_indonesian_date
from app.utils.logger import get_logger
from app.utils.money import format_rupiah, parse_indonesian_amount
from app.utils.validators import bersihkan_teks, validasi_jumlah

router = Router(name="edit")
logger = get_logger(__name__)


def _ringkas(trx: Transaction) -> str:
    """Ringkasan transaksi untuk ditampilkan sebelum dan sesudah diubah."""
    jenis = "Pemasukan" if trx.transaction_type.value == "income" else "Pengeluaran"
    baris = [
        f"🔖 <b>Transaksi #{trx.id}</b>",
        "",
        f"Jenis: {jenis}",
        f"Jumlah: <b>{format_rupiah(trx.amount)}</b>",
        f"Kategori: {trx.category.name if trx.category else '-'}",
        f"Keterangan: {trx.description or '-'}",
        f"Lokasi: {trx.location or '-'}",
        f"Tanggal: {format_date_id(trx.transaction_date)}",
        f"Dicatat oleh: {trx.creator.full_name if trx.creator else '-'}",
    ]
    return "\n".join(baris)


@router.message(Command("edit"))
async def cmd_edit(
    message: Message, user: User, command: CommandObject, state: FSMContext
) -> None:
    """Mulai alur edit. Dengan argumen nomor, langsung ke transaksi itu."""
    permission_service.boleh_lihat(user)
    await state.clear()

    if command.args and command.args.strip().lstrip("#").isdigit():
        await _tampilkan_field(message, user, int(command.args.strip().lstrip("#")))
        return

    async with session_scope() as session:
        # Member hanya melihat catatannya sendiri di daftar pilihan: hak
        # aksesnya memang begitu, dan menampilkan yang tidak bisa dipilih
        # hanya berujung penolakan.
        terbaru = await transaction_repo.list_recent(
            session, limit=10, created_by=None if user.is_admin else user.id
        )

    if not terbaru:
        pesan = (
            "Belum ada transaksi yang bisa diubah."
            if user.is_admin
            else "Anda belum punya transaksi yang bisa diubah.\n\n"
            "<i>Member hanya bisa mengubah catatan yang dicatat sendiri. "
            "Minta administrator bila ada catatan anggota lain yang perlu "
            "diperbaiki.</i>"
        )
        await message.answer(pesan)
        return

    judul = "✏️ <b>Ubah transaksi</b>\n\nPilih transaksi yang akan diubah:"
    if not user.is_admin:
        judul += "\n\n<i>Hanya transaksi yang Anda catat sendiri.</i>"

    await message.answer(judul, reply_markup=kb.daftar_edit(terbaru))


async def _tampilkan_field(target, user: User, trx_id: int, edit: bool = False) -> None:
    """Tampilkan ringkasan transaksi beserta pilihan field yang bisa diubah."""
    async with session_scope() as session:
        trx = await transaction_repo.get_by_id(session, trx_id)

        if trx is None:
            teks = f"Transaksi #{trx_id} tidak ditemukan atau sudah dihapus."
            papan = None
        else:
            # Pemeriksaan hak akses sebelum apa pun ditampilkan, supaya member
            # tidak melihat isi transaksi yang tidak boleh ia ubah lewat
            # perintah /edit <nomor> langsung.
            try:
                permission_service.boleh_edit(user, trx)
            except permission_service.PermissionDenied as exc:
                teks, papan = f"🔒 {exc}", None
            else:
                teks = _ringkas(trx) + "\n\nBagian mana yang ingin diubah?"
                papan = kb.field_transaksi(trx.id)

    if edit and hasattr(target, "edit_text"):
        await target.edit_text(teks, reply_markup=papan)
    else:
        await target.answer(teks, reply_markup=papan)


@router.callback_query(F.data.startswith("et:pick:"))
async def pilih_transaksi(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    await state.clear()
    await _tampilkan_field(callback.message, user, int(callback.data.split(":")[2]), edit=True)
    await callback.answer()


@router.callback_query(F.data.startswith("et:cancel:"))
async def tutup(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Ditutup. Tidak ada yang diubah.")
    await callback.answer()


_PERMINTAAN = {
    "amount": (
        EditTransaksi.menunggu_jumlah,
        "Kirim jumlah barunya.\nContoh: <code>25000</code> atau <code>25rb</code>",
    ),
    "desc": (EditTransaksi.menunggu_keterangan, "Kirim keterangan barunya."),
    "date": (
        EditTransaksi.menunggu_tanggal,
        "Kirim tanggalnya.\nContoh: <code>kemarin</code>, <code>23/11/2026</code>, "
        "<code>3 hari lalu</code>",
    ),
    "loc": (EditTransaksi.menunggu_lokasi, "Kirim nama lokasinya."),
}


@router.callback_query(F.data.regexp(r"^et:f:(amount|desc|date|loc):\d+$"))
async def minta_nilai(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    _, _, field, pid = callback.data.split(":")
    trx_id = int(pid)

    # Diperiksa ulang di sini: callback_data bisa dikirim kapan saja, termasuk
    # dari pesan lama setelah hak akses berubah.
    async with session_scope() as session:
        trx = await transaction_repo.get_by_id(session, trx_id)
        if trx is None:
            await callback.answer("Transaksi tidak ditemukan.", show_alert=True)
            return
        try:
            permission_service.boleh_edit(user, trx)
        except permission_service.PermissionDenied as exc:
            await callback.answer(str(exc)[:190], show_alert=True)
            return

    st, teks = _PERMINTAAN[field]
    await state.set_state(st)
    await state.update_data(transaction_id=trx_id)
    await callback.message.edit_text(f"✏️ {teks}")
    await callback.answer()


async def _terapkan(message: Message, user: User, state: FSMContext, **nilai) -> None:
    """Terapkan perubahan lewat service, lalu tampilkan hasil dan saldo baru."""
    data = await state.get_data()
    trx_id = data.get("transaction_id")
    await state.clear()

    if trx_id is None:  # pragma: no cover
        await message.answer("Sesi edit sudah berakhir. Jalankan /edit lagi.")
        return

    async with session_scope() as session:
        # Service memeriksa hak akses dan menulis audit log dalam transaksi
        # database yang sama; galatnya ditangani middleware.
        trx = await ts.ubah(session, user=user, transaction_id=trx_id, **nilai)
        saldo = await balance_service.hitung_saldo(session)
        ringkasan = _ringkas(trx)
        teks_saldo = format_rupiah(saldo.saldo_sekarang)

    # Hanya setelah commit berhasil.
    await message.answer(
        f"✅ <b>Transaksi diperbarui</b>\n\n{ringkasan}\n\n"
        f"💳 Saldo sekarang: <b>{teks_saldo}</b>\n\n"
        "<i>Perubahan tercatat di log audit.</i>"
    )
    await pin_service.segarkan(message.bot)


@router.message(EditTransaksi.menunggu_jumlah, F.text)
async def terima_jumlah(message: Message, user: User, state: FSMContext) -> None:
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

    await _terapkan(message, user, state, amount=jumlah)


@router.message(EditTransaksi.menunggu_keterangan, F.text)
async def terima_keterangan(message: Message, user: User, state: FSMContext) -> None:
    teks = bersihkan_teks(message.text, 500)
    if len(teks) < 2:
        await message.answer("❌ Keterangan terlalu pendek. Coba lagi.")
        return
    await _terapkan(message, user, state, description=teks)


@router.message(EditTransaksi.menunggu_lokasi, F.text)
async def terima_lokasi(message: Message, user: User, state: FSMContext) -> None:
    teks = bersihkan_teks(message.text, 255)
    if len(teks) < 2:
        await message.answer("❌ Lokasi terlalu pendek. Coba lagi.")
        return
    await _terapkan(message, user, state, location=teks)


@router.message(EditTransaksi.menunggu_tanggal, F.text)
async def terima_tanggal(message: Message, user: User, state: FSMContext) -> None:
    tanggal: date | None = parse_indonesian_date(message.text, today=local_today())

    if tanggal is None:
        await message.answer(
            "❌ Tanggal tidak terbaca.\n\nContoh yang bisa dipakai: "
            "<code>kemarin</code>, <code>23/11/2026</code>, <code>3 hari lalu</code>"
        )
        return

    if tanggal > local_today():
        await message.answer(
            "❌ Tanggal tidak boleh di masa depan. Catatan keuangan hanya untuk "
            "transaksi yang sudah terjadi."
        )
        return

    await _terapkan(message, user, state, transaction_date=tanggal)


@router.callback_query(F.data.regexp(r"^et:f:cat:\d+$"))
async def minta_kategori(callback: CallbackQuery, user: User) -> None:
    trx_id = int(callback.data.split(":")[3])

    async with session_scope() as session:
        trx = await transaction_repo.get_by_id(session, trx_id)
        if trx is None:
            await callback.answer("Transaksi tidak ditemukan.", show_alert=True)
            return
        try:
            permission_service.boleh_edit(user, trx)
        except permission_service.PermissionDenied as exc:
            await callback.answer(str(exc)[:190], show_alert=True)
            return

        # Hanya kategori yang sejenis — kategori pemasukan tidak boleh dipasang
        # pada pengeluaran.
        kategori = await category_repo.list_by_type(session, trx.transaction_type)

    await callback.message.edit_text(
        "🏷 Pilih kategori barunya:", reply_markup=kb.kategori_transaksi(trx_id, kategori)
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^et:c:\d+:\d+$"))
async def terima_kategori(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    _, _, tid, cid = callback.data.split(":")
    trx_id, category_id = int(tid), int(cid)

    async with session_scope() as session:
        trx = await transaction_repo.get_by_id(session, trx_id)
        kategori = await category_repo.get_by_id(session, category_id)

        if trx is None or kategori is None:
            await callback.answer("Transaksi atau kategori tidak ditemukan.", show_alert=True)
            return

        # Jangan percaya callback_data: pastikan kategorinya sejenis.
        if kategori.transaction_type != trx.transaction_type:
            await callback.answer("Kategori tidak sesuai jenis transaksi.", show_alert=True)
            return

        nama_kategori = kategori.name

    await state.update_data(transaction_id=trx_id)
    await _terapkan(callback.message, user, state, kategori_nama=nama_kategori)
    await callback.answer("Diperbarui")
