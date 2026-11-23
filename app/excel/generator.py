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
from openpyxl.chart import BarChart, DoughnutChart, LineChart, Reference
from openpyxl.chart.axis import ChartLines
from openpyxl.chart.label import DataLabelList
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.chart.text import RichText
from openpyxl.drawing.text import (
    CharacterProperties,
    Paragraph,
    ParagraphProperties,
)
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.database.models import Transaction
from app.services.report_service import DataLaporan
from app.utils.dates import JAKARTA, format_month_id, to_local

#: Format angka Rupiah: tanpa desimal, negatif merah dalam tanda kurung.
#:
#: Pemisah ribuan DITULIS sebagai koma, bukan titik. Di dalam format angka
#: Excel, "," selalu berarti pemisah ribuan dan "." selalu berarti pemisah
#: desimal, apa pun lokal penggunanya; Excel-lah yang menampilkannya sebagai
#: titik untuk lokal Indonesia. Menulis "#.##0" membuat Excel membacanya
#: sebagai angka berdesimal, sehingga 22500 tampil "22500,0".
FORMAT_RUPIAH = '_-"Rp"* #,##0_-;[Red]_-"Rp"* (#,##0)_-;_-"Rp"* "-"_-'

#: Varian rapat untuk kartu KPI. Format akuntansi di atas merenggangkan
#: "Rp" ke tepi kiri sel; pada angka besar berukuran 16pt jaraknya jadi
#: terlalu jauh untuk dibaca sebagai satu kesatuan.
FORMAT_RUPIAH_RAPAT = '"Rp"#,##0;[Red]-"Rp"#,##0;"Rp"0'
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


# ── Palet tema gelap untuk sheet Dashboard ────────────────────────
#
# Dipisah dari palet terang sheet lain: hanya Dashboard yang gelap,
# supaya tabel transaksi tetap enak dibaca dan ramah dicetak.
D_LATAR = "FF0B1220"
D_PANEL = "FF131F33"
D_GARIS = "FF1E3A5F"
D_TEKS = "FFE2E8F0"
D_REDUP = "FF94A3B8"
D_SIAN = "FF22D3EE"
D_HIJAU = "FF22C55E"
D_MERAH = "FFEF4444"
D_BIRU = "FF3B82F6"
D_KUNING = "FFF59E0B"

#: Kolom tersembunyi tempat data sumber grafik ditulis. Grafik Excel hanya
#: bisa menunjuk ke sel, tidak bisa diberi angka langsung, jadi angkanya
#: harus ada di suatu tempat di sheet ini.
KOL_DATA = 21  # kolom U


def _warnai(ws, r1, c1, r2, c2, warna):
    """Warnai setiap sel dalam rentang, tanpa menggabungkan.

    Mewarnai satu sel saja tidak cukup: pada sel tergabung, Excel tetap
    menggambar latar tiap sel aslinya.
    """
    for r in range(r1, r2 + 1):
        for c in range(c1, c2 + 1):
            ws.cell(row=r, column=c).fill = PatternFill("solid", fgColor=warna)


def _isi_blok(ws, r1, c1, r2, c2, warna):
    """Warnai rentang lalu gabungkan, dan kembalikan sel kirinya.

    Hanya untuk rentang yang belum tergabung. Menggabungkan sebuah blok
    lalu menggabungkan bagian di dalamnya membuat openpyxl menolak
    penulisan: sel di dalam rentang gabungan bersifat baca-saja.
    """
    _warnai(ws, r1, c1, r2, c2, warna)
    if (r1, c1) != (r2, c2):
        ws.merge_cells(start_row=r1, start_column=c1, end_row=r2, end_column=c2)
    return ws.cell(row=r1, column=c1)


