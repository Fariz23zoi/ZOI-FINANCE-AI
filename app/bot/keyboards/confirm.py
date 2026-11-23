"""Keyboard inline untuk alur konfirmasi transaksi.

Skema callback_data dibuat pendek karena Telegram membatasinya 64 byte.
Format: ``<aksi>:<sub>:<id>``.

Setiap callback MEMBAWA pending_id, dan handler selalu memverifikasi bahwa
pending itu milik pengirim. Tanpa itu, anggota lain bisa mengonfirmasi
transaksi orang lain dengan menebak ID dari callback_data.
"""

from __future__ import annotations

from typing import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def konfirmasi(pending_id: int) -> InlineKeyboardMarkup:
    """Simpan / Edit / Batalkan."""
    b = InlineKeyboardBuilder()
    b.button(text="✅ Simpan", callback_data=f"cf:save:{pending_id}")
    b.button(text="✏️ Edit", callback_data=f"cf:edit:{pending_id}")
    b.button(text="❌ Batalkan", callback_data=f"cf:cancel:{pending_id}")
    b.adjust(2, 1)
    return b.as_markup()


def pilih_field(pending_id: int) -> InlineKeyboardMarkup:
    """Pilih bagian mana yang mau diubah."""
    b = InlineKeyboardBuilder()
    b.button(text="💰 Jumlah", callback_data=f"ed:amount:{pending_id}")
    b.button(text="🔄 Jenis", callback_data=f"ed:type:{pending_id}")
    b.button(text="🏷 Kategori", callback_data=f"ed:cat:{pending_id}")
    b.button(text="📝 Keterangan", callback_data=f"ed:desc:{pending_id}")
    b.button(text="📅 Tanggal", callback_data=f"ed:date:{pending_id}")
    b.button(text="📍 Lokasi", callback_data=f"ed:loc:{pending_id}")
    b.button(text="⬅️ Kembali", callback_data=f"ed:back:{pending_id}")
    b.adjust(2, 2, 2, 1)
    return b.as_markup()


def pilih_kategori(pending_id: int, kategori: Sequence) -> InlineKeyboardMarkup:
    """Daftar kategori sebagai tombol.

    ID kategori yang dipakai, bukan namanya: nama bisa panjang dan melampaui
    batas 64 byte callback_data.
    """
    b = InlineKeyboardBuilder()
    for k in kategori:
        b.button(text=k.name, callback_data=f"ct:{pending_id}:{k.id}")
    b.button(text="⬅️ Kembali", callback_data=f"ed:back:{pending_id}")
    b.adjust(2)
    return b.as_markup()


def duplikat(pending_id: int) -> InlineKeyboardMarkup:
    """Pilihan setelah peringatan kemungkinan duplikat."""
    b = InlineKeyboardBuilder()
    b.button(text="✅ Ya, simpan juga", callback_data=f"cf:dup:{pending_id}")
    b.button(text="❌ Batalkan", callback_data=f"cf:cancel:{pending_id}")
    b.adjust(1)
    return b.as_markup()


def pilih_jenis_baru(pending_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💸 Pengeluaran", callback_data=f"ty:{pending_id}:expense")
    b.button(text="💰 Pemasukan", callback_data=f"ty:{pending_id}:income")
    b.button(text="⬅️ Kembali", callback_data=f"ed:back:{pending_id}")
    b.adjust(2, 1)
    return b.as_markup()


def hapus_konfirmasi(transaction_id: int) -> InlineKeyboardMarkup:
    """Konfirmasi penghapusan. Dua langkah karena penghapusan tidak bisa
    dibatalkan dari sisi pengguna."""
    b = InlineKeyboardBuilder()
    b.button(text="🗑 Ya, hapus", callback_data=f"dl:ok:{transaction_id}")
    b.button(text="⬅️ Tidak", callback_data="dl:no:0")
    b.adjust(2)
    return b.as_markup()


def daftar_hapus(transaksi: Sequence) -> InlineKeyboardMarkup:
    """Daftar transaksi terbaru untuk dipilih dan dihapus."""
    from app.utils.money import format_rupiah

    b = InlineKeyboardBuilder()
    for t in transaksi:
        tanda = "💰" if t.transaction_type.value == "income" else "💸"
        label = f"{tanda} #{t.id} {format_rupiah(t.amount)} · {(t.description or '-')[:18]}"
        b.button(text=label[:60], callback_data=f"dl:pick:{t.id}")
    b.adjust(1)
    return b.as_markup()


def daftar_edit(transaksi: Sequence) -> InlineKeyboardMarkup:
    """Daftar transaksi terbaru untuk dipilih dan diubah."""
    from app.utils.money import format_rupiah

    b = InlineKeyboardBuilder()
    for t in transaksi:
        tanda = "💰" if t.transaction_type.value == "income" else "💸"
        label = f"{tanda} #{t.id} {format_rupiah(t.amount)} · {(t.description or '-')[:18]}"
        b.button(text=label[:60], callback_data=f"et:pick:{t.id}")
    b.button(text="❌ Tutup", callback_data="et:cancel:0")
    b.adjust(1)
    return b.as_markup()


def field_transaksi(transaction_id: int) -> InlineKeyboardMarkup:
    """Pilih bagian transaksi tersimpan yang akan diubah.

    Jenis transaksi TIDAK bisa diubah di sini. Mengubah pengeluaran menjadi
    pemasukan menggeser saldo dua kali nilainya dan membuat kategorinya tidak
    lagi sah; lebih jujur menghapusnya (admin) lalu mencatat ulang, sehingga
    kedua langkah itu terbaca jelas di jejak audit.
    """
    b = InlineKeyboardBuilder()
    b.button(text="💰 Jumlah", callback_data=f"et:f:amount:{transaction_id}")
    b.button(text="🏷 Kategori", callback_data=f"et:f:cat:{transaction_id}")
    b.button(text="📝 Keterangan", callback_data=f"et:f:desc:{transaction_id}")
    b.button(text="📅 Tanggal", callback_data=f"et:f:date:{transaction_id}")
    b.button(text="📍 Lokasi", callback_data=f"et:f:loc:{transaction_id}")
    b.button(text="❌ Tutup", callback_data="et:cancel:0")
    b.adjust(2, 2, 1, 1)
    return b.as_markup()


def kategori_transaksi(transaction_id: int, kategori: Sequence) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for k in kategori:
        b.button(text=k.name, callback_data=f"et:c:{transaction_id}:{k.id}")
    b.button(text="⬅️ Kembali", callback_data=f"et:pick:{transaction_id}")
    b.adjust(2)
    return b.as_markup()
