"""Uji konfigurasi: normalisasi DATABASE_URL dan penjagaan zero-cost."""

from __future__ import annotations

import pytest

from app.ai.errors import AIConfigError
from app.ai.openrouter import pastikan_model_gratis
from app.config import (
    Settings,
    connect_args_untuk,
    normalize_database_url,
    pakai_transaction_pooler,
)


class TestNormalisasiDatabaseUrl:
    @pytest.mark.parametrize(
        "masuk,harapan",
        [
            # Bentuk yang diberikan Supabase (session pooler).
            (
                "postgresql://postgres.abcd:pw@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres?sslmode=require",
                "postgresql+asyncpg://postgres.abcd:pw@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres?ssl=require",
            ),
            # Direct connection Supabase.
            (
                "postgresql://postgres:pw@db.abcd.supabase.co:5432/postgres?sslmode=require",
                "postgresql+asyncpg://postgres:pw@db.abcd.supabase.co:5432/postgres?ssl=require",
            ),
            ("postgres://u:p@h:5432/d?sslmode=require", "postgresql+asyncpg://u:p@h:5432/d?ssl=require"),
            ("postgresql://u:p@h:5432/d", "postgresql+asyncpg://u:p@h:5432/d"),
            # Sudah benar, jangan diubah.
            ("postgresql+asyncpg://u:p@h/d?ssl=require", "postgresql+asyncpg://u:p@h/d?ssl=require"),
            # Parameter lain dipertahankan.
            (
                "postgres://u:p@h/d?sslmode=require&application_name=zoi",
                "postgresql+asyncpg://u:p@h/d?application_name=zoi&ssl=require",
            ),
            ("postgres://u:p@h/d?sslmode=disable", "postgresql+asyncpg://u:p@h/d"),
            ("postgres://u:p@h/d?sslmode=verify-full", "postgresql+asyncpg://u:p@h/d?ssl=verify-full"),
            ("postgres://u:p@h/d?sslmode=prefer", "postgresql+asyncpg://u:p@h/d?ssl=prefer"),
            # SQLite: triple slash tidak boleh runtuh.
            ("sqlite:///./zoi.db", "sqlite+aiosqlite:///./zoi.db"),
            ("sqlite+aiosqlite:///./zoi.db", "sqlite+aiosqlite:///./zoi.db"),
            ("sqlite+aiosqlite:///:memory:", "sqlite+aiosqlite:///:memory:"),
        ],
    )
    def test_normalisasi(self, masuk, harapan):
        assert normalize_database_url(masuk) == harapan

    def test_sslmode_dibuang_karena_asyncpg_menolaknya(self):
        """asyncpg tidak punya parameter sslmode; kegagalannya baru muncul
        saat koneksi pertama, bukan saat engine dibuat."""
        hasil = normalize_database_url("postgres://u:p@h/d?sslmode=require")
        assert "sslmode" not in hasil
        assert "ssl=require" in hasil

    def test_url_kosong(self):
        assert normalize_database_url("") == ""
        assert normalize_database_url(None) == ""


class TestPenjagaanZeroCost:
    @pytest.mark.parametrize(
        "model",
        ["openai/gpt-4o", "anthropic/claude-3-opus", "meta-llama/llama-3.3-70b-instruct", ""],
    )
    def test_model_berbayar_ditolak_saat_startup(self, model):
        """Salah konfigurasi harus menggagalkan boot, bukan menimbulkan tagihan."""
        with pytest.raises(Exception) as info:
            Settings(
                TELEGRAM_BOT_TOKEN="1:x",
                ADMIN_TELEGRAM_ID=1,
                DATABASE_URL="sqlite+aiosqlite:///:memory:",
                OPENROUTER_MODELS=model,
            )
        assert "gratis" in str(info.value).lower() or "kosong" in str(info.value).lower()

    def test_model_gratis_diterima(self):
        s = Settings(
            TELEGRAM_BOT_TOKEN="1:x",
            ADMIN_TELEGRAM_ID=1,
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            OPENROUTER_MODELS="meta-llama/llama-3.3-70b-instruct:free,google/gemma-2-9b-it:free",
        )
        assert len(s.openrouter_model_list) == 2
        assert all(m.endswith(":free") for m in s.openrouter_model_list)

    def test_satu_model_berbayar_menggagalkan_seluruh_daftar(self):
        """Daftar campuran ditolak — tidak ada yang 'lolos sebagian'."""
        with pytest.raises(Exception):
            Settings(
                TELEGRAM_BOT_TOKEN="1:x",
                ADMIN_TELEGRAM_ID=1,
                DATABASE_URL="sqlite+aiosqlite:///:memory:",
                OPENROUTER_MODELS="meta-llama/llama-3.3-70b-instruct:free,openai/gpt-4o",
            )

    @pytest.mark.parametrize("model", ["openai/gpt-4o", "", "llama-3.3-70b"])
    def test_pemeriksaan_kedua_sebelum_permintaan_dikirim(self, model):
        """Lapisan kedua: diperiksa ulang tepat sebelum POST."""
        with pytest.raises(AIConfigError):
            pastikan_model_gratis(model)

    def test_pemeriksaan_kedua_meloloskan_model_free(self):
        pastikan_model_gratis("meta-llama/llama-3.3-70b-instruct:free")


