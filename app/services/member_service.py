"""Pengelolaan anggota. Hanya admin."""

from __future__ import annotations

from typing import List

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AuditAction, User, UserRole
from app.database.repositories import audit_repo, user_repo
from app.services import permission_service
from app.utils.logger import get_logger
from app.utils.validators import bersihkan_teks, validasi_telegram_id

logger = get_logger(__name__)

#: Batas jumlah anggota aktif. ZOI dirancang untuk 2–3 akun; batas ini
#: mencegah buku kas bersama berubah menjadi sesuatu yang lain tanpa
#: keputusan sadar. Admin bisa menaikkannya di sini bila memang perlu.
MAKS_ANGGOTA_AKTIF = 5


class PengelolaanGagal(Exception):
    """Pesannya untuk dibaca pengguna."""


async def daftar(session: AsyncSession, *, user: User) -> List[User]:
    """Daftar anggota. Semua anggota aktif boleh melihatnya."""
    permission_service.boleh_lihat(user)
    return await user_repo.list_all(session)


async def tambah(
    session: AsyncSession,
    *,
    user: User,
    telegram_id_mentah: str,
    nama: str,
    sebagai_admin: bool = False,
) -> User:
    """Tambahkan anggota baru. Hanya admin."""
    permission_service.boleh_kelola_anggota(user)

    valid, tid, galat = validasi_telegram_id(telegram_id_mentah)
    if not valid:
        raise PengelolaanGagal(galat or "Telegram ID tidak sah.")

    nama_bersih = bersihkan_teks(nama, 255)
    if len(nama_bersih) < 2:
        raise PengelolaanGagal("Nama anggota minimal 2 karakter.")

    ada = await user_repo.get_by_telegram_id(session, tid)
    if ada is not None:
        if ada.is_active:
            raise PengelolaanGagal(f"{ada.full_name} sudah terdaftar dan aktif.")
        # Mengaktifkan kembali, bukan membuat baris baru: transaksi lamanya
        # menunjuk ke user.id yang ini.
        await user_repo.set_active(session, ada.id, True)
        await audit_repo.log(
            session,
            action=AuditAction.MEMBER_UPDATE,
            user_id=user.id,
            telegram_id=user.telegram_id,
            details={"target_user_id": ada.id, "aksi": "diaktifkan_kembali"},
        )
        logger.info("Anggota %s diaktifkan kembali oleh admin %s", ada.id, user.id)
        return ada

    aktif = await user_repo.list_all(session, hanya_aktif=True)
    if len(aktif) >= MAKS_ANGGOTA_AKTIF:
        raise PengelolaanGagal(
            f"Jumlah anggota aktif sudah mencapai batas ({MAKS_ANGGOTA_AKTIF}). "
            "Nonaktifkan anggota lain terlebih dahulu."
        )

    baru = await user_repo.create(
        session,
        telegram_id=tid,
        full_name=nama_bersih,
        role=UserRole.ADMIN if sebagai_admin else UserRole.MEMBER,
    )

    await audit_repo.log(
        session,
        action=AuditAction.MEMBER_ADD,
        user_id=user.id,
        telegram_id=user.telegram_id,
        details={
            "target_user_id": baru.id,
            "target_telegram_id": tid,
            "nama": nama_bersih,
            "peran": baru.role.value,
        },
    )

    logger.info("Anggota baru #%s ditambahkan oleh admin %s", baru.id, user.id)
    return baru


async def ubah_peran(
    session: AsyncSession, *, user: User, target_user_id: int, jadi_admin: bool
) -> User:
    """Ubah peran anggota. Hanya admin."""
    permission_service.boleh_kelola_anggota(user)

    target = await user_repo.get_by_id(session, target_user_id)
    if target is None:
        raise PengelolaanGagal("Anggota tidak ditemukan.")

    peran_baru = UserRole.ADMIN if jadi_admin else UserRole.MEMBER
    if target.role == peran_baru:
        raise PengelolaanGagal(f"{target.full_name} sudah berperan {peran_baru.value}.")

    # Jangan sampai tidak ada admin yang tersisa: tanpa admin, tidak ada lagi
    # yang bisa mengelola anggota atau menghapus transaksi, dan satu-satunya
    # jalan keluar adalah mengubah database secara manual.
    if target.role == UserRole.ADMIN and not jadi_admin:
        jumlah_admin = await user_repo.count_admins(session)
        if jumlah_admin <= 1:
            raise PengelolaanGagal(
                "Tidak bisa menurunkan admin terakhir. Angkat admin lain "
                "terlebih dahulu."
            )

    await user_repo.set_role(session, target.id, peran_baru)
    await audit_repo.log(
        session,
        action=AuditAction.MEMBER_UPDATE,
        user_id=user.id,
        telegram_id=user.telegram_id,
        details={
            "target_user_id": target.id,
            "peran_sebelum": target.role.value,
            "peran_sesudah": peran_baru.value,
        },
    )

    logger.info("Peran anggota %s diubah menjadi %s", target.id, peran_baru.value)
    target.role = peran_baru
    return target


async def nonaktifkan(
    session: AsyncSession, *, user: User, target_user_id: int
) -> User:
    """Nonaktifkan anggota. Hanya admin. Barisnya tidak dihapus."""
    permission_service.boleh_kelola_anggota(user)

    target = await user_repo.get_by_id(session, target_user_id)
    if target is None:
        raise PengelolaanGagal("Anggota tidak ditemukan.")
    if not target.is_active:
        raise PengelolaanGagal(f"{target.full_name} sudah tidak aktif.")

    if target.role == UserRole.ADMIN:
        jumlah_admin = await user_repo.count_admins(session)
        if jumlah_admin <= 1:
            raise PengelolaanGagal(
                "Tidak bisa menonaktifkan admin terakhir. Angkat admin lain "
                "terlebih dahulu."
            )

    await user_repo.set_active(session, target.id, False)
    await audit_repo.log(
        session,
        action=AuditAction.MEMBER_DEACTIVATE,
        user_id=user.id,
        telegram_id=user.telegram_id,
        details={"target_user_id": target.id, "nama": target.full_name},
    )

    logger.info("Anggota %s dinonaktifkan oleh admin %s", target.id, user.id)
    target.is_active = False
    return target
