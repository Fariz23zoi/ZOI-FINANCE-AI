"""Alur pencatatan transaksi: bahasa alami, konfirmasi, dan edit.

Ini inti aturan ZOI #8: transaksi hasil AI TIDAK PERNAH langsung tersimpan.
Setiap hasil parsing melewati tabel ``pending_transactions`` dan tombol
konfirmasi.

Pola alur (pending → ringkasan → Simpan/Edit/Batalkan, dengan edit per-field)
mengikuti pendekatan di RibasomR/finance-bot, dengan satu perbedaan penting:
di sana pending disimpan di FSM memori aiogram, di sini di PostgreSQL —
sehingga tombol konfirmasi tetap bekerja setelah proses restart.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.ai import router as ai_router
from app.ai.schema import ParsedTransaction
from app.bot import views
from app.bot.keyboards import confirm as kb
from app.bot.states import EditPending
from app.config import get_settings
from app.database.models import AuditAction, TransactionType, User
from app.database.repositories import (
    audit_repo,
    category_repo,
    pending_repo,
    transaction_repo,
)
from app.database.session import session_scope
from app.services import balance_service, permission_service
from app.services import transaction_service as ts
from app.utils.dates import local_today, parse_indonesian_date
from app.utils.logger import get_logger
from app.utils.money import parse_indonesian_amount
from app.utils.validators import validasi_jumlah

router = Router(name="catat")
logger = get_logger(__name__)

PESAN_TIDAK_TERBACA = (
    "🤔 Maaf, saya belum bisa membaca transaksi dari pesan itu.\n\n"
    "Pesan Anda tidak dibuang — Anda bisa:\n"
    "• menuliskannya ulang dengan jumlahnya, contoh: "
    "<code>beli bensin 30rb</code>\n"
    "• atau pakai /catat untuk mengisi langkah demi langkah"
)


async def _kategori_untuk_prompt(session) -> tuple[list, list]:
    """Nama kategori untuk dikirim ke prompt AI."""
    keluar = await category_repo.list_by_type(session, TransactionType.EXPENSE)
    masuk = await category_repo.list_by_type(session, TransactionType.INCOME)
    return [k.name for k in keluar], [k.name for k in masuk]


async def _tampilkan_konfirmasi(
    target, parsed: ParsedTransaction, pending_id: int, nama: str, edit: bool = False
) -> None:
    """Tampilkan layar konfirmasi, baik sebagai pesan baru maupun suntingan."""
    async with session_scope() as session:
        kategori = await category_repo.resolve(session, parsed.category, parsed.transaction_type)
        nama_kategori = kategori.name if kategori else "Lain-lain"

    teks = views.konfirmasi(parsed, nama, nama_kategori)
    papan = kb.konfirmasi(pending_id)

    if edit:
        await target.edit_text(teks, reply_markup=papan)
    else:
        await target.answer(teks, reply_markup=papan)


# ── Pesan bahasa alami ──────────────────────────────────────────


@router.message(F.text & ~F.text.startswith("/"))
async def teks_biasa(message: Message, user: User, state: FSMContext) -> None:
    """Tangani pesan biasa sebagai calon transaksi.

    Handler ini didaftarkan PALING AKHIR di main.py supaya tidak menelan
    pesan yang sedang ditunggu oleh alur FSM lain.
    """
    permission_service.boleh_tambah(user)

    if await state.get_state() is not None:
        # Ada alur lain yang sedang menunggu masukan; jangan diambil alih.
        return

    s = get_settings()

    async with session_scope() as session:
        # Sekalian bersihkan pending yang kedaluwarsa — dilakukan saat ada
        # aktivitas, bukan lewat cron.
        await pending_repo.expire_stale(session)
        kat_keluar, kat_masuk = await _kategori_untuk_prompt(session)

    menunggu = await message.answer("⏳ Membaca pesan Anda...")

    hasil, penolakan = await ai_router.parse_transaksi(
        message.text, kat_keluar, kat_masuk, hari_ini=local_today(s.tzinfo)
    )

    if penolakan:
        # Pesan ditolak oleh pemeriksaan data sensitif; tidak ada apa pun
        # yang dikirim ke provider AI.
        await menunggu.edit_text(f"🔒 {penolakan}")
        return

    if not hasil.berhasil or hasil.parsed is None:
        logger.info("Parsing gagal. Catatan: %s", "; ".join(hasil.catatan))
        async with session_scope() as session:
            await audit_repo.log(
                session,
                action=AuditAction.AI_PROVIDER_FAILURE,
                user_id=user.id,
                telegram_id=user.telegram_id,
                details={"catatan": hasil.catatan},
            )
        await menunggu.edit_text(PESAN_TIDAK_TERBACA)
        return

    async with session_scope() as session:
        pending = await pending_repo.create(
            session,
            telegram_user_id=user.telegram_id,
            parsed_data=hasil.parsed.to_json(),
            source_text=message.text[:4000],
            expire_minutes=s.pending_expire_minutes,
        )
        pending_id = pending.id

    await _tampilkan_konfirmasi(
        menunggu, hasil.parsed, pending_id, user.full_name, edit=True
    )


# ── Tombol konfirmasi ───────────────────────────────────────────


async def _ambil_pending(session, pending_id: int, user: User):
    """Ambil pending dan pastikan milik pengirim.

    Pesan galat untuk pending milik orang lain dibuat SAMA dengan pesan untuk
    pending yang tidak ada, supaya tidak membocorkan keberadaannya.
    """
    pending = await pending_repo.get(session, pending_id)
    if pending is None or pending.telegram_user_id != user.telegram_id:
        return None
    return pending


@router.callback_query(F.data.startswith("cf:save:"))
async def tombol_simpan(callback: CallbackQuery, user: User) -> None:
    """Simpan transaksi dari pending."""
    pending_id = int(callback.data.split(":")[2])

    async with session_scope() as session:
        hasil = await ts.simpan_dari_pending(session, user=user, pending_id=pending_id)

        if hasil.sudah_diproses:
            # Klik ganda atau pending kedaluwarsa. Tidak ada yang ditulis.
            await callback.answer("Transaksi ini sudah diproses.", show_alert=True)
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            return

        if hasil.duplikat_terdeteksi is not None:
            dup = hasil.duplikat_terdeteksi
            from app.utils.money import format_rupiah

            await callback.message.edit_text(
                "⚠️ <b>Sepertinya ini transaksi yang sama</b>\n\n"
                f"Beberapa menit lalu sudah tercatat transaksi #{dup.id} "
                f"sebesar {format_rupiah(dup.amount)} pada kategori yang sama.\n\n"
                "Tetap simpan sebagai transaksi terpisah?",
                reply_markup=kb.duplikat(pending_id),
            )
            await callback.answer()
            return

        trx = hasil.transaksi
        saldo = await balance_service.hitung_saldo(session)
        kategori = await category_repo.get_by_id(session, trx.category_id)
        nama_kategori = kategori.name if kategori else "-"
        # Objek dibaca SEBELUM keluar dari blok; teks disusun setelah commit.
        teks = views.tersimpan(trx, saldo, nama_kategori)

    # Dikirim hanya setelah commit berhasil: tidak pernah mengaku tersimpan
    # kalau belum (aturan ZOI #8 dan #12).
    await callback.message.edit_text(teks)
    await callback.answer("Tersimpan")


@router.callback_query(F.data.startswith("cf:dup:"))
async def tombol_simpan_duplikat(callback: CallbackQuery, user: User) -> None:
    """Simpan walau terdeteksi mirip transaksi sebelumnya.

    Pending sudah berstatus 'confirmed' dari percobaan pertama, jadi
    penyimpanan dilakukan lewat jalur langsung dengan data dari pending itu.
    """
    pending_id = int(callback.data.split(":")[2])

    async with session_scope() as session:
        pending = await _ambil_pending(session, pending_id, user)
        if pending is None:
            await callback.answer("Data transaksi tidak ditemukan.", show_alert=True)
            return

        if pending.transaction_id is not None:
            await callback.answer("Transaksi ini sudah tersimpan.", show_alert=True)
            return

        parsed = ParsedTransaction.from_json(pending.parsed_data)
        trx = await ts.simpan_langsung(
            session,
            user=user,
            transaction_type=parsed.transaction_type,
            amount=parsed.amount,
            kategori_nama=parsed.category,
            transaction_date=parsed.transaction_date,
            description=parsed.description,
            location=parsed.location,
            sumber=f"{parsed.sumber}+duplikat_disetujui",
        )
        await pending_repo.attach_transaction(session, pending_id, trx.id)

        saldo = await balance_service.hitung_saldo(session)
        kategori = await category_repo.get_by_id(session, trx.category_id)
        teks = views.tersimpan(trx, saldo, kategori.name if kategori else "-")

    await callback.message.edit_text(teks)
    await callback.answer("Tersimpan")


@router.callback_query(F.data.startswith("cf:cancel:"))
async def tombol_batal(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    pending_id = int(callback.data.split(":")[2])
    await state.clear()

    async with session_scope() as session:
        dibatalkan = await pending_repo.cancel(session, pending_id, user.telegram_id)

    if dibatalkan:
        await callback.message.edit_text("❌ Transaksi dibatalkan. Tidak ada yang disimpan.")
    else:
        await callback.message.edit_text("Transaksi ini sudah tidak bisa dibatalkan.")
    await callback.answer()


@router.callback_query(F.data.startswith("cf:edit:"))
async def tombol_edit(callback: CallbackQuery, user: User) -> None:
    pending_id = int(callback.data.split(":")[2])

    async with session_scope() as session:
        pending = await _ambil_pending(session, pending_id, user)

    if pending is None:
        await callback.answer("Data transaksi tidak ditemukan.", show_alert=True)
        return

    await callback.message.edit_text(
        "✏️ Bagian mana yang ingin diubah?", reply_markup=kb.pilih_field(pending_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ed:back:"))
async def tombol_kembali(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    pending_id = int(callback.data.split(":")[2])
    await state.clear()

    async with session_scope() as session:
        pending = await _ambil_pending(session, pending_id, user)

    if pending is None:
        await callback.answer("Data transaksi tidak ditemukan.", show_alert=True)
        return

    parsed = ParsedTransaction.from_json(pending.parsed_data)
    await _tampilkan_konfirmasi(
        callback.message, parsed, pending_id, user.full_name, edit=True
    )
    await callback.answer()


# ── Edit per field ──────────────────────────────────────────────

_PERMINTAAN = {
    "amount": (EditPending.menunggu_jumlah, "Kirim jumlah barunya.\nContoh: <code>25000</code> atau <code>25rb</code>"),
    "desc": (EditPending.menunggu_keterangan, "Kirim keterangan barunya."),
    "date": (EditPending.menunggu_tanggal, "Kirim tanggalnya.\nContoh: <code>kemarin</code>, <code>23/11/2026</code>, <code>3 hari lalu</code>"),
    "loc": (EditPending.menunggu_lokasi, "Kirim nama lokasinya."),
}


@router.callback_query(F.data.regexp(r"^ed:(amount|desc|date|loc):\d+$"))
async def minta_nilai_baru(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    _, field, pid = callback.data.split(":")
    pending_id = int(pid)

    async with session_scope() as session:
        if await _ambil_pending(session, pending_id, user) is None:
            await callback.answer("Data transaksi tidak ditemukan.", show_alert=True)
            return

    st, teks = _PERMINTAAN[field]
    await state.set_state(st)
    await state.update_data(pending_id=pending_id, pesan_id=callback.message.message_id)
    await callback.message.edit_text(f"✏️ {teks}")
    await callback.answer()


async def _terapkan(
    message: Message, user: User, state: FSMContext, field: str, nilai
) -> None:
    """Terapkan nilai baru ke pending lalu tampilkan ulang konfirmasi."""
    data = await state.get_data()
    pending_id = data.get("pending_id")
    await state.clear()

    if pending_id is None:  # pragma: no cover
        await message.answer("Sesi edit sudah berakhir. Silakan catat ulang.")
        return

    async with session_scope() as session:
        pending = await _ambil_pending(session, pending_id, user)
        if pending is None:
            await message.answer("Data transaksi tidak ditemukan. Silakan catat ulang.")
            return

        parsed = ParsedTransaction.from_json(pending.parsed_data)
        setattr(parsed, field, nilai)

        # Field yang baru saja diisi pengguna sendiri jelas tidak "kurang".
        parsed.kurang = [k for k in parsed.kurang if k != field]

        berhasil = await pending_repo.update_parsed_data(
            session, pending_id, user.telegram_id, parsed.to_json()
        )

    if not berhasil:
        await message.answer("Transaksi ini sudah diproses. Silakan catat ulang bila perlu.")
        return

    await _tampilkan_konfirmasi(message, parsed, pending_id, user.full_name)


@router.message(EditPending.menunggu_jumlah, F.text)
async def terima_jumlah(message: Message, user: User, state: FSMContext) -> None:
    jumlah: Optional[Decimal] = parse_indonesian_amount(message.text)

    if jumlah is None:
        valid, jumlah, galat = validasi_jumlah(message.text.strip())
        if not valid:
            await message.answer(f"❌ {galat}\n\nCoba lagi, contoh: <code>25000</code>")
            return

    valid, jumlah, galat = validasi_jumlah(jumlah, get_settings().max_transaction_amount)
    if not valid:
        await message.answer(f"❌ {galat}")
        return

    await _terapkan(message, user, state, "amount", jumlah)


@router.message(EditPending.menunggu_keterangan, F.text)
async def terima_keterangan(message: Message, user: User, state: FSMContext) -> None:
    from app.utils.validators import bersihkan_teks

    teks = bersihkan_teks(message.text, 500)
    if len(teks) < 2:
        await message.answer("❌ Keterangan terlalu pendek. Coba lagi.")
        return
    await _terapkan(message, user, state, "description", teks)


@router.message(EditPending.menunggu_lokasi, F.text)
async def terima_lokasi(message: Message, user: User, state: FSMContext) -> None:
    from app.utils.validators import bersihkan_teks

    teks = bersihkan_teks(message.text, 255)
    if len(teks) < 2:
        await message.answer("❌ Lokasi terlalu pendek. Coba lagi.")
        return
    await _terapkan(message, user, state, "location", teks)


@router.message(EditPending.menunggu_tanggal, F.text)
async def terima_tanggal(message: Message, user: User, state: FSMContext) -> None:
    tanggal = parse_indonesian_date(message.text, today=local_today())

    if tanggal is None:
        await message.answer(
            "❌ Tanggal tidak terbaca.\n\nContoh yang bisa dipakai: "
            "<code>kemarin</code>, <code>23/11/2026</code>, <code>3 hari lalu</code>"
        )
        return

    hari_ini = local_today()
    if tanggal > hari_ini:
        await message.answer(
            "❌ Tanggal tidak boleh di masa depan. Catatan keuangan hanya untuk "
            "transaksi yang sudah terjadi."
        )
        return

    await _terapkan(message, user, state, "transaction_date", tanggal)


@router.callback_query(F.data.startswith("ed:type:"))
async def minta_jenis(callback: CallbackQuery, user: User) -> None:
    pending_id = int(callback.data.split(":")[2])
    await callback.message.edit_text(
        "🔄 Pilih jenis transaksinya:", reply_markup=kb.pilih_jenis_baru(pending_id)
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^ty:\d+:(income|expense)$"))
async def terima_jenis(callback: CallbackQuery, user: User) -> None:
    _, pid, jenis = callback.data.split(":")
    pending_id = int(pid)
    baru = TransactionType(jenis)

    async with session_scope() as session:
        pending = await _ambil_pending(session, pending_id, user)
        if pending is None:
            await callback.answer("Data transaksi tidak ditemukan.", show_alert=True)
            return

        parsed = ParsedTransaction.from_json(pending.parsed_data)
        if parsed.transaction_type != baru:
            parsed.transaction_type = baru
            # Kategori lama milik jenis yang lain, jadi tidak lagi sah.
            parsed.category = None
        parsed.kurang = [k for k in parsed.kurang if k != "transaction_type"]

        await pending_repo.update_parsed_data(
            session, pending_id, user.telegram_id, parsed.to_json()
        )

    await _tampilkan_konfirmasi(
        callback.message, parsed, pending_id, user.full_name, edit=True
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ed:cat:"))
async def minta_kategori(callback: CallbackQuery, user: User) -> None:
    pending_id = int(callback.data.split(":")[2])

    async with session_scope() as session:
        pending = await _ambil_pending(session, pending_id, user)
        if pending is None:
            await callback.answer("Data transaksi tidak ditemukan.", show_alert=True)
            return
        parsed = ParsedTransaction.from_json(pending.parsed_data)
        kategori = await category_repo.list_by_type(session, parsed.transaction_type)

    await callback.message.edit_text(
        "🏷 Pilih kategorinya:", reply_markup=kb.pilih_kategori(pending_id, kategori)
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^ct:\d+:\d+$"))
async def terima_kategori(callback: CallbackQuery, user: User) -> None:
    _, pid, cid = callback.data.split(":")
    pending_id, category_id = int(pid), int(cid)

    async with session_scope() as session:
        pending = await _ambil_pending(session, pending_id, user)
        if pending is None:
            await callback.answer("Data transaksi tidak ditemukan.", show_alert=True)
            return

        kategori = await category_repo.get_by_id(session, category_id)
        parsed = ParsedTransaction.from_json(pending.parsed_data)

        # Jangan percaya callback_data: pastikan kategori memang sejenis.
        if kategori is None or kategori.transaction_type != parsed.transaction_type:
            await callback.answer("Kategori tidak sesuai jenis transaksi.", show_alert=True)
            return

        parsed.category = kategori.name
        parsed.kurang = [k for k in parsed.kurang if k != "category"]
        await pending_repo.update_parsed_data(
            session, pending_id, user.telegram_id, parsed.to_json()
        )

    await _tampilkan_konfirmasi(
        callback.message, parsed, pending_id, user.full_name, edit=True
    )
    await callback.answer()