def _kartu_kpi(ws, baris, kolom, judul, nilai, catatan, warna_aksen, format_nilai):
    """Satu kartu KPI setinggi 3 baris, selebar 3 kolom."""
    _warnai(ws, baris, kolom, baris + 2, kolom + 2, D_PANEL)

    tepi = Side(style="thin", color=warna_aksen)
    for c in range(kolom, kolom + 3):
        ws.cell(row=baris, column=c).border = Border(top=tepi)
        ws.cell(row=baris + 2, column=c).border = Border(bottom=tepi)

    sel_judul = _isi_blok(ws, baris, kolom, baris, kolom + 2, D_PANEL)
    sel_judul.value = judul
    sel_judul.font = Font(bold=True, size=10, color=warna_aksen)
    sel_judul.alignment = Alignment(horizontal="left", vertical="center", indent=1)

    sel_nilai = _isi_blok(ws, baris + 1, kolom, baris + 1, kolom + 2, D_PANEL)
    sel_nilai.value = nilai
    sel_nilai.number_format = format_nilai
    sel_nilai.font = Font(bold=True, size=16, color=D_TEKS)
    sel_nilai.alignment = Alignment(horizontal="left", vertical="center", indent=1)

    sel_catatan = _isi_blok(ws, baris + 2, kolom, baris + 2, kolom + 2, D_PANEL)
    sel_catatan.value = catatan
    sel_catatan.font = Font(size=9, color=D_REDUP)
    sel_catatan.alignment = Alignment(horizontal="left", vertical="center", indent=1)

    ws.row_dimensions[baris].height = 16
    ws.row_dimensions[baris + 1].height = 26
    ws.row_dimensions[baris + 2].height = 15


def _panel(ws, r1, c1, r2, c2, judul):
    """Panel berlatar gelap dengan baris judul bergaris bawah sian."""
    _warnai(ws, r1, c1, r2, c2, D_PANEL)
    sel = _isi_blok(ws, r1, c1, r1, c2, D_PANEL)
    sel.value = judul
    sel.font = Font(bold=True, size=11, color=D_SIAN)
    sel.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    for c in range(c1, c2 + 1):
        ws.cell(row=r1, column=c).border = Border(
            bottom=Side(style="thin", color=D_GARIS)
        )
    ws.row_dimensions[r1].height = 20


def _gaya_grafik_gelap(grafik):
    """Samakan grafik dengan tema gelap sheet.

    Tanpa ini grafik tampil berlatar putih di tengah panel gelap.
    """
    teks = CharacterProperties(solidFill=D_TEKS[2:], sz=900)
    paragraf = RichText(
        p=[Paragraph(pPr=ParagraphProperties(defRPr=teks), endParaRPr=teks)]
    )
    grafik.txPr = paragraf
    grafik.graphical_properties = GraphicalProperties(solidFill=D_PANEL[2:])
    grafik.graphical_properties.line.solidFill = D_GARIS[2:]

    for sumbu in (getattr(grafik, "x_axis", None), getattr(grafik, "y_axis", None)):
        if sumbu is None:
            continue
        sumbu.delete = False
        sumbu.txPr = paragraf
        sumbu.graphicalProperties = GraphicalProperties()
        sumbu.graphicalProperties.line.solidFill = D_GARIS[2:]
        if sumbu.majorGridlines is not None:
            sumbu.majorGridlines.spPr = GraphicalProperties()
            sumbu.majorGridlines.spPr.line.solidFill = D_GARIS[2:]


