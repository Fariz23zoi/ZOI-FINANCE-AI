"""Engine dan session database.

Pool dibatasi eksplisit karena dua alasan sekaligus:

* **RAM host.** Server gratis Lunafy memberi 256 MB RAM untuk seluruh proses.
  Setiap koneksi asyncpg punya buffer sendiri, jadi pool besar memakan memori
  yang dibutuhkan aiogram dan openpyxl.
* **Kuota koneksi Supabase.** Proyek Free punya batas koneksi yang jauh lebih
  kecil daripada instance mandiri, dan pool yang longgar bisa menahan slot
  yang tidak terpakai.

Untuk 2–3 pengguna, 3 koneksi tetap dengan 2 luapan sudah lapang.

Mode koneksi Supabase yang dipakai adalah **pooler session mode** (port 5432),
yang menurut dokumentasi Supabase memang untuk "persistent backend on
IPv4-only networks" — tepat menggambarkan bot ini. Direct connection pada
paket Free hanya IPv6, dan transaction mode (6543) tidak mendukung prepared
statements. Bila URL ternyata menunjuk transaction mode, ``app/config.py``
menyediakan argumen DBAPI yang membuatnya tetap bekerja.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import connect_args_untuk, get_settings, pakai_transaction_pooler
from app.utils.logger import get_logger
from app.utils.sanitizer import sanitize_url

logger = get_logger(__name__)

_engine: Optional[AsyncEngine] = None
_sessionmaker: Optional[async_sessionmaker[AsyncSession]] = None


def get_engine() -> AsyncEngine:
    """Ambil engine global, buat bila belum ada."""
    global _engine
    if _engine is not None:
        return _engine

    s = get_settings()

    kwargs: dict = {
        # echo=False mutlak di produksi: echo mencetak SQL lengkap beserta
        # parameternya, artinya seluruh data keuangan masuk ke log.
        "echo": False,
        "pool_pre_ping": True,
    }

    if s.is_sqlite:
        # SQLite memakai pool bawaannya sendiri; pool_size tidak berlaku.
        pass
    else:
        kwargs.update(
            pool_size=s.db_pool_size,
            max_overflow=s.db_max_overflow,
            # Pooler dan database bisa memutus koneksi idle, sementara proses
            # bot berumur panjang. Tanpa recycle + pre_ping, query pertama
            # setelah masa senggang akan gagal.
            pool_recycle=300,
        )

        tambahan = connect_args_untuk(s.database_url)
        if tambahan:
            kwargs["connect_args"] = tambahan
            logger.warning(
                "DATABASE_URL memakai connection pooler transaction mode "
                "(port 6543). Prepared statement dimatikan agar tetap bekerja, "
                "tetapi untuk bot berproses panjang sebaiknya pakai session "
                "mode (port 5432)."
            )

    _engine = create_async_engine(s.database_url, **kwargs)
    logger.info("Engine database dibuat: %s", sanitize_url(s.database_url))
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Ambil sessionmaker global."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _sessionmaker


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Session dengan commit/rollback otomatis.

    Dipakai untuk setiap operasi yang menulis. Pola ini memastikan transaksi
    database dan baris ``audit_logs``-nya masuk dalam satu commit — jejak audit
    tidak bisa menyimpang dari datanya.
    """
    maker = get_sessionmaker()
    async with maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Tutup semua koneksi. Dipanggil saat shutdown agar kuota 25 koneksi
    tidak tertahan oleh proses yang sudah berhenti."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        logger.info("Koneksi database ditutup.")
    _engine = None
    _sessionmaker = None


async def check_connection() -> bool:
    """Uji koneksi database. Dipanggil saat startup.

    Kegagalan di sini harus menghentikan startup: bot yang berjalan tanpa
    database akan menerima pesan dan tidak bisa menyimpannya, dan aturan ZOI
    melarang mengaku transaksi tersimpan kalau tidak.
    """
    from sqlalchemy import text

    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        from app.utils.sanitizer import sanitize_exception

        logger.error("Koneksi database gagal: %s", sanitize_exception(exc))
        return False


async def keepalive_ping() -> bool:
    """Satu query ringan untuk menandai database sebagai aktif.

    Dipakai oleh tugas keepalive di ``app/main.py``. Sengaja sesederhana
    mungkin: tujuannya hanya mencatat aktivitas, bukan mengambil data.
    """
    from sqlalchemy import text

    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.debug("Keepalive database OK.")
        return True
    except Exception as exc:
        from app.utils.sanitizer import sanitize_exception

        logger.warning("Keepalive database gagal: %s", sanitize_exception(exc))
        return False


async def database_size_bytes() -> Optional[int]:
    """Ukuran database dalam byte, untuk pemantauan kuota.

    Proyek Supabase paket Free menjadi read-only di atas 500 MB ukuran
    database. Aturan ZOI: peringatkan admin, jangan diam-diam kehilangan data.
    Mengembalikan None pada SQLite atau bila query tidak didukung.
    """
    from sqlalchemy import text

    s = get_settings()
    if s.is_sqlite:
        return None

    try:
        async with get_engine().connect() as conn:
            hasil = await conn.execute(text("SELECT pg_database_size(current_database())"))
            return int(hasil.scalar_one())
    except Exception as exc:
        from app.utils.sanitizer import sanitize_exception

        logger.warning("Gagal membaca ukuran database: %s", sanitize_exception(exc))
        return None
