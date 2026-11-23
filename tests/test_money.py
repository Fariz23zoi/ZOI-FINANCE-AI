"""Uji penanganan uang: Decimal, format Rupiah, dan parsing satuan Indonesia."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.utils.money import format_rupiah, parse_indonesian_amount, to_decimal


class TestToDecimal:
    def test_float_tidak_mewarisi_galat_biner(self):
        """Decimal(str(0.1)) tepat 0.1, Decimal(0.1) tidak."""
        assert to_decimal(0.1) == Decimal("0.10")
        assert to_decimal(2000.0) == Decimal("2000.00")

    def test_selalu_dua_desimal(self):
        assert to_decimal("2000").as_tuple().exponent == -2
        assert to_decimal(Decimal("1.005")) == Decimal("1.01")  # ROUND_HALF_UP

    @pytest.mark.parametrize("buruk", ["abc", "", None, "nan", "inf", "1.2.3"])
    def test_tolak_nilai_bukan_uang(self, buruk):
        with pytest.raises(ValueError):
            to_decimal(buruk)


class TestFormatRupiah:
    @pytest.mark.parametrize(
        "nilai,harapan",
        [
            ("0", "Rp0"),
            ("2000", "Rp2.000"),
            ("25000", "Rp25.000"),
            ("500000", "Rp500.000"),
            ("1000000", "Rp1.000.000"),
            ("1500000.50", "Rp1.500.000,50"),
            ("-2000", "-Rp2.000"),
            ("999999999999.99", "Rp999.999.999.999,99"),
        ],
    )
    def test_format(self, nilai, harapan):
        assert format_rupiah(Decimal(nilai)) == harapan


class TestParseJumlahIndonesia:
    @pytest.mark.parametrize(
        "teks,harapan",
        [
            # Contoh yang disebut langsung di spesifikasi ZOI.
            ("Bayar parkir motor 2 ribu", "2000"),
            ("Beli bensin 30rb", "30000"),
            ("Kemarin beli pulsa 25 ribu", "25000"),
            ("Beli beras 150 ribu", "150000"),
            ("Dapat uang tambahan 500 ribu", "500000"),
            ("Pemasukan dari hasil penjualan 750 ribu", "750000"),
            ("Bayar listrik 200 ribu", "200000"),
            ("Beli makan siang 15 ribu", "15000"),
            ("1 juta", "1000000"),
            ("1,5 juta", "1500000"),
            ("500.000", "500000"),
            # Variasi lain yang lazim dipakai.
            ("2jt", "2000000"),
            ("12k", "12000"),
            ("7.500.000", "7500000"),
            ("1.250.500", "1250500"),
            ("2000", "2000"),
            ("1.5 juta", "1500000"),
        ],
    )
    def test_satuan_dan_pemisah(self, teks, harapan):
        assert parse_indonesian_amount(teks) == Decimal(harapan).quantize(Decimal("0.01"))

    @pytest.mark.parametrize("teks", ["tidak ada angka", "", "beli sayur di pasar"])
    def test_tanpa_angka_kembalikan_none(self, teks):
        assert parse_indonesian_amount(teks) is None

    def test_nol_ditolak(self):
        """Nol bukan jumlah transaksi yang bermakna."""
        assert parse_indonesian_amount("0") is None

    def test_titik_sebagai_ribuan_vs_desimal(self):
        """Aturan pembeda: titik = ribuan bila diikuti tepat 3 angka tanpa pengali."""
        assert parse_indonesian_amount("500.000") == Decimal("500000.00")
        assert parse_indonesian_amount("1.5 juta") == Decimal("1500000.00")