def _tulis_data_grafik(ws, data):
    """Tulis sumber data grafik di kolom tersembunyi, kembalikan rentangnya."""
    kol = KOL_DATA

    # Arus kas: paling banyak 12 bulan terakhir supaya grafik tetap terbaca.
    bulanan = list(data.bulanan)[-12:]
    ws.cell(row=1, column=kol, value="Bulan")
    ws.cell(row=1, column=kol + 1, value="Pemasukan")
    ws.cell(row=1, column=kol + 2, value="Pengeluaran")
    ws.cell(row=1, column=kol + 3, value="Saldo")
    for i, b in enumerate(bulanan, start=2):
        ws.cell(row=i, column=kol, value=format_month_id(b.bulan))
        ws.cell(row=i, column=kol + 1, value=_rp(b.pemasukan))
        ws.cell(row=i, column=kol + 2, value=_rp(b.pengeluaran))
        ws.cell(row=i, column=kol + 3, value=_rp(b.saldo_akhir))
    akhir_bulanan = 1 + len(bulanan)

    # Komposisi pengeluaran: enam kategori terbesar, sisanya digabung.
    total_per_kategori: dict = {}
    for t in data.pengeluaran:
        nama = t.category.name if t.category else "Lain-lain"
        total_per_kategori[nama] = total_per_kategori.get(
            nama, Decimal("0")
        ) + Decimal(str(t.amount))

    urut = sorted(total_per_kategori.items(), key=lambda x: x[1], reverse=True)
    teratas = urut[:5]
    sisa = sum((n for _, n in urut[5:]), Decimal("0"))
    if sisa > 0:
        teratas.append(("Lainnya", sisa))

    awal_kategori = 20
    ws.cell(row=awal_kategori, column=kol, value="Kategori")
    ws.cell(row=awal_kategori, column=kol + 1, value="Jumlah")
    for i, (nama, jumlah) in enumerate(teratas, start=awal_kategori + 1):
        ws.cell(row=i, column=kol, value=nama)
        ws.cell(row=i, column=kol + 1, value=_rp(jumlah))
    akhir_kategori = awal_kategori + len(teratas)

    for c in range(kol, kol + 4):
        ws.column_dimensions[get_column_letter(c)].hidden = True

    return bulanan, akhir_bulanan, teratas, awal_kategori, akhir_kategori


def _grafik_arus_kas(ws, akhir_bulanan):
    """Batang pemasukan/pengeluaran dengan garis saldo di atasnya."""
    kol = KOL_DATA
    batang = BarChart()
    batang.type = "col"
    batang.grouping = "clustered"
    batang.gapWidth = 60
    batang.add_data(
        Reference(ws, min_col=kol + 1, max_col=kol + 2, min_row=1, max_row=akhir_bulanan),
        titles_from_data=True,
    )
    batang.set_categories(
        Reference(ws, min_col=kol, min_row=2, max_row=akhir_bulanan)
    )
    batang.series[0].graphicalProperties.solidFill = D_HIJAU[2:]
    batang.series[0].graphicalProperties.line.noFill = True
    batang.series[1].graphicalProperties.solidFill = D_MERAH[2:]
    batang.series[1].graphicalProperties.line.noFill = True

    garis = LineChart()
    garis.add_data(
        Reference(ws, min_col=kol + 3, min_row=1, max_row=akhir_bulanan),
        titles_from_data=True,
    )
    garis.series[0].graphicalProperties.line.solidFill = D_SIAN[2:]
    garis.series[0].graphicalProperties.line.width = 22000
    garis.series[0].smooth = False
    garis.y_axis.axId = 200

    batang.y_axis.majorGridlines = ChartLines()
    batang.y_axis.numFmt = '#,##0'
    batang += garis

    # Data sumber ada di kolom tersembunyi. Secara bawaan Excel hanya
    # memplot sel yang terlihat, sehingga grafiknya tampil kosong.
    batang.visible_cells_only = False
    garis.visible_cells_only = False

    _gaya_grafik_gelap(batang)
    batang.height = 8.2
    batang.width = 17.5
    batang.legend.position = "t"
    batang.legend.overlay = False
    return batang


