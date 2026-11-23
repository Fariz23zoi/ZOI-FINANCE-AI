"""Uji laporan Excel: lima sheet, total benar, format Rupiah, dan konsistensi
dengan isi database."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from openpyxl import load_workbook

from app.database.models import TransactionType
from app.excel import generator
from app.services import report_service
from app.services import transaction_service as ts
from app.services.permission_service import PermissionDenied

HARI_INI = date(2026, 11, 23)

SHEET_WAJIB = ["DASHBOARD", "TRANSAKSI", "PEMASUKAN", "PENGELUARAN", "REKAP BULANAN"]


async def _isi_data(session, admin, member):
    """Data uji yang menjangkau dua bulan dan dua pencatat."""
    data = [
        (admin, TransactionType.EXPENSE, "2000", "Transportasi", HARI_INI, "Bayar parkir motor", "Pasar Ciamis"),
        (member, TransactionType.EXPENSE, "30000", "Transportasi", HARI_INI, "Beli bensin", None),
        (member, TransactionType.EXPENSE, "150000", "Belanja Harian", date(2026, 11, 22), "Beli beras", None),
        (admin, TransactionType.INCOME, "750000", "Penjualan", date(2026, 11, 20), "Hasil penjualan", None),
        (admin, TransactionType.INCOME, "7500000", "Gaji", date(2026, 10, 28), "Gaji bulanan", None),
        (member, TransactionType.EXPENSE, "200000", "Tagihan & Utilitas", date(2026, 10, 15), "Bayar listrik", None),
    ]
    for oleh, jenis, jml, kat, tgl, ket, lok in data:
        await ts.simpan_langsung(
            session, user=oleh, transaction_type=jenis, amount=Decimal(jml),
            kategori_nama=kat, transaction_date=tgl, description=ket, location=lok,
        )
    await session.commit()


@pytest.fixture
async def workbook(seeded, tmp_path):
    s, admin, member = seeded["session"], seeded["admin"], seeded["member"]
    await _isi_data(s, admin, member)

    data = await report_service.kumpulkan(s, user=admin)
    path = generator.simpan(data, direktori=str(tmp_path))
    return load_workbook(path), data, path


class TestStruktur:
    async def test_lima_sheet_dengan_nama_yang_benar(self, workbook):
        wb, _, _ = workbook
        assert wb.sheetnames == SHEET_WAJIB

    async def test_header_dibekukan_dan_filter_dipasang(self, workbook):
        wb, _, _ = workbook
        ws = wb["TRANSAKSI"]
        assert ws.freeze_panes == "A4"
        assert ws.auto_filter.ref is not None

    async def test_lebar_kolom_diatur(self, workbook):
        wb, _, _ = workbook
        ws = wb["TRANSAKSI"]
        assert ws.column_dimensions["D"].width >= 20  # Keterangan

    async def test_file_bisa_dibuka_ulang(self, workbook):
        """Sanity: file valid dan tidak korup."""
        _, _, path = workbook
        assert path.exists()
        assert path.stat().st_size > 5000
        load_workbook(path)


class TestDashboard:
    """Dashboard bertema gelap: kartu KPI, strip bulan ini, grafik.

    Tata letaknya kisi kolom, bukan pasangan label/nilai berurutan, jadi
    pengujian menunjuk sel tertentu. Yang diuji tetap sama: angka di layar
    harus sama dengan angka di database, bukan hasil hitung ulang Excel.
    """

    #: Kolom kiri tiap kartu KPI; nilainya ada di baris ke-2 kartu (baris 6).
    KOLOM_KARTU = {"pemasukan": 2, "pengeluaran": 6, "saldo": 10, "transaksi": 14}
    BARIS_NILAI_KARTU = 6

    async def test_angka_kartu_cocok_dengan_database(self, workbook):
        wb, data, _ = workbook
        ws = wb["DASHBOARD"]
        b = self.BARIS_NILAI_KARTU
        k = self.KOLOM_KARTU

        assert ws.cell(row=b, column=k["pemasukan"]).value == float(
            data.saldo.total_pemasukan
        )
        assert ws.cell(row=b, column=k["pengeluaran"]).value == float(
            data.saldo.total_pengeluaran
        )
        assert ws.cell(row=b, column=k["saldo"]).value == float(
            data.saldo.saldo_sekarang
        )
        assert ws.cell(row=b, column=k["transaksi"]).value == data.saldo.jumlah_transaksi

    async def test_saldo_mengikuti_rumus(self, workbook):
        """saldo_awal + pemasukan − pengeluaran."""
        _, data, _ = workbook
        assert data.saldo.saldo_sekarang == (
            data.saldo.saldo_awal + data.saldo.total_pemasukan - data.saldo.total_pengeluaran
        )
        assert data.saldo.saldo_sekarang == Decimal("8868000.00")

    async def test_strip_bulan_ini_memuat_angka_utuh(self, workbook):
        """Catatan di kartu diringkas; strip ini harus tetap angka pasti."""
        wb, data, _ = workbook
        ws = wb["DASHBOARD"]
        b = data.bulan_ini

        label = [ws.cell(row=10, column=c).value for c in (2, 6, 10, 14)]
        # Judul strip sudah menyebut bulannya, jadi label tidak mengulang.
        assert label == ["Pemasukan", "Pengeluaran", "Selisih", "Transaksi"]
        assert "Bulan Ini" in ws.cell(row=9, column=2).value

        # Nilai digabung dua kolom, jangkarnya tepat di kanan labelnya.
        assert ws.cell(row=10, column=3).value == float(b.pemasukan)
        assert ws.cell(row=10, column=7).value == float(b.pengeluaran)
        assert ws.cell(row=10, column=11).value == float(b.selisih)
        assert ws.cell(row=10, column=15).value == b.jumlah_transaksi

    async def test_mata_uang_dan_zona_waktu_di_subjudul(self, workbook):
        wb, _, _ = workbook
        ws = wb["DASHBOARD"]
        subjudul = ws.cell(row=3, column=2).value
        assert "IDR" in subjudul
        assert "Asia/Jakarta" in subjudul

    async def test_format_rupiah_memakai_koma_sebagai_pemisah_ribuan(self, workbook):
        """Titik di format angka Excel berarti desimal, bukan ribuan.

        Menulis '#.##0' membuat 22500 tampil '22500,0'. Ini pernah terjadi.
        """
        wb, _, _ = workbook
        ws = wb["DASHBOARD"]
        for kolom in self.KOLOM_KARTU.values():
            format_sel = ws.cell(row=self.BARIS_NILAI_KARTU, column=kolom).number_format
            assert "#,##0" in format_sel
            assert "#.##0" not in format_sel

    async def test_grafik_terpasang(self, workbook):
        wb, _, _ = workbook
        ws = wb["DASHBOARD"]
        assert len(ws._charts) == 2

    async def test_kolom_data_grafik_disembunyikan(self, workbook):
        """Angka sumber grafik harus ada di sheet, tapi tidak mengganggu."""
        wb, _, _ = workbook
        ws = wb["DASHBOARD"]
        for huruf in ("U", "V", "W", "X"):
            assert ws.column_dimensions[huruf].hidden is True


class TestSheetTransaksi:
    async def test_sepuluh_kolom_sesuai_spesifikasi(self, workbook):
        wb, _, _ = workbook
        ws = wb["TRANSAKSI"]
        header = [ws.cell(row=3, column=c).value for c in range(1, 11)]
        assert header == [
            "No.", "Tanggal", "Jenis", "Keterangan", "Kategori", "Lokasi",
            "Pemasukan", "Pengeluaran", "Dicatat Oleh", "Dibuat Pada",
        ]

    async def test_jumlah_baris_sama_dengan_database(self, workbook):
        wb, data, _ = workbook
        ws = wb["TRANSAKSI"]
        baris_data = ws.max_row - 4  # judul, kosong, header, total
        assert baris_data == len(data.semua_transaksi) == 6

    async def test_pemasukan_dan_pengeluaran_di_kolom_berbeda(self, workbook):
        wb, _, _ = workbook
        ws = wb["TRANSAKSI"]
        for r in range(4, ws.max_row):
            masuk = ws.cell(row=r, column=7).value
            keluar = ws.cell(row=r, column=8).value
            # Tepat satu dari keduanya terisi.
            assert (masuk is None) != (keluar is None)

    async def test_nama_pencatat_tercatat(self, workbook):
        wb, _, _ = workbook
        ws = wb["TRANSAKSI"]
        nama = {ws.cell(row=r, column=9).value for r in range(4, ws.max_row)}
        assert nama == {"Admin Uji", "Member Uji"}

    async def test_lokasi_tercatat(self, workbook):
        wb, _, _ = workbook
        ws = wb["TRANSAKSI"]
        lokasi = {ws.cell(row=r, column=6).value for r in range(4, ws.max_row)}
        assert "Pasar Ciamis" in lokasi

    async def test_total_memakai_subtotal_bukan_angka_statis(self, workbook):
        """SUBTOTAL ikut menyesuaikan saat pengguna memakai filter."""
        wb, _, _ = workbook
        ws = wb["TRANSAKSI"]
        assert str(ws.cell(row=ws.max_row, column=7).value).startswith("=SUBTOTAL(109")
        assert str(ws.cell(row=ws.max_row, column=8).value).startswith("=SUBTOTAL(109")

    async def test_format_rupiah_pada_kolom_uang(self, workbook):
        wb, _, _ = workbook
        ws = wb["TRANSAKSI"]
        for kol in (7, 8):
            assert "Rp" in ws.cell(row=4, column=kol).number_format

    async def test_format_tanggal(self, workbook):
        wb, _, _ = workbook
        ws = wb["TRANSAKSI"]
        assert ws.cell(row=4, column=2).number_format == "DD/MM/YYYY"


class TestSheetTerpisah:
    async def test_sheet_pemasukan_hanya_pemasukan(self, workbook):
        wb, data, _ = workbook
        ws = wb["PEMASUKAN"]
        assert ws.max_row - 4 == len(data.pemasukan) == 2
        for r in range(4, ws.max_row):
            assert ws.cell(row=r, column=3).value == "Pemasukan"
            assert ws.cell(row=r, column=7).value is not None
            assert ws.cell(row=r, column=8).value is None

    async def test_sheet_pengeluaran_hanya_pengeluaran(self, workbook):
        wb, data, _ = workbook
        ws = wb["PENGELUARAN"]
        assert ws.max_row - 4 == len(data.pengeluaran) == 4
        for r in range(4, ws.max_row):
            assert ws.cell(row=r, column=3).value == "Pengeluaran"
            assert ws.cell(row=r, column=8).value is not None

    async def test_pemasukan_plus_pengeluaran_sama_dengan_total(self, workbook):
        _, data, _ = workbook
        assert len(data.pemasukan) + len(data.pengeluaran) == len(data.semua_transaksi)


class TestRekapBulanan:
    async def test_enam_kolom(self, workbook):
        wb, _, _ = workbook
        ws = wb["REKAP BULANAN"]
        header = [ws.cell(row=3, column=c).value for c in range(1, 7)]
        assert header == [
            "Bulan", "Total Pemasukan", "Total Pengeluaran", "Selisih",
            "Jumlah Transaksi", "Saldo Akhir",
        ]

    async def test_bulan_dalam_bahasa_indonesia_dan_tidak_bergeser(self, workbook):
        wb, _, _ = workbook
        ws = wb["REKAP BULANAN"]
        bulan = [ws.cell(row=r, column=1).value for r in range(4, ws.max_row)]
        assert bulan == ["Oktober 2026", "November 2026"]

    async def test_saldo_akhir_terakhir_sama_dengan_saldo_sekarang(self, workbook):
        _, data, _ = workbook
        assert data.bulanan[-1].saldo_akhir == data.saldo.saldo_sekarang

    async def test_baris_total_tidak_menjumlahkan_saldo_akhir(self, workbook):
        """Saldo akhir bersifat kumulatif; menjumlahkannya tidak bermakna."""
        wb, _, _ = workbook
        ws = wb["REKAP BULANAN"]
        rumus = str(ws.cell(row=ws.max_row, column=6).value)
        assert rumus.startswith("=F")
        assert "SUM" not in rumus


class TestHakAksesEkspor:
    async def test_member_bisa_ekspor_bila_diizinkan(self, seeded):
        s, admin, member = seeded["session"], seeded["admin"], seeded["member"]
        await _isi_data(s, admin, member)
        data = await report_service.kumpulkan(s, user=member)
        assert len(data.semua_transaksi) == 6

    async def test_member_ditolak_bila_ekspor_dimatikan(self, seeded):
        s, admin, member = seeded["session"], seeded["admin"], seeded["member"]
        await _isi_data(s, admin, member)

        from app.database.repositories import settings_repo

        await settings_repo.set_member_can_export(s, False)
        await s.commit()

        with pytest.raises(PermissionDenied):
            await report_service.kumpulkan(s, user=member)

    async def test_admin_tetap_bisa_ekspor_walau_dimatikan(self, seeded):
        s, admin, member = seeded["session"], seeded["admin"], seeded["member"]
        await _isi_data(s, admin, member)

        from app.database.repositories import settings_repo

        await settings_repo.set_member_can_export(s, False)
        await s.commit()

        data = await report_service.kumpulkan(s, user=admin)
        assert len(data.semua_transaksi) == 6


class TestTanpaData:
    async def test_workbook_tetap_terbentuk_saat_belum_ada_transaksi(self, seeded, tmp_path):
        """Jangan sampai /excel error hanya karena buku kas masih kosong."""
        s, admin = seeded["session"], seeded["admin"]
        data = await report_service.kumpulkan(s, user=admin)
        path = generator.simpan(data, direktori=str(tmp_path))

        wb = load_workbook(path)
        assert wb.sheetnames == SHEET_WAJIB
        assert wb["TRANSAKSI"].cell(row=4, column=7).value == 0


class TestTransaksiTerhapus:
    async def test_transaksi_terhapus_tidak_muncul_di_laporan(self, seeded, tmp_path):
        s, admin, member = seeded["session"], seeded["admin"], seeded["member"]
        await _isi_data(s, admin, member)

        from app.database.repositories import transaction_repo

        semua = await transaction_repo.list_all(s)
        await ts.hapus(s, user=admin, transaction_id=semua[0].id)
        await s.commit()

        data = await report_service.kumpulkan(s, user=admin)
        assert len(data.semua_transaksi) == 5

        wb = load_workbook(generator.simpan(data, direktori=str(tmp_path)))
        assert wb["TRANSAKSI"].max_row - 4 == 5
