"""Uji penanganan tanggal, termasuk jebakan zona waktu Asia/Jakarta."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.utils.dates import (
    JAKARTA,
    format_date_id,
    format_month_id,
    local_today,
    month_bounds,
    parse_indonesian_date,
    to_local,
)

HARI_INI = date(2026, 11, 23)


class TestParseTanggalIndonesia:
    @pytest.mark.parametrize(
        "teks,harapan",
        [
            ("hari ini", date(2026, 11, 23)),
            ("tadi pagi", date(2026, 11, 23)),
            ("sekarang", date(2026, 11, 23)),
            ("kemarin", date(2026, 11, 22)),
            ("kemaren", date(2026, 11, 22)),
            ("kemarin lusa", date(2026, 11, 21)),
            ("3 hari lalu", date(2026, 11, 20)),
            ("5 hari yang lalu", date(2026, 11, 18)),
            ("besok", date(2026, 11, 24)),
            ("lusa", date(2026, 11, 25)),
            ("2026-11-01", date(2026, 11, 1)),
            ("23 November 2026", date(2026, 11, 23)),
            ("15 okt", date(2026, 10, 15)),
            ("01/11/2026", date(2026, 11, 1)),
            ("12-11", date(2026, 11, 12)),
        ],
    )
    def test_bentuk_yang_dikenali(self, teks, harapan):
        assert parse_indonesian_date(teks, today=HARI_INI) == harapan

    def test_kemarin_di_dalam_kalimat(self):
        assert parse_indonesian_date(
            "kemarin beli pulsa 25 ribu", today=HARI_INI
        ) == date(2026, 11, 22)

    @pytest.mark.parametrize("teks", ["beli beras 150 ribu", "", "tidak ada tanggal"])
    def test_tanpa_tanggal_kembalikan_none(self, teks):
        assert parse_indonesian_date(teks, today=HARI_INI) is None

    def test_tanggal_tidak_sah_kembalikan_none(self):
        """31 Februari tidak ada — jangan melempar exception, kembalikan None."""
        assert parse_indonesian_date("31 Februari 2026", today=HARI_INI) is None

    def test_tidak_tertipu_jumlah(self):
        """Angka pada jumlah uang tidak boleh dibaca sebagai tanggal."""
        assert parse_indonesian_date("beli bensin 30rb", today=HARI_INI) is None


class TestZonaWaktu:
    def test_konversi_utc_ke_jakarta(self):
        """Jakarta UTC+7: 17:00 UTC adalah tengah malam hari berikutnya."""
        utc = datetime(2026, 11, 22, 17, 0, tzinfo=timezone.utc)
        lokal = to_local(utc, JAKARTA)
        assert lokal.date() == date(2026, 11, 23)
        assert lokal.hour == 0

    def test_datetime_naif_dianggap_utc(self):
        naif = datetime(2026, 11, 22, 17, 0)
        assert to_local(naif, JAKARTA).date() == date(2026, 11, 23)

    def test_dini_hari_jakarta_masih_hari_sebelumnya_di_utc(self):
        """Inilah alasan transaction_date memakai kalender Jakarta.

        Pukul 01:00 tanggal 23 di Jakarta = 18:00 tanggal 22 di UTC. Memakai
        tanggal UTC akan memasukkan transaksi dini hari ke hari yang salah.
        """
        jakarta = datetime(2026, 11, 23, 1, 0, tzinfo=JAKARTA)
        assert jakarta.astimezone(timezone.utc).date() == date(2026, 11, 22)
        assert jakarta.date() == date(2026, 11, 23)

    def test_local_today_memakai_zona_lokal(self):
        assert isinstance(local_today(JAKARTA), date)


class TestFormat:
    def test_format_tanggal(self):
        assert format_date_id(date(2026, 11, 23)) == "23 November 2026"
        assert format_date_id(date(2026, 1, 1)) == "1 Januari 2026"

    def test_format_bulan(self):
        assert format_month_id(date(2026, 11, 23)) == "November 2026"

    @pytest.mark.parametrize(
        "d,awal,akhir",
        [
            (date(2026, 11, 23), date(2026, 11, 1), date(2026, 11, 30)),
            (date(2026, 2, 15), date(2026, 2, 1), date(2026, 2, 28)),
            (date(2024, 2, 15), date(2024, 2, 1), date(2024, 2, 29)),  # kabisat
            (date(2026, 12, 31), date(2026, 12, 1), date(2026, 12, 31)),
        ],
    )
    def test_batas_bulan(self, d, awal, akhir):
        assert month_bounds(d) == (awal, akhir)