def _grafik_komposisi(ws, awal_kategori, akhir_kategori):
    """Donat komposisi pengeluaran per kategori."""
    kol = KOL_DATA
    donat = DoughnutChart(holeSize=55)
    donat.add_data(
        Reference(
            ws, min_col=kol + 1, min_row=awal_kategori, max_row=akhir_kategori
        ),
        titles_from_data=True,
    )
    donat.set_categories(
        Reference(
            ws, min_col=kol, min_row=awal_kategori + 1, max_row=akhir_kategori
        )
    )
    warna = [D_BIRU, D_SIAN, D_KUNING, D_HIJAU, D_MERAH, "FF8B5CF6", D_REDUP]
    for i, titik in enumerate(donat.series[0].data_points or []):
        titik.graphicalProperties.solidFill = warna[i % len(warna)][2:]
        titik.graphicalProperties.line.solidFill = D_PANEL[2:]

    donat.dataLabels = DataLabelList()
    donat.dataLabels.showPercent = True
    donat.dataLabels.showVal = False
    donat.dataLabels.showSerName = False
    donat.dataLabels.showCatName = False

    donat.visible_cells_only = False

    _gaya_grafik_gelap(donat)
    donat.height = 8.2
    donat.width = 9.0
    donat.legend.position = "b"
    donat.legend.overlay = False
    return donat


def _panel_kategori(ws, r1, c1, r2, c2, teratas, total_pengeluaran):
    """Daftar kategori dengan nilai dan bilah persentase.

    Kolom ditetapkan satu per satu, bukan dihitung dari c1, karena kisi
    dashboard menyelipkan kolom pemisah sempit di antaranya. Nilai yang
    jatuh di kolom pemisah akan tampil sebagai "###".
    """
    _panel(ws, r1, c1, r2, c2, "Pengeluaran per Kategori")
    KOL_NAMA, KOL_NILAI, KOL_PERSEN, KOL_BAR = 2, 4, 6, 7

    baris = r1 + 1
    for nama, jumlah in teratas:
        if baris > r2:
            break
        sel_nama = _isi_blok(ws, baris, KOL_NAMA, baris, KOL_NAMA + 1, D_PANEL)
        sel_nama.value = nama
        sel_nama.font = Font(size=10, color=D_TEKS)
        sel_nama.alignment = Alignment(horizontal="left", vertical="center", indent=1)

        # Format rapat, bukan akuntansi: format akuntansi mendorong "Rp"
        # ke tepi kiri sel, sehingga angka tujuh digit tidak lagi muat dan
        # Excel menggantinya dengan "###".
        sel_nilai = _isi_blok(ws, baris, KOL_NILAI, baris, KOL_NILAI + 1, D_PANEL)
        sel_nilai.value = _rp(jumlah)
        sel_nilai.number_format = FORMAT_RUPIAH_RAPAT
        sel_nilai.font = Font(size=10, color=D_TEKS)
        sel_nilai.alignment = Alignment(horizontal="right", vertical="center")

        bagian = (
            float(Decimal(str(jumlah)) / total_pengeluaran)
            if total_pengeluaran
            else 0.0
        )
        sel_persen = ws.cell(row=baris, column=KOL_PERSEN, value=bagian)
        sel_persen.number_format = "0%"
        sel_persen.font = Font(size=10, color=D_REDUP)
        sel_persen.alignment = Alignment(horizontal="right", vertical="center")

        # Bilah dibuat dari karakter blok, bukan data bar bawaan Excel:
        # data bar memakai warna latar yang nyaris tak terlihat di tema
        # gelap, sedangkan warna karakter bisa diatur langsung.
        sel_bar = _isi_blok(ws, baris, KOL_BAR, baris, c2, D_PANEL)
        sel_bar.value = "\u2588" * max(1, round(bagian * 12)) if bagian > 0 else ""
        sel_bar.font = Font(size=10, color=D_SIAN)
        sel_bar.alignment = Alignment(horizontal="left", vertical="center")

        ws.row_dimensions[baris].height = 16
        baris += 1

    if not teratas:
        sel = _isi_blok(ws, r1 + 1, c1, r1 + 1, c2, D_PANEL)
        sel.value = "Belum ada pengeluaran tercatat."
        sel.font = Font(size=10, italic=True, color=D_REDUP)
        sel.alignment = Alignment(horizontal="left", vertical="center", indent=1)


