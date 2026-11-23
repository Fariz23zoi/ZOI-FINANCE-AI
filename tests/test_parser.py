"""Uji pra-parser bahasa Indonesia (tingkat AI pertama, biaya Rp0)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.ai.parser import parse
from app.database.models import TransactionType

HARI_INI = date(2026, 11, 23)


class TestContohSpesifikasi:
    """Setiap contoh yang disebut langsung di spesifikasi ZOI."""

    def test_contoh_utama(self):
        """"Bayar parkir motor 2 ribu di pasar Ciamis" — contoh di bagian 2."""
        h = parse("Bayar parkir motor 2 ribu di pasar Ciamis", hari_ini=HARI_INI)
        assert h.transaction_type == TransactionType.EXPENSE
        assert h.amount == Decimal("2000.00")
        assert h.category == "Transportasi"
        assert h.description == "Bayar parkir motor"
        assert h.location == "Pasar Ciamis"
        assert h.transaction_date == HARI_INI
        assert h.lengkap

    @pytest.mark.parametrize(
        "teks,jenis,jumlah",
        [
            ("Bayar parkir motor 2 ribu", TransactionType.EXPENSE, "2000"),
            ("Beli bensin 30rb", TransactionType.EXPENSE, "30000"),
            ("Kemarin beli pulsa 25 ribu", TransactionType.EXPENSE, "25000"),
            ("Beli beras 150 ribu", TransactionType.EXPENSE, "150000"),
            ("Dapat uang tambahan 500 ribu", TransactionType.INCOME, "500000"),
            ("Pemasukan dari hasil penjualan 750 ribu", TransactionType.INCOME, "750000"),
            ("Bayar listrik 200 ribu", TransactionType.EXPENSE, "200000"),
            ("Beli makan siang 15 ribu", TransactionType.EXPENSE, "15000"),
        ],
    )
    def test_delapan_contoh_bagian_9(self, teks, jenis, jumlah):
        h = parse(teks, hari_ini=HARI_INI)
        assert h.transaction_type == jenis
        assert h.amount == Decimal(jumlah).quantize(Decimal("0.01"))
        assert h.lengkap


class TestJenisTransaksi:
    def test_kata_kerja_terdepan_menentukan(self):
        """"bayar utang" adalah pengeluaran, meski memuat kata "utang"."""
        h = parse("bayar utang 500rb", hari_ini=HARI_INI)
        assert h.transaction_type == TransactionType.EXPENSE

    def test_pemasukan_dikenali(self):
        for teks in ["gajian 7 juta", "terima komisi 300rb", "dapat bonus 1 juta"]:
            assert parse(teks, hari_ini=HARI_INI).transaction_type == TransactionType.INCOME

    def test_tanpa_kata_kerja_default_pengeluaran_tapi_ditandai(self):
        """Tebakan lemah harus tercatat di `kurang` agar bisa ditandai ke pengguna."""
        h = parse("keperluan mendadak 45 ribu", hari_ini=HARI_INI)
        assert h.transaction_type == TransactionType.EXPENSE
        assert "transaction_type" in h.kurang


class TestKategori:
    @pytest.mark.parametrize(
        "teks,kategori",
        [
            ("beli nasi goreng 20rb", "Makanan & Minuman"),
            ("isi bensin 50rb", "Transportasi"),
            ("bayar parkir 2rb", "Transportasi"),
            ("beli beras 150rb", "Belanja Harian"),
            ("bayar listrik 200rb", "Tagihan & Utilitas"),
            ("beli obat 35rb", "Kesehatan"),
            ("isi pulsa 25rb", "Komunikasi & Pulsa"),
            ("nonton bioskop 50rb", "Hiburan"),
            ("gajian 7 juta", "Gaji"),
            ("hasil penjualan 750rb", "Penjualan"),
        ],
    )
    def test_petunjuk_kategori(self, teks, kategori):
        assert parse(teks, hari_ini=HARI_INI).category == kategori

    def test_kategori_pemasukan_tidak_dipakai_untuk_pengeluaran(self):
        """"jual" tidak boleh menjadi kategori pengeluaran."""
        h = parse("beli barang jualan 100rb", hari_ini=HARI_INI)
        assert h.transaction_type == TransactionType.EXPENSE
        assert h.category != "Penjualan"


class TestLokasi:
    @pytest.mark.parametrize(
        "teks,lokasi",
        [
            ("bayar parkir 2 ribu di pasar Ciamis", "Pasar Ciamis"),
            ("beli obat di apotek kimia farma 35 ribu", "Apotek Kimia Farma"),
            ("makan di warung bu ani 20rb", "Warung Bu Ani"),
            ("jajan di kantin 5k", "Kantin"),
            ("bayar di indomaret 55.000", "Indomaret"),
        ],
    )
    def test_lokasi_tidak_menelan_jumlah(self, teks, lokasi):
        """Pola lokasi berjalan pada teks yang masih memuat jumlah."""
        assert parse(teks, hari_ini=HARI_INI).location == lokasi

    def test_kata_generik_bukan_lokasi(self):
        assert parse("beli sayur di pasar 20rb", hari_ini=HARI_INI).location is None


class TestTanggal:
    def test_tanpa_tanggal_pakai_hari_ini(self):
        assert parse("beli bensin 30rb", hari_ini=HARI_INI).transaction_date == HARI_INI

    def test_kemarin(self):
        h = parse("kemarin beli pulsa 25 ribu", hari_ini=HARI_INI)
        assert h.transaction_date == date(2026, 11, 22)


class TestKetahanan:
    @pytest.mark.parametrize("teks", ["", "   ", "halo", "apa kabar"])
    def test_tidak_pernah_melempar_exception(self, teks):
        h = parse(teks, hari_ini=HARI_INI)
        assert not h.lengkap
        assert "amount" in h.kurang

    def test_tidak_mengarang_jumlah(self):
        """Tanpa angka, amount harus None — bukan nol atau tebakan."""
        assert parse("beli sesuatu", hari_ini=HARI_INI).amount is None


class TestSerialisasi:
    def test_bolak_balik_json_mempertahankan_decimal(self):
        """Uang disimpan ke JSONB sebagai string, bukan float."""
        from app.ai.schema import ParsedTransaction

        asli = parse("Bayar parkir motor 2 ribu di pasar Ciamis", hari_ini=HARI_INI)
        data = asli.to_json()

        assert isinstance(data["amount"], str)

        kembali = ParsedTransaction.from_json(data)
        assert kembali.amount == asli.amount
        assert isinstance(kembali.amount, Decimal)
        assert kembali.transaction_type == asli.transaction_type
        assert kembali.transaction_date == asli.transaction_date
        assert kembali.location == asli.location
