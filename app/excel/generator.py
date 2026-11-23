"""Pembentuk laporan Excel lima sheet.

Selalu dibangun dari data PostgreSQL (lihat ``app/services/report_service.py``):
PostgreSQL adalah sumber kebenaran, Excel hanya laporan yang dihasilkan.

Catatan tentang angka. Nilai uang ditulis sebagai ``float`` ke sel Excel, dan
itu memang satu-satunya pilihan: format file xlsx menyimpan angka sebagai
IEEE 754 double, sehingga openpyxl tidak bisa menuliskan Decimal apa adanya.
Yang penting: konversi hanya terjadi pada LANGKAH TERAKHIR, saat menulis ke
sel. Seluruh perhitungan — saldo, total, rekap — sudah selesai di PostgreSQL
dengan NUMERIC sebelum sampai ke sini, jadi tidak ada aritmetika float di
jalur mana pun. Dengan dua angka desimal dan nilai Rupiah yang realistis,
double merepresentasikan nilainya dengan tepat.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import List, Optional, Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.database.models import Transaction
from app.services.report_service import DataLaporan
from app.utils.dates import JAKARTA, format_month_id, to_local

#: Format angka Rupiah gaya Indonesia: titik ribuan, tanpa desimal.
#: Negatif ditulis merah dalam tanda kurung, lazim di laporan keuangan.
FORMAT_RUPIAH = '_-"Rp"* #.##0_-;[Red]_-"Rp"* (#.##0)_-;_-"Rp"* "-"_-'
FORMAT_TANGGAL = "DD/MM/YYYY"
FORMAT_WAKTU = "DD/MM/YYYY HH:MM"

WARNA_JUDUL = "FF1F3864"
WARNA_HEADER = "FF2E5C8A"
WARNA_TOTAL = "FFD9E2F3"
WARNA_PEMASUKAN = "FFE2EFDA"
WARNA_PENGELUARAN = "FFFCE4E4"

FONT_JUDUL = Font(bold=True, size=14, color="FFFFFFFF")
FONT_HEADER = Font(bold=True, size=11, color="FFFFFFFF")
FONT_TOTAL = Font(bold=True, size=11)
FONT_LABEL = Font(bold=True, size=11)

TIPIS = Side(style="thin", color="FFBFBFBF")
GARIS = Border(left=TIPIS, right=TIPIS, top=TIPIS, bottom=TIPIS)

KOLOM_TRANSAKSI = [
    ("No.", 6),
    ("Tanggal", 12),
    ("Jenis", 13),
    ("Keterangan", 34),
    ("Kategori", 20),
    ("Lokasi", 20),
    ("Pemasukan", 16),
    ("Pengeluaran", 16),
    ("Dicatat Oleh", 18),
    ("Dibuat Pada", 18),
]


def _rp(nilai) -> float:
    """Konversi nilai uang ke float untuk ditulis ke sel.

    Hanya dipakai pada langkah penulisan terakhir — lihat catatan di kepala
    modul. Jangan pakai hasilnya untuk perhitungan apa pun.
    """
    return float(Decimal(str(nilai)))


def _judul(ws: Worksheet, teks: str, lebar_kolom: int) -> None:
    """Tulis baris judul yang merentang selebar tabel."""
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=lebar_kolom)
    sel = ws.cell(row=1, column=1, value=teks)
    sel.font = FONT_JUDUL
    sel.fill = PatternFill("solid", fgColor=WARNA_JUDUL)
    sel.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 26


def _header(ws: Worksheet, baris: int, kolom: Sequence[tuple]) -> None:
    """Tulis baris header dan atur lebar kolom."""
    for i, (nama, lebar) in enumerate(kolom, start=1):
        sel = ws.cell(row=baris, column=i, value=nama)
        sel.font = FONT_HEADER
        sel.fill = PatternFill("solid", fgColor=WARNA_HEADER)
        sel.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        sel.border = GARIS
        ws.column_dimensions[get_column_letter(i)].width = lebar
    ws.row_dimensions[baris].height = 22


def _tabel_transaksi(
    ws: Worksheet,
    judul: str,
    transaksi: List[Transaction],
    warna_baris: Optional[str] = None,
) -> None:
    """Bangun satu sheet berisi tabel transaksi dengan baris total.

    Baris total memakai FORMULA ``SUBTOTAL(109; ...)``, bukan angka yang
    sudah dihitung. ``SUBTOTAL`` mengabaikan baris yang disembunyikan oleh
    filter, jadi ketika pengguna menyaring (misalnya satu kategori saja),
    totalnya ikut menyesuaikan di dalam Excel. Angka statis tidak akan.
    """
    _judul(ws, judul, len(KOLOM_TRANSAKSI))
    BARIS_HEADER = 3
    _header(ws, BARIS_HEADER, KOLOM_TRANSAKSI)

    baris = BARIS_HEADER + 1
    for no, t in enumerate(transaksi, start=1):
        masuk = t.transaction_type.value == "income"
        nilai = [
            no,
            t.transaction_date,
            "Pemasukan" if masuk else "Pengeluaran",
            t.description or "-",
            t.category.name if t.category else "-",
            t.location or "-",
            _rp(t.amount) if masuk else None,
            None if masuk else _rp(t.amount),
            t.creator.full_name if t.creator else "-",
            to_local(t.created_at, JAKARTA).replace(tzinfo=None) if t.created_at else None,
        ]

        for kol, v in enumerate(nilai, start=1):
            sel = ws.cell(row=baris, column=kol, value=v)
            sel.border = GARIS
            if kol == 1:
                sel.alignment = Alignment(horizontal="center")
            elif kol == 2:
                sel.number_format = FORMAT_TANGGAL
                sel.alignment = Alignment(horizontal="center")
            elif kol in (7, 8):
                sel.number_format = FORMAT_RUPIAH
            elif kol == 10:
                sel.number_format = FORMAT_WAKTU

            if warna_baris:
                sel.fill = PatternFill("solid", fgColor=warna_baris)

        baris += 1

    baris_akhir_data = baris - 1
    baris_total = baris

    sel = ws.cell(row=baris_total, column=1, value="TOTAL")
    sel.font = FONT_TOTAL
    ws.merge_cells(start_row=baris_total, start_column=1, end_row=baris_total, end_column=6)

    for kol in (7, 8):
        huruf = get_column_letter(kol)
        if transaksi:
            rumus = f"=SUBTOTAL(109,{huruf}{BARIS_HEADER + 1}:{huruf}{baris_akhir_data})"
        else:
            rumus = 0
        sel = ws.cell(row=baris_total, column=kol, value=rumus)
        sel.number_format = FORMAT_RUPIAH
        sel.font = FONT_TOTAL

    for kol in range(1, len(KOLOM_TRANSAKSI) + 1):
        sel = ws.cell(row=baris_total, column=kol)
        sel.fill = PatternFill("solid", fgColor=WARNA_TOTAL)
        sel.border = GARIS

    # Header dibekukan supaya tetap terlihat saat menggulir daftar panjang,
    # dan filter dipasang hanya pada rentang data (baris TOTAL di luar
    # rentang, supaya tidak ikut tersaring dan hilang).
    ws.freeze_panes = f"A{BARIS_HEADER + 1}"
    if transaksi:
        ws.auto_filter.ref = (
            f"A{BARIS_HEADER}:{get_column_letter(len(KOLOM_TRANSAKSI))}{baris_akhir_data}"
        )


def _sheet_dashboard(ws: Worksheet, data: DataLaporan) -> None:
    """Sheet 1 — ringkasan angka penting."""
    _judul(ws, "ZOI FINANCE AI — Dashboard", 3)

    ws.column_dimensions["A"].width = 4
    ws.column_dimensions["B"].width = 34
    ws.column_dimensions["C"].width = 22

    s = data.saldo
    b = data.bulan_ini

    isi = [
        ("RINGKASAN KESELURUHAN", None, None),
        ("Saldo Awal", _rp(s.saldo_awal), "rp"),
        ("Total Pemasukan", _rp(s.total_pemasukan), "rp"),
        ("Total Pengeluaran", _rp(s.total_pengeluaran), "rp"),
        ("Saldo Saat Ini", _rp(s.saldo_sekarang), "rp_tebal"),
        ("Jumlah Transaksi", s.jumlah_transaksi, "angka"),
        (None, None, None),
        (f"BULAN INI — {format_month_id(b.mulai)}", None, None),
        ("Pemasukan Bulan Ini", _rp(b.pemasukan), "rp"),
        ("Pengeluaran Bulan Ini", _rp(b.pengeluaran), "rp"),
        ("Selisih Bulan Ini", _rp(b.selisih), "rp_tebal"),
        ("Transaksi Bulan Ini", b.jumlah_transaksi, "angka"),
        (None, None, None),
        ("INFORMASI", None, None),
        ("Mata Uang", data.mata_uang, "teks"),
        ("Zona Waktu", data.zona_waktu, "teks"),
        (
            "Laporan Dibuat",
            datetime.now(JAKARTA).replace(tzinfo=None),
            "waktu",
        ),
    ]

    baris = 3
    for label, nilai, gaya in isi:
        if label is None:
            baris += 1
            continue

        if gaya is None:
            sel = ws.cell(row=baris, column=2, value=label)
            sel.font = Font(bold=True, size=11, color="FFFFFFFF")
            sel.fill = PatternFill("solid", fgColor=WARNA_HEADER)
            ws.merge_cells(start_row=baris, start_column=2, end_row=baris, end_column=3)
            baris += 1
            continue

        sel_label = ws.cell(row=baris, column=2, value=label)
        sel_label.font = FONT_LABEL
        sel_label.border = GARIS

        sel_nilai = ws.cell(row=baris, column=3, value=nilai)
        sel_nilai.border = GARIS

        if gaya.startswith("rp"):
            sel_nilai.number_format = FORMAT_RUPIAH
        elif gaya == "angka":
            sel_nilai.number_format = "#,##0"
            sel_nilai.alignment = Alignment(horizontal="right")
        elif gaya == "waktu":
            sel_nilai.number_format = FORMAT_WAKTU

        if gaya.endswith("_tebal"):
            sel_nilai.font = FONT_TOTAL
            sel_label.fill = PatternFill("solid", fgColor=WARNA_TOTAL)
            sel_nilai.fill = PatternFill("solid", fgColor=WARNA_TOTAL)

        baris += 1


def _sheet_rekap_bulanan(ws: Worksheet, data: DataLaporan) -> None:
    """Sheet 5 — rekap per bulan dengan saldo akhir berjalan."""
    kolom = [
        ("Bulan", 20),
        ("Total Pemasukan", 18),
        ("Total Pengeluaran", 18),
        ("Selisih", 18),
        ("Jumlah Transaksi", 16),
        ("Saldo Akhir", 20),
    ]

    _judul(ws, "Rekap Bulanan", len(kolom))
    BARIS_HEADER = 3
    _header(ws, BARIS_HEADER, kolom)

    baris = BARIS_HEADER + 1
    for b in data.bulanan:
        nilai = [
            format_month_id(b.bulan),
            _rp(b.pemasukan),
            _rp(b.pengeluaran),
            _rp(b.selisih),
            b.jumlah_transaksi,
            _rp(b.saldo_akhir),
        ]
        for kol, v in enumerate(nilai, start=1):
            sel = ws.cell(row=baris, column=kol, value=v)
            sel.border = GARIS
            if kol in (2, 3, 4, 6):
                sel.number_format = FORMAT_RUPIAH
            elif kol == 5:
                sel.alignment = Alignment(horizontal="center")
        baris += 1

    baris_akhir = baris - 1
    if data.bulanan:
        sel = ws.cell(row=baris, column=1, value="TOTAL")
        sel.font = FONT_TOTAL
        for kol in (2, 3, 4, 5):
            huruf = get_column_letter(kol)
            sel = ws.cell(
                row=baris,
                column=kol,
                value=f"=SUM({huruf}{BARIS_HEADER + 1}:{huruf}{baris_akhir})",
            )
            sel.font = FONT_TOTAL
            sel.number_format = FORMAT_RUPIAH if kol != 5 else "#,##0"

        # Saldo akhir tidak dijumlahkan: nilainya kumulatif, jadi yang benar
        # adalah nilai bulan terakhir. Menjumlahkannya akan menghasilkan angka
        # yang tidak bermakna.
        sel = ws.cell(row=baris, column=6, value=f"=F{baris_akhir}")
        sel.font = FONT_TOTAL
        sel.number_format = FORMAT_RUPIAH

        for kol in range(1, len(kolom) + 1):
            s2 = ws.cell(row=baris, column=kol)
            s2.fill = PatternFill("solid", fgColor=WARNA_TOTAL)
            s2.border = GARIS

    ws.freeze_panes = f"A{BARIS_HEADER + 1}"


def bangun_workbook(data: DataLaporan) -> Workbook:
    """Bangun workbook lima sheet sesuai spesifikasi ZOI bagian 13."""
    wb = Workbook()

    ws1 = wb.active
    ws1.title = "DASHBOARD"
    _sheet_dashboard(ws1, data)

    _tabel_transaksi(
        wb.create_sheet("TRANSAKSI"), "Semua Transaksi", data.semua_transaksi
    )
    _tabel_transaksi(
        wb.create_sheet("PEMASUKAN"), "Pemasukan", data.pemasukan, WARNA_PEMASUKAN
    )
    _tabel_transaksi(
        wb.create_sheet("PENGELUARAN"), "Pengeluaran", data.pengeluaran, WARNA_PENGELUARAN
    )
    _sheet_rekap_bulanan(wb.create_sheet("REKAP BULANAN"), data)

    return wb


def simpan(data: DataLaporan, direktori: str = "output") -> Path:
    """Bangun dan simpan workbook. Mengembalikan path file.

    Ditulis ke ``output/`` yang sudah masuk .gitignore, dan dihapus setelah
    terkirim. Disk server Lunafy hanya 512 MB, jadi file laporan tidak
    disimpan — toh bisa dibuat ulang kapan saja dari PostgreSQL.
    """
    folder = Path(direktori)
    folder.mkdir(parents=True, exist_ok=True)

    stempel = datetime.now(JAKARTA).strftime("%Y%m%d-%H%M")
    path = folder / f"ZOI-FINANCE-{stempel}.xlsx"

    bangun_workbook(data).save(path)
    return path
