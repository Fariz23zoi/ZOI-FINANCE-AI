"""Konfigurasi aplikasi.

Memuat variabel lingkungan, memvalidasinya saat startup, dan menormalisasi
DATABASE_URL agar cocok dengan driver asyncpg.

Pola struktur (Pydantic Settings + field_validator + get_settings singleton)
diadaptasi dari RibasomR/finance-bot (MIT, Copyright (c) 2025-2026 RibasomR).
Lihat docs/THIRD_PARTY_NOTICES.md.

Prinsip: konfigurasi yang salah harus menggagalkan startup dengan pesan jelas,
bukan menimbulkan perilaku aneh saat aplikasi sudah dipakai.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import List, Optional
from urllib.parse import parse_qsl, urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_database_url(url: str) -> str:
    """Normalisasi DATABASE_URL agar aman dipakai SQLAlchemy + asyncpg.

    Dua hal yang diperbaiki:

    1. **Skema driver.** Supabase dan banyak panel lain memberi URL berawalan
       ``postgres://`` atau ``postgresql://``. SQLAlchemy butuh dialek async
       yang eksplisit: ``postgresql+asyncpg://``.

    2. **Parameter ``sslmode``.** Supabase menyertakan ``?sslmode=require``,
       tetapi ``sslmode`` adalah parameter libpq/psycopg yang TIDAK dikenal
       asyncpg. Perilaku ini sudah diverifikasi langsung (SQLAlchemy 2.1.9 +
       asyncpg 0.32.0): ``create_async_engine`` menerima URL itu tanpa
       peringatan, lalu gagal pada koneksi PERTAMA dengan
       ``TypeError: connect() got an unexpected keyword argument 'sslmode'``.
       Mode kegagalannya menipu karena aplikasi start dengan mulus.
       Karena itu ``sslmode`` dibuang dan diganti ``ssl``.

       Pemetaan nilai: disable -> (dibuang), allow/prefer -> prefer,
       require -> require, verify-ca -> verify-ca, verify-full -> verify-full.

    Penanganan connection pooler TIDAK dilakukan di sini, melainkan di
    ``connect_args_untuk``: argumennya adalah argumen DBAPI, bukan parameter
    URL, dan menaruhnya di satu tempat saja mencegah dua sumber kebenaran yang
    bisa saling bertentangan.

    Catatan implementasi: penggantian skema dilakukan dengan operasi string,
    bukan ``urlunsplit``. ``urlunsplit`` meruntuhkan ``///`` menjadi ``/``
    ketika netloc kosong, sehingga URL SQLite seperti
    ``sqlite+aiosqlite:///./zoi.db`` akan rusak menjadi
    ``sqlite+aiosqlite:/./zoi.db``.

    :param url: URL koneksi apa adanya dari lingkungan.
    :return: URL yang siap dipakai ``create_async_engine``.

    Example:
        >>> normalize_database_url("postgres://u:p@h:5432/d?sslmode=require")
        'postgresql+asyncpg://u:p@h:5432/d?ssl=require'
        >>> normalize_database_url("sqlite:///./zoi.db")
        'sqlite+aiosqlite:///./zoi.db'
    """
    url = (url or "").strip()
    if not url:
        return url

    # 1. Samakan skema ke dialek async yang eksplisit (operasi string murni).
    _SKEMA = (
        ("postgresql+asyncpg://", "postgresql+asyncpg://"),
        ("postgresql+psycopg://", "postgresql+asyncpg://"),
        ("postgresql://", "postgresql+asyncpg://"),
        ("postgres://", "postgresql+asyncpg://"),
        ("sqlite+aiosqlite://", "sqlite+aiosqlite://"),
        ("sqlite://", "sqlite+aiosqlite://"),
    )
    for lama, baru in _SKEMA:
        if url.startswith(lama):
            url = baru + url[len(lama):]
            break

    # Normalisasi sslmode hanya relevan untuk asyncpg.
    if not url.startswith("postgresql+asyncpg://"):
        return url

    # 2. Terjemahkan sslmode -> ssl pada query string.
    # Parameter libpq lain yang TIDAK dikenal asyncpg. Dibuang, bukan
    # diterjemahkan: tidak ada padanannya, dan membiarkannya membuat
    # asyncpg.connect() gagal dengan "unexpected keyword argument" pada
    # koneksi pertama — persis mode kegagalan menipu yang sama seperti
    # sslmode. Diverifikasi: asyncpg.connect tidak menerima channel_binding,
    # sslmode, maupun options.
    #
    # channel_binding disertakan Neon di connection string-nya, jadi ini
    # terpakai bila DATABASE_URL kelak diarahkan ke sana.
    _PARAM_LIBPQ_DIBUANG = ("channel_binding", "options", "target_session_attrs")

    _SSLMODE_TO_SSL = {
        "disable": None,
        "allow": "prefer",
        "prefer": "prefer",
        "require": "require",
        "verify-ca": "verify-ca",
        "verify-full": "verify-full",
    }

    if "?" not in url:
        return url

    dasar, _, query_mentah = url.partition("?")
    query = parse_qsl(query_mentah, keep_blank_values=True)

    bersih: List[tuple] = []
    ssl_value: Optional[str] = None
    sudah_ada_ssl = any(k == "ssl" for k, _ in query)

    for key, value in query:
        if key == "sslmode":
            ssl_value = _SSLMODE_TO_SSL.get(value.strip().lower(), "require")
            continue
        if key in _PARAM_LIBPQ_DIBUANG:
            continue
        bersih.append((key, value))

    if ssl_value and not sudah_ada_ssl:
        bersih.append(("ssl", ssl_value))

    query_baru = urlencode(bersih)
    return f"{dasar}?{query_baru}" if query_baru else dasar


def _transaction_mode(url_tanpa_query: str) -> bool:
    """True bila URL menunjuk ke connection pooler transaction mode.

    Dua penanda, karena tiap provider memberinya berbeda:

    * **port 6543** — Supavisor (Supabase) dan PgBouncer pada umumnya;
    * **hostname ber-akhiran ``-pooler``** — Neon, yang menaruh PgBouncer-nya
      di port 5432 biasa sehingga tidak bisa dikenali dari nomor port.

    Keduanya berarti hal yang sama bagi kita: prepared statement tidak bisa
    dipakai apa adanya.
    """
    host_port = url_tanpa_query.rsplit("@", 1)[-1]
    if ":6543" in host_port:
        return True

    host = host_port.split("/")[0].split(":")[0].lower()
    return "-pooler." in host or host.endswith("-pooler")


def pakai_transaction_pooler(url: str) -> bool:
    """True bila URL (sudah dinormalisasi) memakai transaction pooler."""
    dasar = url.partition("?")[0]
    return url.startswith("postgresql+asyncpg://") and _transaction_mode(dasar)


def connect_args_untuk(url: str) -> dict:
    """Argumen DBAPI tambahan yang dibutuhkan URL ini.

    Untuk transaction pooler, SQLAlchemy mendokumentasikan dua hal sekaligus:
    mematikan cache prepared statement DAN memberi nama prepared statement
    yang unik per permintaan. Yang kedua perlu karena beberapa versi asyncpg
    tetap menyiapkan statement bernama, dan nama yang berulang bertabrakan di
    pooler yang membagi satu koneksi server ke banyak klien.

    Mengembalikan dict kosong untuk session mode, direct connection, dan
    SQLite — tidak ada penyesuaian yang diperlukan di sana.
    """
    if not pakai_transaction_pooler(url):
        return {}

    from uuid import uuid4

    return {
        "prepared_statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__zoi_{uuid4().hex}__",
    }


class Settings(BaseSettings):
    """Pengaturan aplikasi, dimuat dari lingkungan atau file .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ─── Telegram ───
    telegram_bot_token: str = Field(..., validation_alias="TELEGRAM_BOT_TOKEN")
    admin_telegram_id: int = Field(..., validation_alias="ADMIN_TELEGRAM_ID")

    # ─── Database ───
    database_url: str = Field(..., validation_alias="DATABASE_URL")

    # ─── AI ───
    openrouter_api_key: str = Field(default="", validation_alias="OPENROUTER_API_KEY")
    openrouter_models: str = Field(
        default="meta-llama/llama-3.3-70b-instruct:free",
        validation_alias="OPENROUTER_MODELS",
    )
    gemini_api_key: str = Field(default="", validation_alias="GEMINI_API_KEY")
    gemini_models: str = Field(
        default="gemini-2.0-flash,gemini-2.0-flash-lite",
        validation_alias="GEMINI_MODELS",
    )

    # ─── Lokal ───
    timezone: str = Field(default="Asia/Jakarta", validation_alias="TIMEZONE")
    currency: str = Field(default="IDR", validation_alias="CURRENCY")

    # ─── Batas ───
    max_transaction_amount: Decimal = Field(
        default=Decimal("999999999"), validation_alias="MAX_TRANSACTION_AMOUNT"
    )
    pending_expire_minutes: int = Field(
        default=10, validation_alias="PENDING_EXPIRE_MINUTES"
    )
    rate_limit_requests: int = Field(default=20, validation_alias="RATE_LIMIT_REQUESTS")
    rate_limit_window_seconds: int = Field(
        default=60, validation_alias="RATE_LIMIT_WINDOW_SECONDS"
    )
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    # Pool kecil: host gratis Lunafy memberi 256 MB RAM untuk seluruh proses,
    # dan proyek Supabase Free punya kuota koneksi yang terbatas.
    db_pool_size: int = Field(default=3, validation_alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=2, validation_alias="DB_MAX_OVERFLOW")

    # Menjaga proyek Supabase Free dari penjedaan otomatis. Supabase menjeda
    # proyek yang aktivitas databasenya rendah selama 7 hari; beberapa query
    # per hari sudah cukup. Nol berarti dimatikan.
    keepalive_hours: int = Field(default=6, validation_alias="KEEPALIVE_HOURS")

    # ── Validator ───────────────────────────────────────────────

    @field_validator("database_url")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        normalized = normalize_database_url(v)
        if not normalized:
            raise ValueError("DATABASE_URL tidak boleh kosong")
        if "://" not in normalized:
            raise ValueError(f"DATABASE_URL tidak sah: {normalized[:30]}...")
        return normalized

    @field_validator("openrouter_models")
    @classmethod
    def _enforce_free_openrouter_models(cls, v: str) -> str:
        """Tolak model OpenRouter yang bukan gratis, saat startup.

        Aturan zero-cost ZOI: hanya model yang eksplisit gratis. Di OpenRouter
        penandanya adalah akhiran ``:free``. Memeriksanya di sini berarti salah
        konfigurasi menggagalkan boot, bukan menimbulkan tagihan.
        """
        models = [m.strip() for m in v.split(",") if m.strip()]
        if not models:
            raise ValueError("OPENROUTER_MODELS tidak boleh kosong")
        bukan_gratis = [m for m in models if not m.endswith(":free")]
        if bukan_gratis:
            raise ValueError(
                "Hanya model gratis yang diizinkan. Model berikut tidak "
                f"berakhiran ':free' → {bukan_gratis}. "
                "Perbaiki OPENROUTER_MODELS di .env."
            )
        return ",".join(models)

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"TIMEZONE tidak dikenal: {v!r}") from exc
        return v

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"LOG_LEVEL harus salah satu dari {sorted(allowed)}")
        return upper

    @field_validator("max_transaction_amount")
    @classmethod
    def _validate_max_amount(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("MAX_TRANSACTION_AMOUNT harus lebih besar dari nol")
        return v

    @field_validator("admin_telegram_id")
    @classmethod
    def _validate_admin_id(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(
                "ADMIN_TELEGRAM_ID harus berupa Telegram ID numerik positif "
                "(bukan username). Kirim pesan ke @userinfobot untuk melihat ID Anda."
            )
        return v

    @field_validator("pending_expire_minutes")
    @classmethod
    def _validate_pending_expire(cls, v: int) -> int:
        if not 1 <= v <= 1440:
            raise ValueError("PENDING_EXPIRE_MINUTES harus antara 1 dan 1440")
        return v

    @model_validator(mode="after")
    def _require_at_least_one_ai_key(self) -> "Settings":
        """Peringatkan bila tidak ada provider AI yang dikonfigurasi.

        Ini bukan error: bot tetap berguna dengan pra-parser regex dan entri
        manual. Tapi admin perlu tahu bahwa jalur AI tidak akan aktif.
        """
        if not self.openrouter_api_key and not self.gemini_api_key:
            import logging

            logging.getLogger(__name__).warning(
                "Tidak ada OPENROUTER_API_KEY maupun GEMINI_API_KEY. "
                "Bot akan berjalan dengan pra-parser bahasa Indonesia dan entri "
                "manual saja; parsing AI tidak aktif."
            )
        return self

    # ── Turunan ─────────────────────────────────────────────────

    @property
    def openrouter_model_list(self) -> List[str]:
        return [m.strip() for m in self.openrouter_models.split(",") if m.strip()]

    @property
    def gemini_model_list(self) -> List[str]:
        return [m.strip() for m in self.gemini_models.split(",") if m.strip()]

    @property
    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Ambil pengaturan aplikasi (singleton, di-cache)."""
    return Settings()  # type: ignore[call-arg]
