"""Uji alur pending dan proteksi konfirmasi ganda.

Ini pengujian paling penting untuk aturan ZOI #8 ("jangan pernah menyimpan
transaksi yang belum dikonfirmasi") dan bagian 10 ("klik ganda tidak boleh
membuat transaksi ganda").
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import update

from app.ai.schema import ParsedTransaction
from app.database.models import PendingStatus, PendingTransaction, TransactionType
from app.database.repositories import pending_repo, transaction_repo
from app.services import transaction_service as ts

HARI_INI = date(2026, 11, 23)


def _parsed(jumlah="2000") -> ParsedTransaction:
    return ParsedTransaction(
        transaction_type=TransactionType.EXPENSE,
        amount=Decimal(jumlah),
        category="Transportasi",
        description="Bayar parkir motor",
        location="Pasar Ciamis",
        transaction_date=HARI_INI,
        sumber="parser",
    )


async def _buat_pending(session, user, jumlah="2000"):
    p = await pending_repo.create(
        session,
        telegram_user_id=user.telegram_id,
        parsed_data=_parsed(jumlah).to_json(),
        source_text="Bayar parkir motor 2 ribu di pasar Ciamis",
        expire_minutes=10,
    )
    await session.commit()
    return p


class TestKlaimAtomik:
    async def test_klaim_pertama_berhasil(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        p = await _buat_pending(s, admin)

        assert await pending_repo.claim(s, p.id, admin.telegram_id) is True
        await s.commit()

    async def test_klaim_kedua_gagal(self, seeded):
        """Inti proteksi klik ganda: hanya satu klaim yang boleh menang."""
        s, admin = seeded["session"], seeded["admin"]
        p = await _buat_pending(s, admin)

        pertama = await pending_repo.claim(s, p.id, admin.telegram_id)
        await s.commit()
        kedua = await pending_repo.claim(s, p.id, admin.telegram_id)
        await s.commit()

        assert pertama is True
        assert kedua is False

    async def test_anggota_lain_tidak_bisa_mengklaim(self, seeded):
        """callback_data bisa ditebak; kepemilikan harus diperiksa."""
        s, admin, member = seeded["session"], seeded["admin"], seeded["member"]
        p = await _buat_pending(s, admin)

        assert await pending_repo.claim(s, p.id, member.telegram_id) is False

    async def test_pending_kedaluwarsa_tidak_bisa_diklaim(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        p = await _buat_pending(s, admin)

        await s.execute(
            update(PendingTransaction)
            .where(PendingTransaction.id == p.id)
            .values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        )
        await s.commit()

        assert await pending_repo.claim(s, p.id, admin.telegram_id) is False

    async def test_pending_yang_dibatalkan_tidak_bisa_diklaim(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        p = await _buat_pending(s, admin)

        assert await pending_repo.cancel(s, p.id, admin.telegram_id) is True
        await s.commit()
        assert await pending_repo.claim(s, p.id, admin.telegram_id) is False


class TestSimpanDariPending:
    async def test_simpan_membuat_transaksi_dan_menautkannya(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        p = await _buat_pending(s, admin)

        hasil = await ts.simpan_dari_pending(s, user=admin, pending_id=p.id)
        await s.commit()

        assert hasil.transaksi is not None
        assert hasil.transaksi.amount == Decimal("2000.00")
        assert hasil.transaksi.location == "Pasar Ciamis"

        dimuat = await pending_repo.get(s, p.id)
        assert dimuat.status == PendingStatus.CONFIRMED
        assert dimuat.transaction_id == hasil.transaksi.id

    async def test_klik_ganda_hanya_menghasilkan_satu_transaksi(self, seeded):
        """Dua kali tekan Simpan = satu transaksi, bukan dua."""
        s, admin = seeded["session"], seeded["admin"]
        p = await _buat_pending(s, admin)

        pertama = await ts.simpan_dari_pending(s, user=admin, pending_id=p.id)
        await s.commit()
        kedua = await ts.simpan_dari_pending(s, user=admin, pending_id=p.id)
        await s.commit()

        assert pertama.transaksi is not None
        assert kedua.transaksi is None
        assert kedua.sudah_diproses is True

        semua = await transaction_repo.list_all(s)
        assert len(semua) == 1

    async def test_pending_milik_orang_lain_ditolak(self, seeded):
        s, admin, member = seeded["session"], seeded["admin"], seeded["member"]
        p = await _buat_pending(s, admin)

        with pytest.raises(ts.TransaksiGagal):
            await ts.simpan_dari_pending(s, user=member, pending_id=p.id)

        assert len(await transaction_repo.list_all(s)) == 0

    async def test_pending_tidak_ada(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        with pytest.raises(ts.TransaksiGagal):
            await ts.simpan_dari_pending(s, user=admin, pending_id=999999)

    async def test_duplikat_terdeteksi_dan_tidak_menyimpan(self, seeded):
        s, admin = seeded["session"], seeded["admin"]

        p1 = await _buat_pending(s, admin)
        await ts.simpan_dari_pending(s, user=admin, pending_id=p1.id)
        await s.commit()

        p2 = await _buat_pending(s, admin)
        hasil = await ts.simpan_dari_pending(s, user=admin, pending_id=p2.id)
        await s.commit()

        assert hasil.transaksi is None
        assert hasil.duplikat_terdeteksi is not None
        assert len(await transaction_repo.list_all(s)) == 1

    async def test_duplikat_bisa_ditimpa_bila_pengguna_menegaskan(self, seeded):
        s, admin = seeded["session"], seeded["admin"]

        p1 = await _buat_pending(s, admin)
        await ts.simpan_dari_pending(s, user=admin, pending_id=p1.id)
        await s.commit()

        p2 = await _buat_pending(s, admin)
        hasil = await ts.simpan_dari_pending(
            s, user=admin, pending_id=p2.id, lewati_cek_duplikat=True
        )
        await s.commit()

        assert hasil.transaksi is not None
        assert len(await transaction_repo.list_all(s)) == 2

    async def test_pending_tidak_lengkap_ditolak(self, seeded):
        """Transaksi tanpa jumlah tidak boleh tersimpan."""
        s, admin = seeded["session"], seeded["admin"]

        kosong = ParsedTransaction(
            transaction_type=TransactionType.EXPENSE,
            amount=None,
            transaction_date=HARI_INI,
        )
        p = await pending_repo.create(
            session=s,
            telegram_user_id=admin.telegram_id,
            parsed_data=kosong.to_json(),
            source_text="beli sesuatu",
        )
        await s.commit()

        with pytest.raises(ts.TransaksiGagal):
            await ts.simpan_dari_pending(s, user=admin, pending_id=p.id)


class TestKedaluwarsa:
    async def test_expire_stale_menandai_yang_lewat_waktu(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        p = await _buat_pending(s, admin)

        await s.execute(
            update(PendingTransaction)
            .where(PendingTransaction.id == p.id)
            .values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        )
        await s.commit()

        jumlah = await pending_repo.expire_stale(s)
        await s.commit()

        assert jumlah == 1
        assert (await pending_repo.get(s, p.id)).status == PendingStatus.EXPIRED

    async def test_pending_yang_masih_berlaku_tidak_tersentuh(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        p = await _buat_pending(s, admin)

        assert await pending_repo.expire_stale(s) == 0
        assert (await pending_repo.get(s, p.id)).status == PendingStatus.WAITING


class TestEditPending:
    async def test_ubah_data_pending(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        p = await _buat_pending(s, admin)

        parsed = _parsed()
        parsed.amount = Decimal("5000")
        ok = await pending_repo.update_parsed_data(
            s, p.id, admin.telegram_id, parsed.to_json()
        )
        await s.commit()

        assert ok is True
        dimuat = ParsedTransaction.from_json((await pending_repo.get(s, p.id)).parsed_data)
        assert dimuat.amount == Decimal("5000")

    async def test_tidak_bisa_mengubah_pending_yang_sudah_dikonfirmasi(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        p = await _buat_pending(s, admin)

        await pending_repo.claim(s, p.id, admin.telegram_id)
        await s.commit()

        ok = await pending_repo.update_parsed_data(
            s, p.id, admin.telegram_id, _parsed("9999").to_json()
        )
        assert ok is False

    async def test_teks_asli_tersimpan(self, seeded):
        """Aturan ZOI: jangan membuang pesan pengguna."""
        s, admin = seeded["session"], seeded["admin"]
        p = await _buat_pending(s, admin)

        dimuat = await pending_repo.get(s, p.id)
        assert dimuat.source_text == "Bayar parkir motor 2 ribu di pasar Ciamis"