def _panel_transaksi_terakhir(ws, r1, c1, r2, c2, transaksi):
    """Transaksi terbaru, terbaru di atas. Kolom eksplisit, lihat catatan
    pada _panel_kategori."""
    _panel(ws, r1, c1, r2, c2, "Transaksi Terakhir")
    KOL_TGL, KOL_KET, KOL_KAT, KOL_JML = 10, 11, 14, 16

    kepala = ((KOL_TGL, "Tanggal"), (KOL_KET, "Keterangan"),
              (KOL_KAT, "Kategori"), (KOL_JML, "Jumlah"))
    for kol, teks in kepala:
        sel = ws.cell(row=r1 + 1, column=kol, value=teks)
        sel.font = Font(size=9, bold=True, color=D_REDUP)
        sel.alignment = Alignment(
            horizontal="right" if kol == KOL_JML else "left",
            vertical="center",
            indent=0 if kol == KOL_JML else 1,
        )
    ws.row_dimensions[r1 + 1].height = 15

    terbaru = sorted(
        transaksi,
        key=lambda t: (t.transaction_date, t.id or 0),
        reverse=True,
    )[: r2 - r1 - 1]

    baris = r1 + 2
    for t in terbaru:
        masuk = t.transaction_type.value == "income"

        sel_tgl = ws.cell(row=baris, column=KOL_TGL, value=t.transaction_date)
        sel_tgl.number_format = FORMAT_TANGGAL
        sel_tgl.font = Font(size=9, color=D_REDUP)
        sel_tgl.alignment = Alignment(horizontal="left", vertical="center", indent=1)

        sel_ket = _isi_blok(ws, baris, KOL_KET, baris, KOL_KAT - 1, D_PANEL)
        sel_ket.value = t.description or "-"
        sel_ket.font = Font(size=9, color=D_TEKS)
        sel_ket.alignment = Alignment(horizontal="left", vertical="center")

        sel_kat = _isi_blok(ws, baris, KOL_KAT, baris, KOL_JML - 1, D_PANEL)
        sel_kat.value = t.category.name if t.category else "-"
        sel_kat.font = Font(size=9, color=D_REDUP)
        sel_kat.alignment = Alignment(horizontal="left", vertical="center")

        nilai = _rp(t.amount)
        sel_jml = ws.cell(row=baris, column=KOL_JML, value=nilai if masuk else -nilai)
        sel_jml.number_format = FORMAT_RUPIAH
        sel_jml.font = Font(size=9, bold=True, color=D_HIJAU if masuk else D_MERAH)

        ws.row_dimensions[baris].height = 15
        baris += 1

    if not terbaru:
        sel = _isi_blok(ws, r1 + 2, c1, r1 + 2, c2, D_PANEL)
        sel.value = "Belum ada transaksi."
        sel.font = Font(size=10, italic=True, color=D_REDUP)
        sel.alignment = Alignment(horizontal="left", vertical="center", indent=1)


