"""Akses data transaksi yang menunggu konfirmasi.

Inti modul ini adalah ``claim()``: proteksi klik-ganda di tingkat database.

**Catatan tentang UPDATE massal dan objek di memori.** ``claim``, ``cancel``,
``update_parsed_data`` dan ``expire_stale`` memakai pernyataan UPDATE
berkondisi karena atomisitasnya memang inti dari fungsi-fungsi itu.
Konsekuensinya: objek ORM yang sudah terlanjur dimuat di session yang sama
TIDAK ikut berubah. Pemanggil harus membaca ulang lewat ``get()`` di session
baru bila butuh nilai terkini.

``synchronize_session="fetch"`` sengaja TIDAK dipakai. Di SQLAlchemy async,
opsi itu menandai atribut sebagai kedaluwarsa, tetapi atribut kedaluwarsa
tidak bisa dimuat ulang secara implisit saat diakses (async melarang I/O
implisit) — hasilnya atribut terbaca ``None`` tanpa error. Diverifikasi
langsung: lebih berbahaya daripada nilai basi, karena ``None`` terlihat
seperti jawaban yang sah.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PendingStatus, PendingTransaction


async def create(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    parsed_data: dict,
    source_text: str,
    expire_minutes: int = 10,
) -> PendingTransaction:
    """Simpan hasil parsing yang menunggu konfirmasi.

    ``source_text`` adalah pesan asli pengguna. Aturan ZOI: jangan membuang
    pesan pengguna — kalau parsing salah, teks aslinya masih bisa dibaca.
    """
    pending = PendingTransaction(
        telegram_user_id=telegram_user_id,
        parsed_data=parsed_data,
        source_text=source_text,
        status=PendingStatus.WAITING,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=expire_minutes),
    )
    session.add(pending)
    await session.flush()
    return pending


async def get(session: AsyncSession, pending_id: int) -> Optional[PendingTransaction]:
    return await session.get(PendingTransaction, pending_id)


async def claim(session: AsyncSession, pending_id: int, telegram_user_id: int) -> bool:
    """Klaim pending untuk disimpan. Atomik.

    Pemeriksaan dan perubahan status terjadi dalam SATU pernyataan UPDATE,
    bukan "cek dulu lalu tulis". Dua klik tombol Simpan yang datang bersamaan
    karena itu tidak mungkin keduanya menang: yang kedua mendapat nol baris.

    Syarat ``telegram_user_id`` ikut diperiksa supaya anggota lain tidak bisa
    mengonfirmasi pending milik orang lain dengan menebak ID-nya dari
    callback_data.

    :return: True bila pemanggil memegang klaim tunggal dan boleh menyimpan.
    """
    hasil = await session.execute(
        update(PendingTransaction)
        .where(
            PendingTransaction.id == pending_id,
            PendingTransaction.telegram_user_id == telegram_user_id,
            PendingTransaction.status == PendingStatus.WAITING,
            PendingTransaction.expires_at > datetime.now(timezone.utc),
        )
        .values(status=PendingStatus.CONFIRMED)
    )
    return bool(hasil.rowcount)


async def attach_transaction(
    session: AsyncSession, pending_id: int, transaction_id: int
) -> None:
    """Hubungkan pending dengan transaksi hasilnya.

    Memberi jejak dua arah: setiap transaksi hasil AI bisa dilacak kembali ke
    teks asli yang menghasilkannya. Berguna saat ada selisih dan kita perlu
    tahu apa yang sebenarnya ditulis anggota.
    """
    # Lewat ORM, bukan UPDATE massal: tidak ada syarat atomik di sini, dan
    # penugasan atribut membuat objek di memori tetap benar.
    pending = await session.get(PendingTransaction, pending_id)
    if pending is not None:
        pending.transaction_id = transaction_id
        await session.flush()


async def cancel(session: AsyncSession, pending_id: int, telegram_user_id: int) -> bool:
    """Batalkan pending. Atomik, dengan alasan yang sama seperti ``claim``."""
    hasil = await session.execute(
        update(PendingTransaction)
        .where(
            PendingTransaction.id == pending_id,
            PendingTransaction.telegram_user_id == telegram_user_id,
            PendingTransaction.status == PendingStatus.WAITING,
        )
        .values(status=PendingStatus.CANCELLED)
    )
    return bool(hasil.rowcount)


async def update_parsed_data(
    session: AsyncSession, pending_id: int, telegram_user_id: int, parsed_data: dict
) -> bool:
    """Perbarui data hasil parsing saat pengguna menekan Edit.

    Hanya boleh pada pending yang masih ``waiting``: setelah dikonfirmasi,
    perubahan harus lewat alur edit transaksi agar tercatat di audit log.
    """
    hasil = await session.execute(
        update(PendingTransaction)
        .where(
            PendingTransaction.id == pending_id,
            PendingTransaction.telegram_user_id == telegram_user_id,
            PendingTransaction.status == PendingStatus.WAITING,
        )
        .values(parsed_data=parsed_data)
    )
    return bool(hasil.rowcount)


async def expire_stale(session: AsyncSession) -> int:
    """Tandai pending kedaluwarsa sebagai ``expired``.

    Dipanggil saat ada aktivitas, bukan lewat penjadwal terpisah: bot ini satu
    proses tanpa HTTP, dan penjadwal tambahan berarti satu hal lagi yang bisa
    gagal tanpa diketahui.

    :return: jumlah baris yang ditandai.
    """
    hasil = await session.execute(
        update(PendingTransaction)
        .where(
            PendingTransaction.status == PendingStatus.WAITING,
            PendingTransaction.expires_at <= datetime.now(timezone.utc),
        )
        .values(status=PendingStatus.EXPIRED)
    )
    return int(hasil.rowcount or 0)


async def list_waiting(
    session: AsyncSession, telegram_user_id: int
) -> List[PendingTransaction]:
    hasil = await session.execute(
        select(PendingTransaction)
        .where(
            PendingTransaction.telegram_user_id == telegram_user_id,
            PendingTransaction.status == PendingStatus.WAITING,
            PendingTransaction.expires_at > datetime.now(timezone.utc),
        )
        .order_by(PendingTransaction.id.desc())
    )
    return list(hasil.scalars())
