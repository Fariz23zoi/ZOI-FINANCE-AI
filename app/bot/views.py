"""Penyusun teks pesan.

Dipisahkan dari handler supaya bisa diuji tanpa objek aiogram, dan supaya
format tampilan konsisten di seluruh bot.
"""

from __future__ import annotations

from typing import Optional, Sequence

from app.ai.schema import ParsedTransaction
from app.database.models import Transaction, TransactionType, User
from app.services.balance_service import BarisBulanan, RekapPeriode, Saldo
from app.utils.dates import JAKARTA, format_date_id, format_month_id, to_local
from app.utils.money import format_rupiah


def _tanda(jenis: TransactionType) -> str:
    return "💰" if jenis == TransactionType.INCOME else "💸"


def _nama_jenis(jenis: TransactionType) -> str:
    return "Pemasukan" if jenis == TransactionType.INCOME else "Pengeluaran"


def konfirmasi(parsed: ParsedTransaction, nama_pencatat: str, kategori: str) -> str:
    """Layar konfirmasi sebelum transaksi disimpan.

    Catatan yang lemah ditandai dengan "(mohon dicek)" supaya pengguna tahu
    bagian mana yang ditebak oleh bot dan bukan dibaca dari pesannya.
    """
    jenis = parsed.transaction_type
    tanda_tipe = " (mohon dicek)" if "transaction_type" in parsed.kurang else ""
    tanda_kat = " (mohon dicek)" if "category" in parsed.kurang else ""

    baris = [
        "<b>Konfirmasi transaksi</b>",
        "",
        f"{_tanda(jenis)} Jenis: <b>{_nama_jenis(jenis)}</b>{tanda_tipe}",
        f"💵 Jumlah: <b>{format_rupiah(parsed.amount)}</b>",
        f"🏷 Kategori: {kategori}{tanda_kat}",
    ]

    if parsed.description:
        baris.append(f"📝 Keterangan: {parsed.description}")
    if parsed.location:
        baris.append(f"📍 Lokasi: {parsed.location}")

    baris += [
        f"📅 Tanggal: {format_date_id(parsed.transaction_date)}",
        f"👤 Dicatat oleh: {nama_pencatat}",
        "",
        "Simpan transaksi ini?",
    ]

    if parsed.sumber == "parser":
        baris.append("<i>Dibaca tanpa AI (hemat kuota).</i>")

    return "\n".join(baris)


def tersimpan(trx: Transaction, saldo: Saldo, kategori: str) -> str:
    return "\n".join([
        "✅ <b>Transaksi tersimpan</b>",
        "",
        f"{_tanda(trx.transaction_type)} {_nama_jenis(trx.transaction_type)}: "
        f"<b>{format_rupiah(trx.amount)}</b>",
        f"🏷 {kategori}",
        f"📅 {format_date_id(trx.transaction_date)}",
        f"🔖 Nomor transaksi: #{trx.id}",
        "",
        f"💳 Saldo sekarang: <b>{format_rupiah(saldo.saldo_sekarang)}</b>",
    ])


def saldo_bersama(saldo: Saldo, bulan: RekapPeriode) -> str:
    return "\n".join([
        "💳 <b>Saldo Bersama</b>",
        "",
        f"Saldo sekarang: <b>{format_rupiah(saldo.saldo_sekarang)}</b>",
        "",
        f"Saldo awal: {format_rupiah(saldo.saldo_awal)}",
        f"Total pemasukan: {format_rupiah(saldo.total_pemasukan)}",
        f"Total pengeluaran: {format_rupiah(saldo.total_pengeluaran)}",
        f"Jumlah transaksi: {saldo.jumlah_transaksi}",
        "",
        f"<b>{format_month_id(bulan.mulai)}</b>",
        f"Masuk: {format_rupiah(bulan.pemasukan)}",
        f"Keluar: {format_rupiah(bulan.pengeluaran)}",
        f"Selisih: {format_rupiah(bulan.selisih)}",
    ])