def _strip_bulan_ini(ws, baris, b):
    """Satu baris berisi empat angka bulan berjalan, nilainya utuh.

    Catatan di kartu KPI sengaja diringkas ("Rp450 rb") agar muat; angka
    pastinya ada di sini, supaya dashboard tetap bisa dipakai sebagai
    laporan dan bukan sekadar gambaran kasar.
    """
    _warnai(ws, baris, 2, baris + 1, 16, D_PANEL)

    sel = _isi_blok(ws, baris, 2, baris, 16, D_PANEL)
    sel.value = f"Bulan Ini — {format_month_id(b.mulai)}"
    sel.font = Font(bold=True, size=11, color=D_SIAN)
    sel.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    for c in range(2, 17):
        ws.cell(row=baris, column=c).border = Border(
            bottom=Side(style="thin", color=D_GARIS)
        )
    ws.row_dimensions[baris].height = 20

    # Label menempati satu kolom, nilainya dua kolom yang digabung. Nilai
    # Rupiah penuh butuh ruang; ditaruh di satu kolom sempit, Excel
    # menggantinya dengan "###" dan angkanya hilang dari pandangan.
    isi = [
        (2, "Pemasukan", _rp(b.pemasukan), FORMAT_RUPIAH_RAPAT, D_HIJAU),
        (6, "Pengeluaran", _rp(b.pengeluaran), FORMAT_RUPIAH_RAPAT, D_MERAH),
        (10, "Selisih", _rp(b.selisih), FORMAT_RUPIAH_RAPAT, D_SIAN),
        (14, "Transaksi", b.jumlah_transaksi, "#,##0", D_KUNING),
    ]
    for kol, label, nilai, format_angka, warna in isi:
        sel_label = ws.cell(row=baris + 1, column=kol, value=label)
        sel_label.font = Font(size=9, color=D_REDUP)
        sel_label.alignment = Alignment(horizontal="left", vertical="center", indent=1)

        sel_nilai = _isi_blok(ws, baris + 1, kol + 1, baris + 1, kol + 2, D_PANEL)
        sel_nilai.value = nilai
        sel_nilai.number_format = format_angka
        sel_nilai.font = Font(bold=True, size=10, color=warna)
        sel_nilai.alignment = Alignment(horizontal="right", vertical="center")

    ws.row_dimensions[baris + 1].height = 18


