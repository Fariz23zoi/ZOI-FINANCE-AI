"""Uji pengelolaan anggota dan matriks hak akses."""

from __future__ import annotations

import pytest

from app.database.models import Transaction, TransactionType, UserRole
from app.database.repositories import audit_repo, user_repo
from app.services import member_service as ms
from app.services import permission_service as ps


class TestMatriksHakAkses:
    """Matriks di docs/ARCHITECTURE.md bagian 6, diuji satu per satu."""

    def test_admin_boleh_semuanya(self, seeded):
        admin = seeded["admin"]
        ps.boleh_lihat(admin)
        ps.boleh_tambah(admin)
        ps.boleh_hapus(admin)
        ps.boleh_kelola_anggota(admin)
        ps.boleh_ubah_pengaturan(admin)
        ps.boleh_ekspor(admin, member_can_export=False)

    def test_member_boleh_lihat_dan_tambah(self, seeded):
        member = seeded["member"]
        ps.boleh_lihat(member)
        ps.boleh_tambah(member)

    @pytest.mark.parametrize(
        "fungsi", ["boleh_hapus", "boleh_kelola_anggota", "boleh_ubah_pengaturan"]
    )
    def test_member_ditolak_untuk_aksi_admin(self, seeded, fungsi):
        with pytest.raises(ps.PermissionDenied):
            getattr(ps, fungsi)(seeded["member"])

    def test_member_ditolak_ekspor_bila_dimatikan(self, seeded):
        with pytest.raises(ps.PermissionDenied):
            ps.boleh_ekspor(seeded["member"], member_can_export=False)

    @pytest.mark.parametrize(
        "fungsi", ["boleh_lihat", "boleh_tambah", "boleh_hapus", "pastikan_aktif"]
    )
    def test_anggota_nonaktif_ditolak_semuanya(self, seeded, fungsi):
        with pytest.raises(ps.PermissionDenied):
            getattr(ps, fungsi)(seeded["nonaktif"])

    def test_edit_transaksi_sendiri_vs_orang_lain(self, seeded):
        admin, member = seeded["admin"], seeded["member"]

        milik_member = Transaction(
            transaction_type=TransactionType.EXPENSE, amount=1, category_id=1,
            transaction_date=None, created_by=member.id,
        )
        milik_admin = Transaction(
            transaction_type=TransactionType.EXPENSE, amount=1, category_id=1,
            transaction_date=None, created_by=admin.id,
        )

        ps.boleh_edit(member, milik_member)   # miliknya sendiri: boleh
        ps.boleh_edit(admin, milik_member)    # admin: boleh semua
        ps.boleh_edit(admin, milik_admin)

        with pytest.raises(ps.PermissionDenied):
            ps.boleh_edit(member, milik_admin)

    def test_pesan_penolakan_bisa_dibaca_pengguna(self, seeded):
        """Pesannya tampil langsung di Telegram, jadi harus menjelaskan."""
        with pytest.raises(ps.PermissionDenied) as info:
            ps.boleh_hapus(seeded["member"])
        pesan = str(info.value)
        assert "administrator" in pesan.lower()
        assert len(pesan) > 30