def daftar_transaksi(
    judul: str, transaksi: Sequence[Transaction], rekap: Optional[RekapPeriode] = None
) -> str:
    if not transaksi:
        return f"<b>{judul}</b>\n\nBelum ada transaksi."

    baris = [f"<b>{judul}</b>", ""]

    for t in transaksi:
        bagian = [
            f"{_tanda(t.transaction_type)} <b>{format_rupiah(t.amount)}</b> · "
            f"{t.category.name if t.category else '-'}"
        ]
        if t.description:
            bagian.append(f"   {t.description}")
        jejak = []
        if t.location:
            jejak.append(f"📍 {t.location}")
        jejak.append(f"👤 {t.creator.full_name if t.creator else '-'}")
        jejak.append(f"#{t.id}")
        bagian.append("   " + " · ".join(jejak))
        baris.append("\n".join(bagian))

    if rekap is not None:
        baris += [
            "",
            f"Masuk: {format_rupiah(rekap.pemasukan)}",
            f"Keluar: {format_rupiah(rekap.pengeluaran)}",
            f"Selisih: <b>{format_rupiah(rekap.selisih)}</b>",
        ]

    return "\n".join(baris)


def rekap_bulanan(baris_bulan: Sequence[BarisBulanan]) -> str:
    if not baris_bulan:
        return "<b>Rekap Bulanan</b>\n\nBelum ada transaksi."

    baris = ["<b>Rekap Bulanan</b>", ""]
    for b in baris_bulan:
        baris += [
            f"<b>{format_month_id(b.bulan)}</b>",
            f"  Masuk: {format_rupiah(b.pemasukan)}",
            f"  Keluar: {format_rupiah(b.pengeluaran)}",
            f"  Selisih: {format_rupiah(b.selisih)}",
            f"  Saldo akhir: <b>{format_rupiah(b.saldo_akhir)}</b>",
            f"  {b.jumlah_transaksi} transaksi",
            "",
        ]
    return "\n".join(baris).rstrip()


def daftar_anggota(anggota: Sequence[User], peminta_admin: bool) -> str:
    baris = ["👥 <b>Anggota</b>", ""]

    for a in anggota:
        lencana = "👑" if a.is_admin else "👤"
        status = "" if a.is_active else " <i>(tidak aktif)</i>"
        baris.append(f"{lencana} <b>{a.full_name}</b>{status}")
        baris.append(f"   {a.role.value}" + (f" · @{a.username}" if a.username else ""))
        if peminta_admin:
            # ID hanya ditampilkan ke admin: ini yang dipakai untuk otorisasi.
            baris.append(f"   ID: <code>{a.telegram_id}</code>")
        baris.append("")

    if peminta_admin:
        baris.append("<i>Tambah anggota: /anggota tambah &lt;telegram_id&gt; &lt;nama&gt;</i>")

    return "\n".join(baris).rstrip()


def bantuan(adalah_admin: bool) -> str:
    baris = [
        "<b>ZOI FINANCE AI</b>",
        "<i>Smart Finance. Simple Control.</i>",
        "",
        "<b>Cara tercepat:</b> kirim saja pesan biasa.",
        "",
        "<code>Bayar parkir motor 2 ribu di pasar Ciamis</code>",
        "<code>Beli bensin 30rb</code>",
        "<code>Kemarin beli pulsa 25 ribu</code>",
        "<code>Dapat uang tambahan 500 ribu</code>",
        "",
        "Bot membaca jenis, jumlah, kategori, lokasi, dan tanggalnya, lalu "
        "meminta konfirmasi Anda sebelum menyimpan.",
        "",
        "<b>Satuan yang dipahami:</b>",
        "2 ribu = Rp2.000 · 25rb = Rp25.000",
        "1 juta = Rp1.000.000 · 1,5 juta = Rp1.500.000",
        "500.000 = Rp500.000",
        "",
        "<b>Perintah:</b>",
        "/catat — catat transaksi langkah demi langkah",
        "/edit — ubah transaksi yang sudah tersimpan",
        "/saldo — saldo bersama",
        "/hariini — transaksi hari ini",
        "/bulanan — rekap bulanan",
        "/anggota — daftar anggota",
        "/excel — laporan Excel",
        "/bantuan — bantuan ini",
    ]

    if adalah_admin:
        baris += [
            "",
            "<b>Khusus administrator:</b>",
            "/hapus — hapus transaksi",
            "/edit — bisa mengubah transaksi siapa pun",
            "/hapus &lt;nomor&gt; — hapus transaksi tertentu",
            "/anggota tambah &lt;telegram_id&gt; &lt;nama&gt;",
            "/saldoawal &lt;jumlah&gt; — atur saldo awal",
        ]

    return "\n".join(baris)
