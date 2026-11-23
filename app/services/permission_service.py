"""Penegakan hak akses.

Pola ini ditiru dari nikamurkaa/finance-helper, yang menegakkan peran di
lapisan data sehingga tidak bisa di-bypass lewat handler lain. Ditulis ulang
dan disederhanakan menjadi dua peran pada satu buku kas bersama.

Filter aiogram (``app/bot/filters``) hanya untuk UX — menyembunyikan tombol
dan memberi pesan ramah. Keputusan keamanan sesungguhnya diambil di sini, dan
setiap service yang mengubah data WAJIB memanggilnya.
"""

from __future__ import annotations

from app.database.models import Transaction, User


class PermissionDenied(Exception):
    """Aksi ditolak karena hak akses.

    Pesannya ditulis untuk dibaca langsung oleh pengguna di Telegram, jadi
    harus jelas dan tidak membocorkan detail internal.
    """


def pastikan_aktif(user: User) -> None:
    """Pastikan anggota masih aktif."""
    if not user.is_active:
        raise PermissionDenied(
            "Akun Anda tidak aktif. Hubungi administrator untuk mengaktifkannya."
        )


def pastikan_admin(user: User) -> None:
    """Pastikan anggota berperan admin."""
    pastikan_aktif(user)
    if not user.is_admin:
        raise PermissionDenied("Hanya administrator yang boleh melakukan ini.")


def boleh_tambah(user: User) -> None:
    """Semua anggota aktif boleh menambah transaksi."""
    pastikan_aktif(user)


def boleh_lihat(user: User) -> None:
    """Semua anggota aktif boleh melihat saldo dan seluruh riwayat.

    Ini inti dari "buku kas bersama": tidak ada penyaringan per pengguna.
    """
    pastikan_aktif(user)


def boleh_edit(user: User, trx: Transaction) -> None:
    """Admin boleh mengedit semua transaksi; member hanya miliknya sendiri."""
    pastikan_aktif(user)

    if user.is_admin:
        return

    if trx.created_by != user.id:
        raise PermissionDenied(
            "Anda hanya bisa mengubah transaksi yang Anda catat sendiri. "
            "Minta administrator bila transaksi ini perlu diperbaiki."
        )


def boleh_hapus(user: User) -> None:
    """Hanya admin boleh menghapus. Aturan ZOI #9, tanpa pengecualian."""
    pastikan_aktif(user)
    if not user.is_admin:
        raise PermissionDenied(
            "Hanya administrator yang boleh menghapus transaksi. "
            "Kalau ada catatan yang salah, minta administrator memperbaikinya."
        )


def boleh_kelola_anggota(user: User) -> None:
    pastikan_admin(user)


def boleh_ubah_pengaturan(user: User) -> None:
    pastikan_admin(user)


def boleh_ekspor(user: User, member_can_export: bool) -> None:
    """Admin selalu boleh; member tergantung pengaturan."""
    pastikan_aktif(user)

    if user.is_admin:
        return

    if not member_can_export:
        raise PermissionDenied(
            "Ekspor Excel saat ini hanya untuk administrator. "
            "Minta administrator mengaktifkannya bila Anda memerlukannya."
        )
