"""Uji perlindungan data sebelum teks dikirim ke provider AI.

Aturan ZOI bagian 15: jangan pernah mengirim kunci API, password, PIN, atau
kredensial bank ke provider AI.
"""

from __future__ import annotations

import pytest

from app.ai.scrub import periksa
from app.utils.sanitizer import mask, sanitize_dict, sanitize_exception, sanitize_text, sanitize_url


class TestTolakKredensial:
    @pytest.mark.parametrize(
        "teks",
        [
            "pin atm saya 123456",
            "password rekening abc123",
            "kode otp 884421",
            "cvv 123 kartu saya",
            "sandi internet banking rahasia",
            "api key sk-or-v1-abcdefgh12345678",
            "AIzaSyAbCdEfGhIjKlMnOpQrSt",
        ],
    )
    def test_pesan_berisi_kredensial_ditolak(self, teks):
        aman, alasan, bersih = periksa(teks)
        assert aman is False
        assert alasan
        assert bersih == ""

    @pytest.mark.parametrize(
        "teks",
        [
            "bayar pinjaman 500rb",      # "pin" di dalam "pinjaman" bukan PIN
            "beli pisang 10rb",
            "bayar cicilan motor 1 juta",
            "beli bensin 30rb",
        ],
    )
    def test_kata_mirip_tidak_ikut_tertolak(self, teks):
        aman, _, _ = periksa(teks)
        assert aman is True


class TestRedaksiNomor:
    def test_nomor_panjang_diredaksi(self):
        aman, _, bersih = periksa("transfer ke 1234567890123456 sebesar 50rb")
        assert aman is True
        assert "1234567890123456" not in bersih
        assert "[nomor]" in bersih
        assert "50rb" in bersih  # jumlah tetap bisa diparsing

    def test_nomor_kartu_berspasi_diredaksi(self):
        _, _, bersih = periksa("kartu 4111 1111 1111 1111 kena charge 90rb")
        assert "4111" not in bersih
        assert "90rb" in bersih

    def test_jumlah_biasa_tidak_diredaksi(self):
        _, _, bersih = periksa("beli beras 150000")
        assert "150000" in bersih

    def test_spasi_tidak_hilang_setelah_redaksi(self):
        _, _, bersih = periksa("transfer ke 1234567890123456 sebesar 50rb")
        assert "[nomor] sebesar" in bersih


class TestSanitizerLog:
    def test_token_telegram_disamarkan(self):
        hasil = sanitize_text("gagal dengan token 8123456789:AAEhBOweik6ad9r_Q458mXFGnHbPMtPS")
        assert "AAEhBOweik6ad9r" not in hasil
        assert "8123456789:***" in hasil

    def test_kredensial_url_disamarkan(self):
        hasil = sanitize_url("postgresql+asyncpg://zoi:rahasia@pooler.supabase.com:5432/zoi")
        assert "rahasia" not in hasil
        assert "zoi:***@" in hasil

    def test_kunci_api_disamarkan(self):
        assert "abcdefgh12345678" not in sanitize_text("key sk-or-v1-abcdefgh12345678")

    def test_dict_bersarang_disamarkan(self):
        hasil = sanitize_dict({
            "TELEGRAM_BOT_TOKEN": "8123456789:AAEabcdefghij",
            "nama": "Fariz",
            "nested": {"gemini_api_key": "AIzaSyAbCdEf123456"},
        })
        assert hasil["nama"] == "Fariz"
        assert "AAEabcdefghij" not in hasil["TELEGRAM_BOT_TOKEN"]
        assert "AIzaSyAbCdEf123456" not in hasil["nested"]["gemini_api_key"]

    def test_exception_disanitasi_dan_menyebut_tipenya(self):
        hasil = sanitize_exception(ValueError("gagal untuk postgresql://u:pw@h/db"))
        assert hasil.startswith("ValueError:")
        assert "pw" not in hasil

    def test_panjang_secret_tidak_bocor_lewat_panjang_topeng(self):
        pendek = mask("sk-" + "a" * 20)
        panjang = mask("sk-" + "a" * 200)
        assert len(pendek) == len(panjang)
