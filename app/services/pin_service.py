"""Papan saldo tersemat di percakapan Telegram.

Satu pesan per anggota, disemat di bagian atas percakapan pribadinya, berisi
saldo terkini. Pesannya DIPERBARUI di tempat setiap ada perubahan — tidak
dikirim ulang — supaya percakapan tidak penuh pesan saldo.

Tiga keputusan yang pantas dijelaskan:

**Nomor pesan disimpan di database.** Lunafy menjalankan ulang proses setiap
kali server naik. Nomor yang hanya ada di memori akan hilang di situ, dan bot
akan mengirim pesan baru setiap restart alih-alih memperbarui yang lama.

**Papan semua anggota diperbarui, bukan hanya pencatatnya.** Buku kasnya
bersama: transaksi yang dicatat satu orang mengubah saldo yang dilihat
semuanya. Papan yang hanya diperbarui untuk pencatat akan menampilkan angka
basi kepada anggota lain — lebih buruk daripada tidak ada papan sama sekali,
karena angka yang salah terlihat sama meyakinkannya dengan yang benar.

**Kegagalan di sini tidak boleh menggagalkan transaksinya.** Papan ini
kenyamanan, bukan catatan. Transaksinya sudah ter-commit sebelum fungsi ini
dipanggil; kalau Telegram menolak, yang hilang hanya kesegaran papan.
"""

from __future__ import annotations

import logging
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User
from app.database.repositories import user_repo
from app.services import balance_service
from app.utils.dates import JAKARTA, to_local, utc_now
from app.utils.money import format_rupiah

logger = logging.getLogger(__name__)

#: Bilah pesan tersemat di Telegram hanya menampilkan satu baris sebelum
#: terpotong. Baris pertama karenanya dijaga pendek dan memuat angka yang
#: paling sering dicari; sisanya baru terlihat saat bilahnya diketuk.
_BARIS_RINGKAS = "📌 Saldo: {saldo}"


def susun_teks(saldo, hari_ini, waktu) -> str:
    """Susun isi papan. Dipisah dari pengiriman supaya bisa diuji langsung."""
    baris_pertama = _BARIS_RINGKAS.format(saldo=format_rupiah(saldo.saldo_sekarang))

    if hari_ini.jumlah_transaksi:
        baris_pertama += f" · {hari_ini.jumlah_transaksi} transaksi hari ini"

    return (
        f"{baris_pertama}\n"
        "\n"
        f"Masuk hari ini: {format_rupiah(hari_ini.pemasukan)}\n"
        f"Keluar hari ini: {format_rupiah(hari_ini.pengeluaran)}\n"
        f"Total transaksi: {saldo.jumlah_transaksi}\n"
        "\n"
        f"Diperbarui {waktu.strftime('%d %b %Y %H:%M')} WIB"
    )


def _pesan_hilang(exc: TelegramAPIError) -> bool:
    """Apakah pesan yang mau diubah sudah tidak ada atau tidak bisa diubah?

    Terjadi ketika pengguna menghapus pesannya, melepas sematannya lalu
    menghapusnya, atau membersihkan riwayat percakapan.
    """
    pesan = str(exc).lower()
    return (
        "message to edit not found" in pesan
        or "message can't be edited" in pesan
        or "message identifier is not specified" in pesan
    )


def _tidak_berubah(exc: TelegramAPIError) -> bool:
    """Telegram menolak penyuntingan yang isinya persis sama.

    Itu BUKAN kegagalan: papan sudah menampilkan angka yang benar. Terjadi
    misalnya saat transaksi diubah tanpa mengubah nominalnya.
    """
    return "message is not modified" in str(exc).lower()


async def _tulis_papan_baru(
    bot: Bot, session: AsyncSession, user: User, teks: str
) -> Optional[int]:
    """Kirim pesan baru, sematkan, simpan nomornya. None bila gagal."""
    pesan = await bot.send_message(chat_id=user.telegram_id, text=teks)
    try:
        await bot.pin_chat_message(
            chat_id=user.telegram_id,
            message_id=pesan.message_id,
            disable_notification=True,
        )
    except TelegramAPIError as exc:
        # Pesannya tetap terkirim dan tetap bisa diperbarui; yang gagal
        # hanya penyematannya. Nomornya tetap disimpan.
        logger.warning(
            "Gagal menyematkan papan saldo untuk user id=%s: %s", user.id, exc
        )

    await user_repo.set_pinned_message_id(session, user.id, pesan.message_id)
    return pesan.message_id


async def perbarui_papan(bot: Bot, session: AsyncSession, *, user: User) -> None:
    """Perbarui papan satu anggota. Menelan kegagalan Telegram."""
    saldo = await balance_service.hitung_saldo(session)
    hari_ini = await balance_service.rekap_hari_ini(session)
    teks = susun_teks(saldo, hari_ini, to_local(utc_now(), JAKARTA))

    try:
        if user.pinned_message_id is not None:
            try:
                await bot.edit_message_text(
                    chat_id=user.telegram_id,
                    message_id=user.pinned_message_id,
                    text=teks,
                )
                return
            except TelegramAPIError as exc:
                if _tidak_berubah(exc):
                    return
                if not _pesan_hilang(exc):
                    raise
                # Pesannya hilang — lanjut membuat yang baru di bawah.
                logger.info(
                    "Papan saldo user id=%s hilang, dibuat ulang.", user.id
                )

        await _tulis_papan_baru(bot, session, user, teks)

    except TelegramAPIError as exc:
        # Anggota memblokir bot, belum pernah memulai percakapan, atau
        # Telegram sedang bermasalah. Bukan alasan menggagalkan transaksi
        # yang sudah tersimpan.
        logger.warning(
            "Papan saldo user id=%s tidak bisa diperbarui: %s", user.id, exc
        )


async def perbarui_semua(bot: Bot, session: AsyncSession) -> None:
    """Perbarui papan seluruh anggota aktif.

    Dipanggil setelah transaksi disimpan, diubah, atau dihapus — saat itu
    saldo yang dilihat SEMUA anggota sudah berubah, bukan hanya pencatatnya.
    """
    for anggota in await user_repo.list_all(session, hanya_aktif=True):
        await perbarui_papan(bot, session, user=anggota)


async def segarkan(bot: Bot) -> None:
    """Perbarui papan semua anggota, memakai sesi database tersendiri.

    Sesinya sengaja baru. Fungsi ini dipanggil SETELAH transaksi ter-commit,
    dan sesi yang dipakai menyimpannya sudah ditutup. Menumpang sesi yang
    sama berarti commit transaksi tertahan sampai Telegram selesai menjawab
    — dan Telegram yang lambat atau menolak akan ikut menggagalkan
    pencatatan yang sebenarnya sudah benar.
    """
    from app.database.session import session_scope

    async with session_scope() as session:
        await perbarui_semua(bot, session)
