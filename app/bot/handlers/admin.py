"""Handler khusus administrator: /hapus, /anggota, /saldoawal.

Filter ``IsAdmin`` di sini hanya untuk UX. Penegakan hak akses yang
sesungguhnya ada di dalam service (``permission_service``) dan tetap berjalan
walau filter dilewati lewat jalur lain.
"""

from __future__ import annotations

from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot import views
from app.bot.keyboards import confirm as kb
from app.database.models import AuditAction, User
from app.database.repositories import audit_repo, settings_repo, transaction_repo
from app.database.session import session_scope
from app.services import balance_service, member_service, permission_service
from app.services import transaction_service as ts
from app.utils.logger import get_logger
from app.utils.money import format_rupiah, parse_indonesian_amount
from app.utils.validators import validasi_jumlah

router = Router(name="admin")
logger = get_logger(__name__)


# ── /hapus ──────────────────────────────────────────────────────


@router.message(Command("hapus"))
async def cmd_hapus(message: Message, user: User, command: CommandObject) -> None:
    """Hapus transaksi. Hanya admin (aturan ZOI #9).

    Dengan argumen nomor: langsung menampilkan konfirmasi untuk transaksi itu.
    Tanpa argumen: menampilkan daftar transaksi terbaru untuk dipilih.
    """
    # Pemeriksaan sesungguhnya; filter IsAdmin tidak dipakai di sini supaya
    # member mendapat penjelasan, bukan diam saja.
    permission_service.boleh_hapus(user)

    if command.args and command.args.strip().lstrip("#").isdigit():
        trx_id = int(command.args.strip().lstrip("#"))
        await _tampilkan_konfirmasi_hapus(message, trx_id)
        return

    async with session_scope() as session:
        terbaru = await transaction_repo.list_recent(session, limit=10)

    if not terbaru:
        await message.answer("Belum ada transaksi yang bisa dihapus.")
        return

    await message.answer(
        "🗑 <b>Hapus transaksi</b>\n\nPilih transaksi yang akan dihapus:",
        reply_markup=kb.daftar_hapus(terbaru),
    )


async def _tampilkan_konfirmasi_hapus(target, trx_id: int) -> None:
    async with session_scope() as session:
        trx = await transaction_repo.get_by_id(session, trx_id)
        if trx is None:
            teks = f"Transaksi #{trx_id} tidak ditemukan atau sudah dihapus."
            papan = None
        else:
            from app.utils.dates import format_date_id

            jenis = "Pemasukan" if trx.transaction_type.value == "income" else "Pengeluaran"
            teks = "\n".join([
                "🗑 <b>Hapus transaksi ini?</b>",
                "",
                f"Nomor: #{trx.id}",
                f"Jenis: {jenis}",
                f"Jumlah: <b>{format_rupiah(trx.amount)}</b>",
                f"Kategori: {trx.category.name if trx.category else '-'}",
                f"Keterangan: {trx.description or '-'}",
                f"Tanggal: {format_date_id(trx.transaction_date)}",
                f"Dicatat oleh: {trx.creator.full_name if trx.creator else '-'}",
                "",
                "<i>Data tetap tersimpan di database sebagai catatan "
                "(dihapus dari perhitungan saldo saja), dan tercatat di log audit.</i>",
            ])
            papan = kb.hapus_konfirmasi(trx.id)

    if hasattr(target, "edit_text"):
        await target.edit_text(teks, reply_markup=papan)
    else:
        await target.answer(teks, reply_markup=papan)


@router.callback_query(F.data.startswith("dl:pick:"))
async def pilih_hapus(callback: CallbackQuery, user: User) -> None:
    permission_service.boleh_hapus(user)
    trx_id = int(callback.data.split(":")[2])
    await _tampilkan_konfirmasi_hapus(callback.message, trx_id)
    await callback.answer()


@router.callback_query(F.data == "dl:no:0")
async def batal_hapus(callback: CallbackQuery) -> None:
    await callback.message.edit_text("Penghapusan dibatalkan.")
    await callback.answer()


@router.callback_query(F.data.startswith("dl:ok:"))
async def konfirmasi_hapus(callback: CallbackQuery, user: User) -> None:
    trx_id = int(callback.data.split(":")[2])

    async with session_scope() as session:
        # Pemeriksaan izin ada di dalam service.
        trx = await ts.hapus(session, user=user, transaction_id=trx_id)
        saldo = await balance_service.hitung_saldo(session)
        jumlah = trx.amount

    await callback.message.edit_text(
        f"✅ Transaksi #{trx_id} ({format_rupiah(jumlah)}) dihapus.\n\n"
        f"💳 Saldo sekarang: <b>{format_rupiah(saldo.saldo_sekarang)}</b>\n\n"
        "<i>Barisnya tetap ada di database dan tercatat di log audit.</i>"
    )
    await callback.answer("Dihapus")