class TestTambahAnggota:
    async def test_admin_bisa_menambah(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        baru = await ms.tambah(s, user=admin, telegram_id_mentah="100000009", nama="Anggota Baru")
        await s.commit()

        assert baru.telegram_id == 100000009
        assert baru.role == UserRole.MEMBER
        assert baru.is_active is True

    async def test_member_tidak_bisa_menambah(self, seeded):
        s, member = seeded["session"], seeded["member"]
        with pytest.raises(ps.PermissionDenied):
            await ms.tambah(s, user=member, telegram_id_mentah="100000009", nama="X")

    async def test_username_ditolak_sebagai_identitas(self, seeded):
        """Username bisa diganti pemiliknya; hanya ID numerik yang sah."""
        s, admin = seeded["session"], seeded["admin"]
        with pytest.raises(ms.PengelolaanGagal) as info:
            await ms.tambah(s, user=admin, telegram_id_mentah="@fariz", nama="Fariz")
        assert "numerik" in str(info.value).lower()

    async def test_anggota_yang_sudah_ada_ditolak(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        with pytest.raises(ms.PengelolaanGagal):
            await ms.tambah(s, user=admin, telegram_id_mentah="100000002", nama="Duplikat")

    async def test_anggota_nonaktif_diaktifkan_kembali_bukan_dibuat_ulang(self, seeded):
        """Transaksi lamanya menunjuk ke user.id yang ini — jangan buat baris baru."""
        s, admin, nonaktif = seeded["session"], seeded["admin"], seeded["nonaktif"]
        sebelum = len(await user_repo.list_all(s))

        hasil = await ms.tambah(
            s, user=admin, telegram_id_mentah=str(nonaktif.telegram_id), nama="Kembali"
        )
        await s.commit()

        assert hasil.id == nonaktif.id
        assert hasil.is_active is True
        assert len(await user_repo.list_all(s)) == sebelum

    async def test_nama_terlalu_pendek_ditolak(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        with pytest.raises(ms.PengelolaanGagal):
            await ms.tambah(s, user=admin, telegram_id_mentah="100000009", nama="X")

    async def test_batas_jumlah_anggota_ditegakkan(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        # Sudah ada 2 aktif; isi sampai batas.
        for i in range(ms.MAKS_ANGGOTA_AKTIF - 2):
            await ms.tambah(
                s, user=admin, telegram_id_mentah=str(200000000 + i), nama=f"Anggota {i}"
            )
        await s.commit()

        with pytest.raises(ms.PengelolaanGagal) as info:
            await ms.tambah(s, user=admin, telegram_id_mentah="299999999", nama="Kelebihan")
        assert "batas" in str(info.value).lower()

    async def test_penambahan_tercatat_di_audit(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        await ms.tambah(s, user=admin, telegram_id_mentah="100000009", nama="Anggota Baru")
        await s.commit()

        jejak = await audit_repo.list_recent(s)
        assert any(j.action == "member_add" for j in jejak)


class TestPeranDanNonaktif:
    async def test_admin_bisa_mengangkat_admin_baru(self, seeded):
        s, admin, member = seeded["session"], seeded["admin"], seeded["member"]
        hasil = await ms.ubah_peran(s, user=admin, target_user_id=member.id, jadi_admin=True)
        await s.commit()
        assert hasil.role == UserRole.ADMIN

    async def test_admin_terakhir_tidak_bisa_diturunkan(self, seeded):
        """Tanpa admin, tidak ada lagi yang bisa mengelola sistem."""
        s, admin = seeded["session"], seeded["admin"]
        with pytest.raises(ms.PengelolaanGagal) as info:
            await ms.ubah_peran(s, user=admin, target_user_id=admin.id, jadi_admin=False)
        assert "terakhir" in str(info.value).lower()

    async def test_admin_terakhir_tidak_bisa_dinonaktifkan(self, seeded):
        s, admin = seeded["session"], seeded["admin"]
        with pytest.raises(ms.PengelolaanGagal):
            await ms.nonaktifkan(s, user=admin, target_user_id=admin.id)

    async def test_admin_bisa_diturunkan_bila_ada_admin_lain(self, seeded):
        s, admin, member = seeded["session"], seeded["admin"], seeded["member"]
        await ms.ubah_peran(s, user=admin, target_user_id=member.id, jadi_admin=True)
        await s.commit()

        hasil = await ms.ubah_peran(s, user=admin, target_user_id=admin.id, jadi_admin=False)
        await s.commit()
        assert hasil.role == UserRole.MEMBER

    async def test_nonaktifkan_tidak_menghapus_baris(self, seeded):
        s, admin, member = seeded["session"], seeded["admin"], seeded["member"]
        sebelum = len(await user_repo.list_all(s))

        await ms.nonaktifkan(s, user=admin, target_user_id=member.id)
        await s.commit()

        assert len(await user_repo.list_all(s)) == sebelum
        assert (await user_repo.get_by_id(s, member.id)).is_active is False

    async def test_member_tidak_bisa_mengubah_peran(self, seeded):
        s, member, admin = seeded["session"], seeded["member"], seeded["admin"]
        with pytest.raises(ps.PermissionDenied):
            await ms.ubah_peran(s, user=member, target_user_id=admin.id, jadi_admin=False)


class TestDaftarAnggota:
    async def test_member_boleh_melihat_daftar(self, seeded):
        s, member = seeded["session"], seeded["member"]
        daftar = await ms.daftar(s, user=member)
        assert len(daftar) == 3

    async def test_anggota_nonaktif_ditolak(self, seeded):
        s, nonaktif = seeded["session"], seeded["nonaktif"]
        with pytest.raises(ps.PermissionDenied):
            await ms.daftar(s, user=nonaktif)
