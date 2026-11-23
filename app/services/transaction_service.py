"""Aturan bisnis transaksi: simpan, edit, hapus.

Tiga jaminan yang ditegakkan modul ini:

1. **Hak akses diperiksa di sini**, bukan hanya di handler. Filter aiogram
   bisa dilewati bila ada handler lain yang cocok; service tidak.
2. **Transaksi dan baris audit-nya masuk dalam satu commit.** Jejak audit
   tidak bisa menyimpang dari datanya.
3. **Tidak pernah membalas "tersimpan" sebelum commit berhasil.** Pemanggil
   hanya menerima objek transaksi bila penulisan benar-benar sukses.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.schema import ParsedTransaction
from app.database.models import (
    AuditAction,
    Transaction,
    TransactionType,
    User,
)
from app.database.repositories import (
    audit_repo,
    category_repo,
    pending_repo,
    transaction_repo,
)
from app.services import permission_service
from app.utils.logger import get_logger
from app.utils.validators import bersihkan_teks, validasi_jumlah

logger = get_logger(__name__)


class TransaksiGagal(Exception):
    """Transaksi tidak bisa diproses. Pesannya untuk dibaca pengguna."""


@dataclass
class HasilSimpan:
    transaksi: Optional[Transaction]
    duplikat_terdeteksi: Optional[Transaction] = None
    sudah_diproses: bool = False


async def simpan_dari_pending(
    session: AsyncSession,
    *,
    user: User,
    pending_id: int,
    lewati_cek_duplikat: bool = False,
) -> HasilSimpan:
    """Simpan transaksi dari pending yang dikonfirmasi pengguna.

    Alur ini adalah inti proteksi klik-ganda. ``pending_repo.claim`` memakai
    ``UPDATE ... WHERE status='waiting'`` yang atomik: dua klik tombol Simpan
    yang datang bersamaan tidak mungkin keduanya menang. Yang kedua mendapat
    ``sudah_diproses=True`` dan tidak ada apa pun yang ditulis.
    """
    permission_service.boleh_tambah(user)

    pending = await pending_repo.get(session, pending_id)
    if pending is None:
        raise TransaksiGagal("Data transaksi tidak ditemukan. Silakan catat ulang.")

    if pending.telegram_user_id != user.telegram_id:
        # Tidak membocorkan keberadaan pending milik orang lain.
        raise TransaksiGagal("Data transaksi tidak ditemukan. Silakan catat ulang.")

    parsed = ParsedTransaction.from_json(pending.parsed_data)

    if not parsed.lengkap:
        raise TransaksiGagal(
            "Data transaksi belum lengkap. Tekan Edit untuk melengkapinya."
        )

    # Klaim atomik SEBELUM cek duplikat dan sebelum menulis apa pun.
    diklaim = await pending_repo.claim(session, pending_id, user.telegram_id)
    if not diklaim:
        logger.info("Pending %s sudah diproses atau kedaluwarsa.", pending_id)
        return HasilSimpan(transaksi=None, sudah_diproses=True)

    kategori = await category_repo.resolve(session, parsed.category, parsed.transaction_type)
    if kategori is None:
        raise TransaksiGagal(
            "Kategori tidak tersedia di database. Jalankan migrasi "
            "(alembic upgrade head) lalu coba lagi."
        )

    if not lewati_cek_duplikat:
        duplikat = await transaction_repo.find_possible_duplicate(
            session,
            transaction_type=parsed.transaction_type,
            amount=parsed.amount,
            category_id=kategori.id,
            transaction_date=parsed.transaction_date,
            created_by=user.id,
        )
        if duplikat is not None:
            # Pending sudah diklaim 'confirmed'; supaya pengguna masih bisa
            # memilih "simpan saja", transaksi dibuat lewat jalur langsung
            # ketika mereka menegaskan. Lihat handler konfirmasi duplikat.
            logger.info("Kemungkinan duplikat dari transaksi #%s", duplikat.id)
            return HasilSimpan(transaksi=None, duplikat_terdeteksi=duplikat)

    trx = await _tulis(
        session,
        user=user,
        transaction_type=parsed.transaction_type,
        amount=parsed.amount,
        category_id=kategori.id,
        transaction_date=parsed.transaction_date,
        description=parsed.description,
        location=parsed.location,
        sumber=parsed.sumber,
        pending_id=pending_id,
    )

    await pending_repo.attach_transaction(session, pending_id, trx.id)
    return HasilSimpan(transaksi=trx)


async def simpan_langsung(
    session: AsyncSession,
    *,
    user: User,
    transaction_type: TransactionType,
    amount: Decimal,
    kategori_nama: Optional[str],
    transaction_date: date,
    description: Optional[str] = None,
    location: Optional[str] = None,
    sumber: str = "manual",
) -> Transaction:
    """Simpan transaksi tanpa alur pending.

    Dipakai oleh entri manual terpandu (/catat) dan ketika pengguna menegaskan
    "simpan saja" setelah peringatan duplikat. Alur AI TIDAK memakai jalur ini
    — AI selalu melewati pending + konfirmasi (aturan ZOI #8).
    """
    permission_service.boleh_tambah(user)

    valid, jumlah, galat = validasi_jumlah(amount)
    if not valid:
        raise TransaksiGagal(galat or "Jumlah tidak sah.")

    kategori = await category_repo.resolve(session, kategori_nama, transaction_type)
    if kategori is None:
        raise TransaksiGagal(
            "Kategori tidak tersedia di database. Jalankan migrasi "
            "(alembic upgrade head) lalu coba lagi."
        )

    return await _tulis(
        session,
        user=user,
        transaction_type=transaction_type,
        amount=jumlah,
        category_id=kategori.id,
        transaction_date=transaction_date,
        description=description,
        location=location,
        sumber=sumber,
        pending_id=None,
    )


async def _tulis(
    session: AsyncSession,
    *,
    user: User,
    transaction_type: TransactionType,
    amount: Decimal,
    category_id: int,
    transaction_date: date,
    description: Optional[str],
    location: Optional[str],
    sumber: str,
    pending_id: Optional[int],
) -> Transaction:
    """Tulis transaksi beserta baris auditnya, dalam session yang sama."""
    trx = await transaction_repo.create(
        session,
        transaction_type=transaction_type,
        amount=amount,
        category_id=category_id,
        transaction_date=transaction_date,
        created_by=user.id,
        description=bersihkan_teks(description, 500) or None,
        location=bersihkan_teks(location, 255) or None,
    )

    await audit_repo.log(
        session,
        action=AuditAction.TRANSACTION_CREATE,
        user_id=user.id,
        telegram_id=user.telegram_id,
        transaction_id=trx.id,
        details={
            "jenis": transaction_type.value,
            "jumlah": str(amount),
            "kategori_id": category_id,
            "tanggal": transaction_date.isoformat(),
            "sumber": sumber,
            "pending_id": pending_id,
        },
    )

    logger.info(
        "Transaksi #%s dibuat oleh user %s (%s %s, sumber=%s)",
        trx.id, user.id, transaction_type.value, amount, sumber,
    )
    return trx


async def ubah(
    session: AsyncSession,
    *,
    user: User,
    transaction_id: int,
    amount: Optional[Decimal] = None,
    kategori_nama: Optional[str] = None,
    description: Optional[str] = None,
    location: Optional[str] = None,
    transaction_date: Optional[date] = None,
) -> Transaction:
    """Ubah transaksi. Admin boleh semua; member hanya miliknya sendiri."""
    trx = await transaction_repo.get_by_id(session, transaction_id)
    if trx is None:
        raise TransaksiGagal(f"Transaksi #{transaction_id} tidak ditemukan.")

    # Pemeriksaan hak akses yang sesungguhnya.
    permission_service.boleh_edit(user, trx)

    sebelum = {
        "jumlah": str(trx.amount),
        "kategori_id": trx.category_id,
        "keterangan": trx.description,
        "lokasi": trx.location,
        "tanggal": trx.transaction_date.isoformat(),
    }

    nilai: dict = {}

    if amount is not None:
        valid, jumlah, galat = validasi_jumlah(amount)
        if not valid:
            raise TransaksiGagal(galat or "Jumlah tidak sah.")
        nilai["amount"] = jumlah

    if kategori_nama is not None:
        kategori = await category_repo.resolve(session, kategori_nama, trx.transaction_type)
        if kategori is None:
            raise TransaksiGagal("Kategori tidak ditemukan.")
        nilai["category_id"] = kategori.id

    if description is not None:
        nilai["description"] = bersihkan_teks(description, 500) or None
    if location is not None:
        nilai["location"] = bersihkan_teks(location, 255) or None
    if transaction_date is not None:
        nilai["transaction_date"] = transaction_date

    if not nilai:
        raise TransaksiGagal("Tidak ada yang diubah.")

    berubah = await transaction_repo.apply_update(
        session, transaction_id, updated_by=user.id, **nilai
    )
    if not berubah:
        raise TransaksiGagal(f"Transaksi #{transaction_id} tidak bisa diubah.")

    await audit_repo.log(
        session,
        action=AuditAction.TRANSACTION_UPDATE,
        user_id=user.id,
        telegram_id=user.telegram_id,
        transaction_id=transaction_id,
        details={
            "sebelum": sebelum,
            "sesudah": {k: (str(v) if isinstance(v, (Decimal, date)) else v) for k, v in nilai.items()},
        },
    )

    diperbarui = await transaction_repo.get_by_id(session, transaction_id)
    if diperbarui is None:  # pragma: no cover
        raise TransaksiGagal("Transaksi hilang setelah diubah.")

    logger.info("Transaksi #%s diubah oleh user %s", transaction_id, user.id)
    return diperbarui


async def hapus(session: AsyncSession, *, user: User, transaction_id: int) -> Transaction:
    """Hapus transaksi. HANYA admin (aturan ZOI #9).

    Penghapusan bersifat *soft delete*: barisnya tetap ada dengan
    ``status='deleted'`` sehingga catatan keuangan tidak pernah benar-benar
    hilang (aturan ZOI #11) dan masih bisa diaudit.
    """
    permission_service.boleh_hapus(user)

    trx = await transaction_repo.get_by_id(session, transaction_id)
    if trx is None:
        raise TransaksiGagal(
            f"Transaksi #{transaction_id} tidak ditemukan atau sudah dihapus."
        )

    salinan = {
        "jenis": trx.transaction_type.value,
        "jumlah": str(trx.amount),
        "kategori_id": trx.category_id,
        "keterangan": trx.description,
        "lokasi": trx.location,
        "tanggal": trx.transaction_date.isoformat(),
        "dicatat_oleh": trx.created_by,
    }

    terhapus = await transaction_repo.soft_delete(session, transaction_id, updated_by=user.id)
    if not terhapus:
        raise TransaksiGagal(f"Transaksi #{transaction_id} sudah dihapus sebelumnya.")

    await audit_repo.log(
        session,
        action=AuditAction.TRANSACTION_DELETE,
        user_id=user.id,
        telegram_id=user.telegram_id,
        transaction_id=transaction_id,
        # Seluruh isi transaksi disalin ke audit: kalau kelak ada pertanyaan
        # tentang catatan yang hilang, jawabannya ada di sini.
        details={"transaksi": salinan},
    )

    logger.info("Transaksi #%s dihapus oleh admin %s", transaction_id, user.id)
    return trx