class TestValidasiLain:
    def test_admin_id_harus_angka_positif(self):
        with pytest.raises(Exception):
            Settings(
                TELEGRAM_BOT_TOKEN="1:x",
                ADMIN_TELEGRAM_ID=0,
                DATABASE_URL="sqlite+aiosqlite:///:memory:",
                OPENROUTER_MODELS="a:free",
            )

    def test_zona_waktu_tidak_dikenal_ditolak(self):
        with pytest.raises(Exception):
            Settings(
                TELEGRAM_BOT_TOKEN="1:x",
                ADMIN_TELEGRAM_ID=1,
                DATABASE_URL="sqlite+aiosqlite:///:memory:",
                OPENROUTER_MODELS="a:free",
                TIMEZONE="Mars/Olympus",
            )

    def test_zona_waktu_jakarta_diterima(self):
        s = Settings(
            TELEGRAM_BOT_TOKEN="1:x",
            ADMIN_TELEGRAM_ID=1,
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            OPENROUTER_MODELS="a:free",
            TIMEZONE="Asia/Jakarta",
        )
        assert str(s.tzinfo) == "Asia/Jakarta"


SESSION_POOLER = (
    "postgresql://postgres.abcd:pw@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres"
)
TRANSACTION_POOLER = (
    "postgresql://postgres.abcd:pw@aws-0-ap-northeast-1.pooler.supabase.com:6543/postgres"
)
DIRECT = "postgresql://postgres:pw@db.abcd.supabase.co:5432/postgres?sslmode=require"


class TestConnectionPoolerSupabase:
    """Supabase punya tiga mode koneksi dan hanya satu yang tepat untuk bot
    berproses panjang. Dua lainnya gagal dengan cara yang berbeda, jadi
    keduanya harus tertangani."""

    def test_session_mode_tidak_perlu_penyesuaian(self):
        """Mode yang disarankan: IPv4 dan prepared statement didukung penuh."""
        url = normalize_database_url(SESSION_POOLER)
        assert pakai_transaction_pooler(url) is False
        assert connect_args_untuk(url) == {}

    def test_transaction_mode_dikenali(self):
        url = normalize_database_url(TRANSACTION_POOLER)
        assert pakai_transaction_pooler(url) is True

    def test_transaction_mode_mematikan_prepared_statement(self):
        """Transaction mode tidak mendukung prepared statements, sementara
        asyncpg memakainya secara default."""
        args = connect_args_untuk(normalize_database_url(TRANSACTION_POOLER))
        assert args["prepared_statement_cache_size"] == 0

    def test_transaction_mode_memberi_nama_statement_unik(self):
        """Nama yang berulang bertabrakan ketika pooler membagi satu koneksi
        server ke banyak klien."""
        args = connect_args_untuk(normalize_database_url(TRANSACTION_POOLER))
        buat = args["prepared_statement_name_func"]
        assert buat() != buat()
        assert buat().startswith("__zoi_")

    def test_direct_connection_tidak_dianggap_pooler(self):
        url = normalize_database_url(DIRECT)
        assert pakai_transaction_pooler(url) is False
        assert connect_args_untuk(url) == {}

    def test_sqlite_tidak_pernah_dianggap_pooler(self):
        url = normalize_database_url("sqlite+aiosqlite:///./zoi.db")
        assert pakai_transaction_pooler(url) is False
        assert connect_args_untuk(url) == {}

    def test_password_berisi_6543_tidak_memicu_salah_deteksi(self):
        """Port dibaca dari bagian host, bukan dari kredensial."""
        url = normalize_database_url(
            "postgresql://postgres.abcd:p6543w@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres"
        )
        assert pakai_transaction_pooler(url) is False

    def test_engine_menerima_connect_args_transaction_mode(self):
        """Argumennya harus benar-benar diterima SQLAlchemy, bukan hanya
        terbentuk sebagai dict."""
        from sqlalchemy.ext.asyncio import create_async_engine

        url = normalize_database_url(TRANSACTION_POOLER)
        engine = create_async_engine(url, connect_args=connect_args_untuk(url))
        assert engine.url.port == 6543