# ── /anggota ────────────────────────────────────────────────────


@router.message(Command("anggota"))
async def cmd_anggota(message: Message, user: User, command: CommandObject) -> None:
    """Lihat anggota; admin bisa menambah lewat argumen."""
    args = (command.args or "").strip()

    if not args:
        async with session_scope() as session:
            daftar = await member_service.daftar(session, user=user)
        await message.answer(views.daftar_anggota(daftar, user.is_admin))
        return

    bagian = args.split(maxsplit=2)
    aksi = bagian[0].lower()

    if aksi in ("tambah", "add"):
        if len(bagian) < 3:
            await message.answer(
                "Format: <code>/anggota tambah &lt;telegram_id&gt; &lt;nama&gt;</code>\n\n"
                "Contoh: <code>/anggota tambah 123456789 Budi</code>\n\n"
                "Anggota bisa melihat Telegram ID-nya dengan mengirim pesan "
                "ke @userinfobot."
            )
            return

        async with session_scope() as session:
            baru = await member_service.tambah(
                session, user=user, telegram_id_mentah=bagian[1], nama=bagian[2]
            )
            nama, tid = baru.full_name, baru.telegram_id

        await message.answer(
            f"✅ <b>{nama}</b> ditambahkan sebagai anggota.\n"
            f"Telegram ID: <code>{tid}</code>\n\n"
            "Minta yang bersangkutan mengirim /start ke bot ini."
        )
        return

    await message.answer(
        "Perintah tidak dikenali.\n\n"
        "<code>/anggota</code> — lihat daftar\n"
        "<code>/anggota tambah &lt;telegram_id&gt; &lt;nama&gt;</code> — tambah anggota"
    )


# ── /saldoawal ──────────────────────────────────────────────────


@router.message(Command("saldoawal"))
async def cmd_saldo_awal(message: Message, user: User, command: CommandObject) -> None:
    """Atur saldo awal buku kas. Hanya admin.

    Aturan ZOI bagian 12: saldo awal harus dikonfigurasi manual. Bot tidak
    pernah menebaknya — nilai awalnya nol sampai admin mengisinya.
    """
    permission_service.boleh_ubah_pengaturan(user)

    args = (command.args or "").strip()

    if not args:
        async with session_scope() as session:
            pengaturan = await settings_repo.get(session)
            saldo = await balance_service.hitung_saldo(session)
            nilai = pengaturan.initial_balance if pengaturan else Decimal("0")

        await message.answer(
            f"💳 Saldo awal saat ini: <b>{format_rupiah(nilai)}</b>\n"
            f"Saldo sekarang: <b>{format_rupiah(saldo.saldo_sekarang)}</b>\n\n"
            "Untuk mengubah: <code>/saldoawal 1500000</code>"
        )
        return

    jumlah = parse_indonesian_amount(args)
    if jumlah is None:
        # Nol adalah nilai yang sah untuk saldo awal, tapi
        # parse_indonesian_amount menolak nol karena untuk jumlah transaksi
        # nol tidak bermakna. Jadi kasus ini ditangani khusus.
        if args.strip() in ("0", "nol"):
            jumlah = Decimal("0")
        else:
            await message.answer(
                "❌ Jumlah tidak terbaca. Contoh: <code>/saldoawal 1500000</code> "
                "atau <code>/saldoawal 1,5 juta</code>"
            )
            return

    if jumlah > 0:
        valid, jumlah, galat = validasi_jumlah(jumlah)
        if not valid:
            await message.answer(f"❌ {galat}")
            return

    async with session_scope() as session:
        pengaturan = await settings_repo.get(session)
        sebelum = str(pengaturan.initial_balance) if pengaturan else None

        await settings_repo.set_initial_balance(session, jumlah)
        await audit_repo.log(
            session,
            action=AuditAction.SETTINGS_UPDATE,
            user_id=user.id,
            telegram_id=user.telegram_id,
            details={"saldo_awal_sebelum": sebelum, "saldo_awal_sesudah": str(jumlah)},
        )
        saldo = await balance_service.hitung_saldo(session)

    await message.answer(
        f"✅ Saldo awal diatur ke <b>{format_rupiah(jumlah)}</b>.\n\n"
        f"💳 Saldo sekarang: <b>{format_rupiah(saldo.saldo_sekarang)}</b>"
    )
