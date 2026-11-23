"""Uji layanan transaksi: simpan, edit, hapus, saldo, rekap, hak akses."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.database.models import TransactionStatus, TransactionType
from app.database.repositories import audit_repo, transaction_repo
from app.services import balance_service as bs
from app.services import transaction_service as ts
from app.services.permission_service import PermissionDenied

HARI_INI = date(2026, 11, 23)


async def _buat(session, user, jenis, jumlah, kategori="Lain-lain", tgl=HARI_INI, **kw):
    return await ts.simpan_langsung(
        session,
        user=user,
        transaction_type=jenis,
        amount=Decimal(jumlah),
        kategori_nama=kategori,
        transaction_date=tgl,
        **kw,
    )


class TestSimpan:
    async def test_tambah_pengeluaran(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        trx = await _buat(s, admin, TransactionType.EXPENSE, "2000", "Transportasi",
                          description="Bayar parkir motor", location="Pasar Ciamis")
        await s.commit()

        assert trx.id is not None
        assert trx.amount == Decimal("2000.00")
        assert isinstance(trx.amount, Decimal)
        assert trx.status == TransactionStatus.ACTIVE
        assert trx.created_by == admin.id
        assert trx.location == "Pasar Ciamis"

    async def test_tambah_pemasukan(self, seeded):
        s, member = seeded["session"], seeded["member"]
        trx = await _buat(s, member, TransactionType.INCOME, "750000", "Penjualan")
        await s.commit()
        assert trx.transaction_type == TransactionType.INCOME

    async def test_kategori_tak_dikenal_jatuh_ke_lain_lain(self, seeded):
        """Transaksi tidak boleh gagal hanya karena kategori tidak dikenal."""
        s, admin = seeded["session"], seeded["admin"]
        trx = await _buat(s, admin, TransactionType.EXPENSE, "5000", "KategoriNgawur")
        await s.commit()

        dimuat = await transaction_repo.get_by_id(s, trx.id)
        assert dimuat.category.name == "Lain-lain"

    @pytest.mark.parametrize("jumlah", ["0", "-100"])
    async def test_jumlah_tidak_sah_ditolak(self, seeded, jumlah):
        s, admin = seeded["session"], seeded["admin"]
        with pytest.raises(ts.TransaksiGagal):
            await _buat(s, admin, TransactionType.EXPENSE, jumlah)

    async def test_anggota_nonaktif_tidak_bisa_mencatat(self, seeded):
        s, nonaktif = seeded["session"], seeded["nonaktif"]
        with pytest.raises(PermissionDenied):
            await _buat(s, nonaktif, TransactionType.EXPENSE, "1000")

    async def test_menulis_jejak_audit(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        trx = await _buat(s, admin, TransactionType.EXPENSE, "2000")
        await s.commit()

        jejak = await audit_repo.list_by_transaction(s, trx.id)
        assert len(jejak) == 1
        assert jejak[0].action == "transaction_create"
        assert jejak[0].details["jumlah"] == "2000.00"


class TestBukuKasBersama:
    async def test_semua_anggota_melihat_transaksi_yang_sama(self, seeded):
        """Inti buku kas bersama: tidak ada penyaringan per pengguna."""
        s, admin, member = seeded["session"], seeded["admin"], seeded["member"]

        await _buat(s, admin, TransactionType.EXPENSE, "2000")
        await _buat(s, member, TransactionType.EXPENSE, "3000")
        await s.commit()

        semua = await transaction_repo.list_all(s)
        assert len(semua) == 2
        assert {t.created_by for t in semua} == {admin.id, member.id}

    async def test_saldo_menghitung_transaksi_semua_anggota(self, seeded):
        s, admin, member = seeded["session"], seeded["admin"], seeded["member"]

        await _buat(s, admin, TransactionType.INCOME, "750000", "Penjualan")
        await _buat(s, member, TransactionType.EXPENSE, "150000", "Belanja Harian")
        await s.commit()

        saldo = await bs.hitung_saldo(s)
        assert saldo.saldo_awal == Decimal("1000000.00")
        assert saldo.total_pemasukan == Decimal("750000.00")
        assert saldo.total_pengeluaran == Decimal("150000.00")
        assert saldo.saldo_sekarang == Decimal("1600000.00")


class TestHakAkses:
    async def test_member_tidak_bisa_menghapus(self, seeded):
        """Aturan ZOI #9, tanpa pengecualian."""
        s, admin, member = seeded["session"], seeded["admin"], seeded["member"]
        trx = await _buat(s, member, TransactionType.EXPENSE, "2000")
        await s.commit()

        with pytest.raises(PermissionDenied):
            await ts.hapus(s, user=member, transaction_id=trx.id)

        # Pastikan benar-benar masih aktif.
        assert await transaction_repo.get_by_id(s, trx.id) is not None

    async def test_member_tidak_bisa_mengedit_transaksi_anggota_lain(self, seeded):
        s, admin, member = seeded["session"], seeded["admin"], seeded["member"]
        trx = await _buat(s, admin, TransactionType.EXPENSE, "2000")
        await s.commit()

        with pytest.raises(PermissionDenied):
            await ts.ubah(s, user=member, transaction_id=trx.id, amount=Decimal("1"))

        dimuat = await transaction_repo.get_by_id(s, trx.id)
        assert dimuat.amount == Decimal("2000.00")

    async def test_member_bisa_mengedit_transaksinya_sendiri(self, seeded):
        s, member = seeded["session"], seeded["member"]
        trx = await _buat(s, member, TransactionType.EXPENSE, "30000")
        await s.commit()

        diubah = await ts.ubah(s, user=member, transaction_id=trx.id, amount=Decimal("32000"))
        await s.commit()
        assert diubah.amount == Decimal("32000.00")
        assert diubah.updated_by == member.id

    async def test_admin_bisa_mengedit_transaksi_anggota_lain(self, seeded):
        s, admin, member = seeded["session"], seeded["admin"], seeded["member"]
        trx = await _buat(s, member, TransactionType.EXPENSE, "30000")
        await s.commit()

        diubah = await ts.ubah(s, user=admin, transaction_id=trx.id, amount=Decimal("31000"))
        await s.commit()
        assert diubah.amount == Decimal("31000.00")