def _sheet_dashboard(ws: Worksheet, data: DataLaporan) -> None:
    """Sheet 1 — dashboard bertema gelap dengan grafik.

    Tata letaknya memakai kisi kolom sempit: kartu dan panel dibentuk dari
    beberapa kolom yang digabung, bukan dari satu sel lebar. Itu satu-satunya
    cara menyusun blok berdampingan di Excel.
    """
    s = data.saldo
    b = data.bulan_ini

    ws.sheet_view.showGridLines = False
    ws.sheet_properties.tabColor = D_LATAR[2:]

    # Dashboard lebih lebar dari kertas potret. Tanpa pengaturan ini,
    # mencetak atau mengekspor ke PDF memotongnya di tengah — separuh
    # panel kanan hilang tanpa peringatan.
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_area = "A1:Q44"

    KOL_AWAL, KOL_AKHIR = 2, 16  # B sampai P
    SELA = (5, 9, 13)  # E, I, M — pemisah antar-kartu

    ws.column_dimensions["A"].width = 2
    ws.column_dimensions["Q"].width = 2
    for c in range(KOL_AWAL, KOL_AKHIR + 1):
        ws.column_dimensions[get_column_letter(c)].width = 1.6 if c in SELA else 11

    # Latar seluruh kanvas lebih dulu, supaya tidak ada petak putih tersisa
    # di sela antar-panel.
    for r in range(1, 46):
        for c in range(1, 18):
            ws.cell(row=r, column=c).fill = PatternFill("solid", fgColor=D_LATAR)

    bulanan, akhir_bulanan, teratas, awal_kat, akhir_kat = _tulis_data_grafik(ws, data)

    # ── Judul ──────────────────────────────────────────────────────
    ws.row_dimensions[1].height = 8
    sel = _isi_blok(ws, 2, KOL_AWAL, 2, KOL_AKHIR, D_LATAR)
    sel.value = "ZOI FINANCE AI — DASHBOARD KEUANGAN"
    sel.font = Font(bold=True, size=18, color=D_SIAN)
    sel.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[2].height = 28

    sel = _isi_blok(ws, 3, KOL_AWAL, 3, KOL_AKHIR, D_LATAR)
    sel.value = (
        f"Periode: {format_month_id(b.mulai)}   |   "
        f"Dibuat: {datetime.now(JAKARTA).strftime('%d %b %Y %H:%M')} WIB   |   "
        f"Mata uang: {data.mata_uang}   |   Zona waktu: {data.zona_waktu}"
    )
    sel.font = Font(size=9, color=D_REDUP)
    sel.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[3].height = 15
    ws.row_dimensions[4].height = 6

    # ── Empat kartu KPI ────────────────────────────────────────────
    _kartu_kpi(
        ws, 5, 2, "PEMASUKAN", _rp(s.total_pemasukan),
        f"Bulan ini: {_rupiah_singkat(b.pemasukan)}", D_HIJAU, FORMAT_RUPIAH_RAPAT,
    )
    _kartu_kpi(
        ws, 5, 6, "PENGELUARAN", _rp(s.total_pengeluaran),
        f"Bulan ini: {_rupiah_singkat(b.pengeluaran)}", D_MERAH, FORMAT_RUPIAH_RAPAT,
    )
    _kartu_kpi(
        ws, 5, 10, "SALDO SAAT INI", _rp(s.saldo_sekarang),
        f"Saldo awal: {_rupiah_singkat(s.saldo_awal)}", D_BIRU, FORMAT_RUPIAH_RAPAT,
    )
    _kartu_kpi(
        ws, 5, 14, "TRANSAKSI", s.jumlah_transaksi,
        f"Bulan ini: {b.jumlah_transaksi} transaksi", D_KUNING, "#,##0",
    )
    ws.row_dimensions[8].height = 6

    # ── Angka bulan berjalan ───────────────────────────────────────
    _strip_bulan_ini(ws, 9, b)
    ws.row_dimensions[11].height = 6

    # ── Grafik ─────────────────────────────────────────────────────
    _panel(ws, 12, 2, 29, 10, "Arus Kas Bulanan")
    _panel(ws, 12, 12, 29, 16, "Komposisi Pengeluaran")

    if bulanan:
        ws.add_chart(_grafik_arus_kas(ws, akhir_bulanan), "B13")
    else:
        sel = _isi_blok(ws, 14, 2, 14, 10, D_PANEL)
        sel.value = "Belum ada data bulanan."
        sel.font = Font(size=10, italic=True, color=D_REDUP)
        sel.alignment = Alignment(horizontal="center", vertical="center")

    if teratas:
        ws.add_chart(_grafik_komposisi(ws, awal_kat, akhir_kat), "L13")
    else:
        sel = _isi_blok(ws, 14, 12, 14, 16, D_PANEL)
        sel.value = "Belum ada pengeluaran."
        sel.font = Font(size=10, italic=True, color=D_REDUP)
        sel.alignment = Alignment(horizontal="center", vertical="center")

    ws.row_dimensions[30].height = 6

    # ── Dua panel bawah ────────────────────────────────────────────
    _panel_kategori(ws, 31, 2, 41, 8, teratas, s.total_pengeluaran)
    _panel_transaksi_terakhir(ws, 31, 10, 41, 16, data.semua_transaksi)

    ws.row_dimensions[42].height = 6
    sel = _isi_blok(ws, 43, 2, 43, 16, D_LATAR)
    sel.value = "ZOI FINANCE AI  ·  Smart Finance. Simple Control."
    sel.font = Font(size=9, italic=True, color=D_GARIS)
    sel.alignment = Alignment(horizontal="center", vertical="center")


def _rupiah_singkat(nilai) -> str:
    """Rupiah ringkas untuk baris catatan kartu: 1,2 jt / 450 rb."""
    n = Decimal(str(nilai))
    if n >= 1_000_000_000:
        return f"Rp{n / 1_000_000_000:.1f} M".replace(".", ",")
    if n >= 1_000_000:
        return f"Rp{n / 1_000_000:.1f} jt".replace(".", ",")
    if n >= 1_000:
        return f"Rp{n / 1_000:.0f} rb"
    return f"Rp{n:.0f}"


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
