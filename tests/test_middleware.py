"""Uji middleware Telegram: otorisasi, pembatas laju, dan penanganan galat.

Objek aiogram dipalsukan dengan ``AsyncMock``; tidak ada koneksi ke Telegram.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.middlewares.auth import AuthMiddleware
from app.bot.middlewares.error_handler import ErrorHandlerMiddleware
from app.bot.middlewares.rate_limit import RateLimitMiddleware
from app.database.repositories import audit_repo
from app.services.permission_service import PermissionDenied


@pytest.fixture
def tg_user_factory():
    def buat(telegram_id: int, nama: str = "Uji", username: str | None = None, bot: bool = False):
        u = MagicMock()
        u.id = telegram_id
        u.first_name = nama
        u.last_name = None
        u.username = username
        u.is_bot = bot
        return u
    return buat


@pytest.fixture
def pesan_palsu():
    from aiogram.types import Message

    m = MagicMock(spec=Message)
    m.answer = AsyncMock()
    return m


@pytest.fixture
def patch_session(engine):
    """Arahkan session_scope ke engine test."""
    maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    with patch("app.database.session.get_sessionmaker", return_value=maker):
        yield maker


class TestAuthMiddleware:
    async def test_anggota_terdaftar_diteruskan(
        self, seeded, patch_session, tg_user_factory, pesan_palsu
    ):
        mw = AuthMiddleware()
        handler = AsyncMock(return_value="lanjut")
        data = {"event_from_user": tg_user_factory(seeded["admin"].telegram_id)}

        hasil = await mw(handler, pesan_palsu, data)

        assert hasil == "lanjut"
        handler.assert_awaited_once()
        assert data["user"].telegram_id == seeded["admin"].telegram_id
        assert data["is_admin"] is True
        pesan_palsu.answer.assert_not_awaited()

    async def test_member_ditandai_bukan_admin(
        self, seeded, patch_session, tg_user_factory, pesan_palsu
    ):
        mw = AuthMiddleware()
        data = {"event_from_user": tg_user_factory(seeded["member"].telegram_id)}
        await mw(AsyncMock(), pesan_palsu, data)
        assert data["is_admin"] is False

    async def test_pengguna_tak_terdaftar_ditolak(
        self, seeded, patch_session, tg_user_factory, pesan_palsu
    ):
        """Orang luar tidak boleh mencapai handler mana pun."""
        mw = AuthMiddleware()
        handler = AsyncMock()
        data = {"event_from_user": tg_user_factory(999999999)}

        hasil = await mw(handler, pesan_palsu, data)

        assert hasil is None
        handler.assert_not_awaited()
        pesan_palsu.answer.assert_awaited_once()
        assert "belum terdaftar" in pesan_palsu.answer.call_args[0][0].lower()

    async def test_percobaan_tak_sah_tercatat_di_audit(
        self, seeded, patch_session, tg_user_factory, pesan_palsu
    ):
        """Satu-satunya cara mengetahui ada yang mencoba masuk."""
        mw = AuthMiddleware()
        await mw(AsyncMock(), pesan_palsu, {"event_from_user": tg_user_factory(999999999, username="penyusup")})

        jejak = await audit_repo.list_recent(seeded["session"])
        tolak = [j for j in jejak if j.action == "unauthorized_access"]
        assert len(tolak) == 1
        assert tolak[0].telegram_id == 999999999
        assert tolak[0].details["alasan"] == "tidak_terdaftar"
        assert tolak[0].details["username"] == "penyusup"

    async def test_anggota_nonaktif_ditolak(
        self, seeded, patch_session, tg_user_factory, pesan_palsu
    ):
        mw = AuthMiddleware()
        handler = AsyncMock()
        data = {"event_from_user": tg_user_factory(seeded["nonaktif"].telegram_id)}

        hasil = await mw(handler, pesan_palsu, data)

        assert hasil is None
        handler.assert_not_awaited()
        assert "tidak aktif" in pesan_palsu.answer.call_args[0][0].lower()

    async def test_bot_lain_diabaikan(self, seeded, patch_session, tg_user_factory, pesan_palsu):
        mw = AuthMiddleware()
        handler = AsyncMock()
        hasil = await mw(handler, pesan_palsu, {"event_from_user": tg_user_factory(1, bot=True)})
        assert hasil is None
        handler.assert_not_awaited()

    async def test_event_tanpa_pengirim_diabaikan(self, seeded, patch_session, pesan_palsu):
        mw = AuthMiddleware()
        handler = AsyncMock()
        assert await mw(handler, pesan_palsu, {"event_from_user": None}) is None
        handler.assert_not_awaited()

    async def test_nama_disegarkan_tanpa_mengubah_hak_akses(
        self, seeded, patch_session, tg_user_factory, pesan_palsu
    ):
        """Ganti nama/username di Telegram tidak boleh memengaruhi otorisasi."""
        mw = AuthMiddleware()
        data = {"event_from_user": tg_user_factory(
            seeded["admin"].telegram_id, nama="Nama Baru", username="handle_baru"
        )}
        await mw(AsyncMock(), pesan_palsu, data)
        assert data["is_admin"] is True


class TestRateLimitMiddleware:
    async def test_dalam_batas_diteruskan(self, tg_user_factory, pesan_palsu):
        mw = RateLimitMiddleware(maks_permintaan=3, jendela_detik=60)
        handler = AsyncMock(return_value="ok")
        data = {"event_from_user": tg_user_factory(1)}

        for _ in range(3):
            assert await mw(handler, pesan_palsu, data) == "ok"

    async def test_melebihi_batas_diblokir(self, tg_user_factory, pesan_palsu):
        mw = RateLimitMiddleware(maks_permintaan=2, jendela_detik=60)
        handler = AsyncMock(return_value="ok")
        data = {"event_from_user": tg_user_factory(1)}

        await mw(handler, pesan_palsu, data)
        await mw(handler, pesan_palsu, data)
        hasil = await mw(handler, pesan_palsu, data)

        assert hasil is None
        assert handler.await_count == 2
        assert "terlalu banyak" in pesan_palsu.answer.call_args[0][0].lower()

    async def test_batas_dihitung_per_pengguna(self, tg_user_factory, pesan_palsu):
        """Satu anggota yang membanjiri tidak boleh memblokir anggota lain."""
        mw = RateLimitMiddleware(maks_permintaan=1, jendela_detik=60)
        handler = AsyncMock(return_value="ok")

        await mw(handler, pesan_palsu, {"event_from_user": tg_user_factory(1)})
        diblokir = await mw(handler, pesan_palsu, {"event_from_user": tg_user_factory(1)})
        pengguna_lain = await mw(handler, pesan_palsu, {"event_from_user": tg_user_factory(2)})

        assert diblokir is None
        assert pengguna_lain == "ok"


class TestErrorHandlerMiddleware:
    async def test_permission_denied_jadi_pesan_ramah(self, pesan_palsu):
        mw = ErrorHandlerMiddleware()
        handler = AsyncMock(side_effect=PermissionDenied("Hanya administrator."))

        hasil = await mw(handler, pesan_palsu, {})

        assert hasil is None
        assert "Hanya administrator." in pesan_palsu.answer.call_args[0][0]

    async def test_galat_tak_terduga_menyatakan_tidak_tersimpan(self, pesan_palsu):
        """Aturan ZOI #8: jangan pernah membiarkan pengguna menyangka
        transaksinya tersimpan padahal gagal."""
        mw = ErrorHandlerMiddleware()
        handler = AsyncMock(side_effect=RuntimeError("database mati"))

        hasil = await mw(handler, pesan_palsu, {})

        assert hasil is None
        pesan = pesan_palsu.answer.call_args[0][0]
        assert "TIDAK tersimpan" in pesan

    async def test_detail_internal_tidak_dibocorkan_ke_pengguna(self, pesan_palsu):
        mw = ErrorHandlerMiddleware()
        handler = AsyncMock(
            side_effect=RuntimeError("postgresql://zoi:rahasia@pooler.supabase.com/zoi gagal")
        )

        await mw(handler, pesan_palsu, {})

        pesan = pesan_palsu.answer.call_args[0][0]
        assert "rahasia" not in pesan
        assert "supabase.com" not in pesan

    async def test_hasil_normal_diteruskan(self, pesan_palsu):
        mw = ErrorHandlerMiddleware()
        assert await mw(AsyncMock(return_value="ok"), pesan_palsu, {}) == "ok"

    async def test_database_read_only_dijelaskan_khusus(self, pesan_palsu):
        """Supabase paket Free menjadi read-only di atas 500 MB, dan proyek
        yang dijeda juga menolak penulisan. Tanpa pemeriksaan khusus, pengguna
        hanya melihat galat umum dan tidak tahu penyebabnya bisa
        ditindaklanjuti."""
        from sqlalchemy.exc import DBAPIError

        mw = ErrorHandlerMiddleware()
        asli = Exception("cannot execute INSERT in a read-only transaction")
        handler = AsyncMock(side_effect=DBAPIError("INSERT ...", {}, asli))

        hasil = await mw(handler, pesan_palsu, {})

        assert hasil is None
        pesan = pesan_palsu.answer.call_args[0][0]
        assert "read-only" in pesan.lower()
        assert "TIDAK tersimpan" in pesan
        assert "Supabase" in pesan

    async def test_galat_database_lain_tetap_pesan_umum(self, pesan_palsu):
        from sqlalchemy.exc import DBAPIError

        mw = ErrorHandlerMiddleware()
        asli = Exception("connection refused")
        handler = AsyncMock(side_effect=DBAPIError("SELECT 1", {}, asli))

        await mw(handler, pesan_palsu, {})

        pesan = pesan_palsu.answer.call_args[0][0]
        assert "TIDAK tersimpan" in pesan
        assert "read-only" not in pesan.lower()