class TestHapus:
    async def test_admin_hapus_adalah_soft_delete(self, seeded):
        """Aturan ZOI #11: catatan keuangan tidak pernah benar-benar hilang."""
        s, admin = seeded["session"], seeded["admin"]
        trx = await _buat(s, admin, TransactionType.EXPENSE, "150000")
        await s.commit()

        await ts.hapus(s, user=admin, transaction_id=trx.id)
        await s.commit()

        assert await transaction_repo.get_by_id(s, trx.id) is None
        masih = await transaction_repo.get_by_id(s, trx.id, termasuk_terhapus=True)
        assert masih is not None
        assert masih.status == TransactionStatus.DELETED

    async def test_transaksi_terhapus_tidak_masuk_saldo(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        trx = await _buat(s, admin, TransactionType.EXPENSE, "150000")
        await s.commit()

        sebelum = await bs.hitung_saldo(s)
        await ts.hapus(s, user=admin, transaction_id=trx.id)
        await s.commit()
        sesudah = await bs.hitung_saldo(s)

        assert sesudah.saldo_sekarang == sebelum.saldo_sekarang + Decimal("150000.00")
        assert sesudah.jumlah_transaksi == sebelum.jumlah_transaksi - 1

    async def test_hapus_dua_kali_idempoten(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        trx = await _buat(s, admin, TransactionType.EXPENSE, "2000")
        await s.commit()

        await ts.hapus(s, user=admin, transaction_id=trx.id)
        await s.commit()

        with pytest.raises(ts.TransaksiGagal):
            await ts.hapus(s, user=admin, transaction_id=trx.id)

    async def test_hapus_menyalin_isi_transaksi_ke_audit(self, seeded):
        """Kalau kelak ada pertanyaan soal catatan yang hilang, jawabannya di audit."""
        s, admin = seeded["session"], seeded["admin"]
        trx = await _buat(s, admin, TransactionType.EXPENSE, "150000", "Belanja Harian",
                          description="Beli beras")
        await s.commit()

        await ts.hapus(s, user=admin, transaction_id=trx.id)
        await s.commit()

        jejak = await audit_repo.list_by_transaction(s, trx.id)
        hapus = [j for j in jejak if j.action == "transaction_delete"]
        assert len(hapus) == 1
        assert hapus[0].details["transaksi"]["jumlah"] == "150000.00"
        assert hapus[0].details["transaksi"]["keterangan"] == "Beli beras"


class TestRekap:
    async def test_rekap_hari_ini_hanya_hari_itu(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        await _buat(s, admin, TransactionType.EXPENSE, "2000", tgl=HARI_INI)
        await _buat(s, admin, TransactionType.EXPENSE, "5000", tgl=date(2026, 11, 22))
        await s.commit()

        rekap = await bs.rekap_hari_ini(s, hari_ini=HARI_INI)
        assert rekap.pengeluaran == Decimal("2000.00")
        assert rekap.jumlah_transaksi == 1

    async def test_rekap_bulanan_mengelompokkan_bulan_dengan_benar(self, seeded):
        """Pengelompokan tidak boleh bergeser akibat zona waktu.

        Pernah terjadi: date_trunc pada kolom DATE memilih overload
        timestamptz, sehingga Oktober terlabel 30 September.
        """
        s, admin = seeded["session"], seeded["admin"]
        await _buat(s, admin, TransactionType.EXPENSE, "200000", tgl=date(2026, 10, 15))
        await _buat(s, admin, TransactionType.INCOME, "7500000", "Gaji", tgl=date(2026, 10, 28))
        await _buat(s, admin, TransactionType.EXPENSE, "2000", tgl=date(2026, 11, 23))
        await s.commit()

        baris = await bs.rekap_bulanan(s)
        assert [b.bulan for b in baris] == [date(2026, 10, 1), date(2026, 11, 1)]
        assert baris[0].pemasukan == Decimal("7500000.00")
        assert baris[0].pengeluaran == Decimal("200000.00")

    async def test_saldo_akhir_bulan_terakhir_sama_dengan_saldo_sekarang(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        await _buat(s, admin, TransactionType.INCOME, "7500000", "Gaji", tgl=date(2026, 10, 28))
        await _buat(s, admin, TransactionType.EXPENSE, "200000", tgl=date(2026, 11, 1))
        await _buat(s, admin, TransactionType.EXPENSE, "2000", tgl=date(2026, 11, 23))
        await s.commit()

        baris = await bs.rekap_bulanan(s)
        saldo = await bs.hitung_saldo(s)
        assert baris[-1].saldo_akhir == saldo.saldo_sekarang

    async def test_tanggal_batas_bulan_masuk_bulan_yang_benar(self):
        """Tanggal 1 dan tanggal terakhir bulan tidak boleh bergeser."""
        from app.utils.dates import month_bounds

        awal, akhir = month_bounds(date(2026, 11, 15))
        assert awal == date(2026, 11, 1)
        assert akhir == date(2026, 11, 30)


class TestDeteksiDuplikat:
    async def test_transaksi_identik_terdeteksi(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        trx = await _buat(s, admin, TransactionType.EXPENSE, "2000", "Transportasi")
        await s.commit()

        dup = await transaction_repo.find_possible_duplicate(
            s,
            transaction_type=TransactionType.EXPENSE,
            amount=Decimal("2000.00"),
            category_id=trx.category_id,
            transaction_date=HARI_INI,
            created_by=admin.id,
        )
        assert dup is not None and dup.id == trx.id

    async def test_jumlah_berbeda_bukan_duplikat(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        trx = await _buat(s, admin, TransactionType.EXPENSE, "2000", "Transportasi")
        await s.commit()

        dup = await transaction_repo.find_possible_duplicate(
            s,
            transaction_type=TransactionType.EXPENSE,
            amount=Decimal("3000.00"),
            category_id=trx.category_id,
            transaction_date=HARI_INI,
            created_by=admin.id,
        )
        assert dup is None

    async def test_anggota_berbeda_bukan_duplikat(self, seeded):
        """Dua orang membayar hal yang sama adalah dua transaksi berbeda."""
        s, admin, member = seeded["session"], seeded["admin"], seeded["member"]
        trx = await _buat(s, admin, TransactionType.EXPENSE, "2000", "Transportasi")
        await s.commit()

        dup = await transaction_repo.find_possible_duplicate(
            s,
            transaction_type=TransactionType.EXPENSE,
            amount=Decimal("2000.00"),
            category_id=trx.category_id,
            transaction_date=HARI_INI,
            created_by=member.id,
        )
        assert dup is None
