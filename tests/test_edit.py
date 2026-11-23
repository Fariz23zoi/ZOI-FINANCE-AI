"""Uji alur /edit — mengubah transaksi yang sudah tersimpan.

Yang diuji di sini adalah hal-hal yang membedakan edit catatan tersimpan dari
edit calon transaksi: hak akses per pemilik, jejak audit dengan nilai sebelum
dan sesudah, dan pengaruhnya pada saldo.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.database.models import TransactionType
from app.database.repositories import audit_repo, transaction_repo
from app.services import balance_service as bs
from app.services import transaction_service as ts
from app.services.permission_service import PermissionDenied

HARI_INI = date(2026, 11, 23)


async def _buat(session, user, jenis=TransactionType.EXPENSE, jumlah="30000",
                kategori="Transportasi", **kw):
    return await ts.simpan_langsung(
        session, user=user, transaction_type=jenis, amount=Decimal(jumlah),
        kategori_nama=kategori, transaction_date=HARI_INI, **kw,
    )


class TestDaftarPilihan:
    async def test_admin_melihat_transaksi_semua_anggota(self, seeded):
        s, admin, member = seeded["session"], seeded["admin"], seeded["member"]
        await _buat(s, admin)
        await _buat(s, member)
        await s.commit()

        daftar = await transaction_repo.list_recent(s, limit=10, created_by=None)
        assert {t.created_by for t in daftar} == {admin.id, member.id}

    async def test_member_hanya_melihat_miliknya(self, seeded):
        """Menampilkan yang tidak bisa dipilih hanya berujung penolakan."""
        s, admin, member = seeded["session"], seeded["admin"], seeded["member"]
        await _buat(s, admin)
        await _buat(s, member)
        await s.commit()

        daftar = await transaction_repo.list_recent(s, limit=10, created_by=member.id)
        assert [t.created_by for t in daftar] == [member.id]

    async def test_terbaru_lebih_dulu(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        pertama = await _buat(s, admin, jumlah="1000")
        kedua = await _buat(s, admin, jumlah="2000")
        await s.commit()

        daftar = await transaction_repo.list_recent(s, limit=10)
        assert daftar[0].id == kedua.id and daftar[1].id == pertama.id

    async def test_transaksi_terhapus_tidak_bisa_diedit(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        trx = await _buat(s, admin)
        await s.commit()
        await ts.hapus(s, user=admin, transaction_id=trx.id)
        await s.commit()

        assert await transaction_repo.list_recent(s, limit=10) == []
        with pytest.raises(ts.TransaksiGagal):
            await ts.ubah(s, user=admin, transaction_id=trx.id, amount=Decimal("1"))


class TestHakAkses:
    async def test_member_mengubah_miliknya_sendiri(self, seeded):
        s, member = seeded["session"], seeded["member"]
        trx = await _buat(s, member, jumlah="30000")
        await s.commit()

        hasil = await ts.ubah(s, user=member, transaction_id=trx.id, amount=Decimal("32000"))
        await s.commit()
        assert hasil.amount == Decimal("32000.00")
        assert hasil.updated_by == member.id

    async def test_member_ditolak_mengubah_milik_orang_lain(self, seeded):
        s, admin, member = seeded["session"], seeded["admin"], seeded["member"]
        trx = await _buat(s, admin, jumlah="30000")
        await s.commit()

        with pytest.raises(PermissionDenied):
            await ts.ubah(s, user=member, transaction_id=trx.id, amount=Decimal("1"))

        # Nilainya benar-benar tidak berubah.
        assert (await transaction_repo.get_by_id(s, trx.id)).amount == Decimal("30000.00")

    async def test_admin_mengubah_milik_siapa_pun(self, seeded):
        s, admin, member = seeded["session"], seeded["admin"], seeded["member"]
        trx = await _buat(s, member, jumlah="30000")
        await s.commit()

        hasil = await ts.ubah(s, user=admin, transaction_id=trx.id, amount=Decimal("31000"))
        await s.commit()
        assert hasil.amount == Decimal("31000.00")
        assert hasil.updated_by == admin.id

    async def test_anggota_nonaktif_ditolak(self, seeded):
        s, admin, nonaktif = seeded["session"], seeded["admin"], seeded["nonaktif"]
        trx = await _buat(s, admin)
        await s.commit()

        with pytest.raises(PermissionDenied):
            await ts.ubah(s, user=nonaktif, transaction_id=trx.id, amount=Decimal("1"))


class TestFieldYangBisaDiubah:
    async def test_ubah_keterangan(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        trx = await _buat(s, admin, description="Beli bensin")
        await s.commit()

        hasil = await ts.ubah(
            s, user=admin, transaction_id=trx.id, description="Beli bensin Pertalite"
        )
        await s.commit()
        assert hasil.description == "Beli bensin Pertalite"

    async def test_ubah_lokasi(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        trx = await _buat(s, admin)
        await s.commit()

        hasil = await ts.ubah(s, user=admin, transaction_id=trx.id, location="Pasar Ciamis")
        await s.commit()
        assert hasil.location == "Pasar Ciamis"

    async def test_ubah_tanggal(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        trx = await _buat(s, admin)
        await s.commit()

        baru = HARI_INI - timedelta(days=3)
        hasil = await ts.ubah(s, user=admin, transaction_id=trx.id, transaction_date=baru)
        await s.commit()
        assert hasil.transaction_date == baru

    async def test_ubah_kategori(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        trx = await _buat(s, admin, kategori="Transportasi")
        await s.commit()

        hasil = await ts.ubah(s, user=admin, transaction_id=trx.id, kategori_nama="Hiburan")
        await s.commit()
        assert hasil.category.name == "Hiburan"

    async def test_kategori_dicari_dalam_jenis_yang_sama(self, seeded):
        """Kategori pemasukan tidak boleh terpasang pada pengeluaran."""
        s, admin = seeded["session"], seeded["admin"]
        trx = await _buat(s, admin, jenis=TransactionType.EXPENSE)
        await s.commit()

        hasil = await ts.ubah(s, user=admin, transaction_id=trx.id, kategori_nama="Gaji")
        await s.commit()
        # "Gaji" hanya ada sebagai kategori pemasukan, jadi tidak dipakai.
        assert hasil.category.transaction_type == TransactionType.EXPENSE
        assert hasil.category.name != "Gaji"

    async def test_jumlah_tidak_sah_ditolak(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        trx = await _buat(s, admin, jumlah="30000")
        await s.commit()

        for buruk in [Decimal("0"), Decimal("-100")]:
            with pytest.raises(ts.TransaksiGagal):
                await ts.ubah(s, user=admin, transaction_id=trx.id, amount=buruk)

        assert (await transaction_repo.get_by_id(s, trx.id)).amount == Decimal("30000.00")

    async def test_tanpa_perubahan_ditolak(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        trx = await _buat(s, admin)
        await s.commit()

        with pytest.raises(ts.TransaksiGagal):
            await ts.ubah(s, user=admin, transaction_id=trx.id)


class TestPengaruhPadaSaldo:
    async def test_saldo_mengikuti_perubahan_jumlah(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        trx = await _buat(s, admin, jumlah="30000")
        await s.commit()

        sebelum = await bs.hitung_saldo(s)
        await ts.ubah(s, user=admin, transaction_id=trx.id, amount=Decimal("50000"))
        await s.commit()
        sesudah = await bs.hitung_saldo(s)

        # Pengeluaran naik 20.000, jadi saldo turun 20.000.
        assert sesudah.saldo_sekarang == sebelum.saldo_sekarang - Decimal("20000.00")

    async def test_mengubah_tanggal_memindahkan_rekap_bulanan(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        trx = await _buat(s, admin, jumlah="30000")
        await s.commit()

        await ts.ubah(
            s, user=admin, transaction_id=trx.id, transaction_date=date(2026, 10, 15)
        )
        await s.commit()

        baris = await bs.rekap_bulanan(s)
        assert [b.bulan for b in baris] == [date(2026, 10, 1)]

    async def test_saldo_total_tidak_berubah_karena_pindah_bulan(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        trx = await _buat(s, admin, jumlah="30000")
        await s.commit()

        sebelum = await bs.hitung_saldo(s)
        await ts.ubah(
            s, user=admin, transaction_id=trx.id, transaction_date=date(2026, 10, 15)
        )
        await s.commit()

        assert (await bs.hitung_saldo(s)).saldo_sekarang == sebelum.saldo_sekarang


class TestJejakAudit:
    async def test_perubahan_mencatat_nilai_sebelum_dan_sesudah(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        trx = await _buat(s, admin, jumlah="30000", description="Beli bensin")
        await s.commit()

        await ts.ubah(s, user=admin, transaction_id=trx.id, amount=Decimal("32000"))
        await s.commit()

        jejak = await audit_repo.list_by_transaction(s, trx.id)
        ubah = [j for j in jejak if j.action == "transaction_update"]
        assert len(ubah) == 1
        assert ubah[0].details["sebelum"]["jumlah"] == "30000.00"
        assert ubah[0].details["sesudah"]["amount"] == "32000.00"
        assert ubah[0].user_id == admin.id

    async def test_setiap_perubahan_menambah_satu_entri(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        trx = await _buat(s, admin, jumlah="30000")
        await s.commit()

        for jumlah in ["31000", "32000", "33000"]:
            await ts.ubah(s, user=admin, transaction_id=trx.id, amount=Decimal(jumlah))
            await s.commit()

        jejak = await audit_repo.list_by_transaction(s, trx.id)
        assert len([j for j in jejak if j.action == "transaction_update"]) == 3

    async def test_perubahan_yang_ditolak_tidak_menulis_audit(self, seeded):
        """Jejak audit hanya memuat perubahan yang benar-benar terjadi."""
        s, admin, member = seeded["session"], seeded["admin"], seeded["member"]
        trx = await _buat(s, admin)
        await s.commit()

        with pytest.raises(PermissionDenied):
            await ts.ubah(s, user=member, transaction_id=trx.id, amount=Decimal("1"))

        # Penolakan terjadi sebelum ada penulisan apa pun, jadi tidak ada yang
        # perlu dibatalkan — dan jejak auditnya hanya memuat pembuatannya.
        jejak = await audit_repo.list_by_transaction(s, trx.id)
        assert [j.action for j in jejak] == ["transaction_create"]