class TestPengaturanKetahanan:
    def test_pool_kecil_secara_default(self):
        """Lunafy memberi 256 MB RAM untuk seluruh proses."""
        s = Settings(
            TELEGRAM_BOT_TOKEN="1:x",
            ADMIN_TELEGRAM_ID=1,
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            OPENROUTER_MODELS="a:free",
        )
        assert s.db_pool_size + s.db_max_overflow <= 6

    def test_keepalive_aktif_secara_default(self):
        """Supabase menjeda proyek Free yang aktivitasnya rendah 7 hari."""
        s = Settings(
            TELEGRAM_BOT_TOKEN="1:x",
            ADMIN_TELEGRAM_ID=1,
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            OPENROUTER_MODELS="a:free",
        )
        assert 0 < s.keepalive_hours <= 24

    def test_keepalive_bisa_dimatikan(self):
        s = Settings(
            TELEGRAM_BOT_TOKEN="1:x",
            ADMIN_TELEGRAM_ID=1,
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            OPENROUTER_MODELS="a:free",
            KEEPALIVE_HOURS=0,
        )
        assert s.keepalive_hours == 0


NEON_DIRECT = (
    "postgresql://u:p@ep-cool-x1.ap-southeast-1.aws.neon.tech/zoi"
    "?sslmode=require&channel_binding=require"
)
NEON_POOLER = (
    "postgresql://u:p@ep-cool-x1-pooler.ap-southeast-1.aws.neon.tech/zoi"
    "?sslmode=require&channel_binding=require"
)


class TestParameterLibpqYangTidakDikenalAsyncpg:
    """asyncpg menolak beberapa parameter libpq, dan gagalnya baru terjadi
    pada koneksi pertama — bukan saat engine dibuat. Semuanya harus dibuang
    di normalisasi URL, bukan diteruskan ke driver."""

    def test_channel_binding_dibuang(self):
        """Neon menyertakan channel_binding di connection string-nya."""
        hasil = normalize_database_url(NEON_DIRECT)
        assert "channel_binding" not in hasil
        assert "ssl=require" in hasil

    @pytest.mark.parametrize("param", ["channel_binding=require", "options=-csearch_path%3Dx",
                                       "target_session_attrs=read-write"])
    def test_parameter_libpq_lain_dibuang(self, param):
        hasil = normalize_database_url(f"postgresql://u:p@h:5432/d?{param}")
        assert param.split("=")[0] not in hasil

    def test_parameter_yang_dikenal_tetap_dipertahankan(self):
        hasil = normalize_database_url(
            "postgresql://u:p@h:5432/d?application_name=zoi&sslmode=require"
        )
        assert "application_name=zoi" in hasil
        assert "ssl=require" in hasil

    def test_asyncpg_memang_menolak_parameter_itu(self):
        """Dasar dari keputusan di atas, diuji langsung terhadap asyncpg."""
        import inspect

        import asyncpg

        diterima = inspect.signature(asyncpg.connect).parameters
        assert "sslmode" not in diterima
        assert "channel_binding" not in diterima
        assert "ssl" in diterima


class TestDeteksiPoolerAntarProvider:
    """Tiap provider menandai transaction pooler-nya berbeda."""

    def test_neon_pooler_dikenali_dari_hostname(self):
        """Neon menaruh PgBouncer di port 5432, jadi nomor port tidak cukup."""
        url = normalize_database_url(NEON_POOLER)
        assert pakai_transaction_pooler(url) is True
        assert connect_args_untuk(url)["prepared_statement_cache_size"] == 0

    def test_neon_direct_bukan_pooler(self):
        url = normalize_database_url(NEON_DIRECT)
        assert pakai_transaction_pooler(url) is False

    def test_session_pooler_supabase_tidak_salah_dikenali(self):
        """Hostname Supabase memuat kata "pooler" tanpa tanda hubung di
        depannya, dan session mode memang mendukung prepared statements."""
        url = normalize_database_url(SESSION_POOLER)
        assert pakai_transaction_pooler(url) is False
        assert connect_args_untuk(url) == {}
