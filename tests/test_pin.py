"""Uji papan saldo tersemat.

Yang diuji di sini bukan "apakah pesannya terkirim" — itu urusan Telegram.
Yang diuji adalah empat cara fitur ini gagal di dunia nyata, karena di
situlah papan saldo biasanya berhenti berguna tanpa ada yang menyadarinya.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError

from app.database.models import Transaction, TransactionType
from app.database.repositories import user_repo
from app.services import pin_service


class PesanPalsu:
    def __init__(self, message_id: int) -> None:
        self.message_id = message_id


class BotPalsu:
    """Bot tiruan yang mencatat panggilan dan bisa disuruh gagal.

    Memakai bot sungguhan berarti memanggil Telegram; yang perlu dipastikan
    justru perilaku kita saat Telegram menolak.
    """

    def __init__(self, galat_edit: Exception | None = None,
                 galat_kirim: Exception | None = None) -> None:
        self.galat_edit = galat_edit
        self.galat_kirim = galat_kirim
        self.edit_dipanggil: list[tuple[int, int]] = []
        self.kirim_dipanggil: list[int] = []
        self.pin_dipanggil: list[tuple[int, int]] = []
        self._nomor_berikutnya = 5000

    async def edit_message_text(self, chat_id, message_id, text, **_):
        self.edit_dipanggil.append((chat_id, message_id))
        if self.galat_edit is not None:
            raise self.galat_edit
        return PesanPalsu(message_id)

    async def send_message(self, chat_id, text, **_):
        self.kirim_dipanggil.append(chat_id)
        if self.galat_kirim is not None:
            raise self.galat_kirim
        self._nomor_berikutnya += 1
        return PesanPalsu(self._nomor_berikutnya)

    async def pin_chat_message(self, chat_id, message_id, **_):
        self.pin_dipanggil.append((chat_id, message_id))


def galat(pesan: str) -> TelegramAPIError:
    return TelegramAPIError(method=None, message=pesan)


class TestPapanDibuatPertamaKali:
    async def test_anggota_tanpa_papan_mendapat_pesan_baru_yang_disemat(self, seeded):
        session, admin = seeded["session"], seeded["admin"]
        assert admin.pinned_message_id is None
        bot = BotPalsu()

        await pin_service.perbarui_papan(bot, session, user=admin)

        assert bot.edit_dipanggil == []
        assert bot.kirim_dipanggil == [admin.telegram_id]
        assert len(bot.pin_dipanggil) == 1
        assert admin.pinned_message_id is not None


class TestPesanDihapusPengguna:
    """Pengguna bisa menghapus pesannya kapan saja; papan harus pulih."""

    async def test_papan_dibuat_ulang_bila_pesannya_sudah_tidak_ada(self, seeded):
        session, admin = seeded["session"], seeded["admin"]
        await user_repo.set_pinned_message_id(session, admin.id, 777)
        await session.commit()

        bot = BotPalsu(galat_edit=galat("Bad Request: message to edit not found"))
        await pin_service.perbarui_papan(bot, session, user=admin)

        assert bot.edit_dipanggil == [(admin.telegram_id, 777)]
        assert bot.kirim_dipanggil == [admin.telegram_id]
        assert admin.pinned_message_id != 777

    async def test_nomor_baru_tersimpan_di_database_bukan_hanya_di_memori(self, seeded):
        """Kalau hanya di memori, restart berikutnya menyunting pesan hantu."""
        session, admin = seeded["session"], seeded["admin"]
        await user_repo.set_pinned_message_id(session, admin.id, 777)
        await session.commit()

        bot = BotPalsu(galat_edit=galat("Bad Request: message to edit not found"))
        await pin_service.perbarui_papan(bot, session, user=admin)
        nomor_baru = admin.pinned_message_id
        await session.commit()
        session.expunge_all()

        dari_database = await user_repo.get_by_telegram_id(session, admin.telegram_id)
        assert dari_database.pinned_message_id == nomor_baru


class TestIsiTidakBerubah:
    """Telegram menolak penyuntingan yang isinya persis sama.

    Itu bukan kegagalan: papan sudah menampilkan angka yang benar. Mengirim
    pesan baru di situ justru membuat percakapan penuh pesan kembar.
    """

    async def test_tidak_mengirim_pesan_baru(self, seeded):
        session, admin = seeded["session"], seeded["admin"]
        await user_repo.set_pinned_message_id(session, admin.id, 888)
        await session.commit()

        bot = BotPalsu(
            galat_edit=galat("Bad Request: message is not modified")
        )
        await pin_service.perbarui_papan(bot, session, user=admin)

        assert bot.kirim_dipanggil == []
        assert admin.pinned_message_id == 888


class TestAnggotaBelumPernahChat:
    """Bot tidak bisa memulai percakapan lebih dulu.

    Anggota yang baru ditambahkan admin belum punya percakapan, dan anggota
    lain bisa saja memblokir bot. Keduanya tidak boleh menggagalkan apa pun.
    """

    async def test_kegagalan_ditelan_tanpa_melempar(self, seeded):
        session, member = seeded["session"], seeded["member"]
        bot = BotPalsu(
            galat_kirim=TelegramForbiddenError(
                method=None, message="Forbidden: bot can't initiate conversation with a user"
            )
        )

        await pin_service.perbarui_papan(bot, session, user=member)

        assert member.pinned_message_id is None

    async def test_satu_anggota_gagal_tidak_menghentikan_yang_lain(self, seeded):
        """Papan anggota lain tetap harus diperbarui."""
        session = seeded["session"]

        class BotSebagianGagal(BotPalsu):
            async def send_message(self, chat_id, text, **_):
                if chat_id == seeded["admin"].telegram_id:
                    raise TelegramForbiddenError(method=None, message="Forbidden")
                return await BotPalsu.send_message(self, chat_id, text)

        bot = BotSebagianGagal()
        await pin_service.perbarui_semua(bot, session)

        assert seeded["admin"].pinned_message_id is None
        assert seeded["member"].pinned_message_id is not None


class TestCakupanPembaruan:
    async def test_papan_semua_anggota_aktif_diperbarui(self, seeded):
        """Buku kas bersama: transaksi satu orang mengubah saldo semua."""
        session = seeded["session"]
        bot = BotPalsu()

        await pin_service.perbarui_semua(bot, session)

        assert sorted(bot.kirim_dipanggil) == sorted(
            [seeded["admin"].telegram_id, seeded["member"].telegram_id]
        )

    async def test_anggota_nonaktif_dilewati(self, seeded):
        session = seeded["session"]
        bot = BotPalsu()

        await pin_service.perbarui_semua(bot, session)

        assert seeded["nonaktif"].telegram_id not in bot.kirim_dipanggil


class TestIsiPapan:
    async def test_baris_pertama_memuat_saldo(self, seeded):
        from datetime import date

        from app.database.repositories import category_repo

        session, admin = seeded["session"], seeded["admin"]
        kategori = await category_repo.resolve(
            session, "Makan & Minum", TransactionType.EXPENSE
        )
        session.add(
            Transaction(
                amount=Decimal("25000"),
                transaction_type=TransactionType.EXPENSE,
                category_id=kategori.id,
                transaction_date=date.today(),
                description="uji",
                created_by=admin.id,
            )
        )
        await session.commit()

        from app.services import balance_service
        from app.utils.dates import JAKARTA, to_local, utc_now

        saldo = await balance_service.hitung_saldo(session)
        hari_ini = await balance_service.rekap_hari_ini(session)
        teks = pin_service.susun_teks(saldo, hari_ini, to_local(utc_now(), JAKARTA))

        baris_pertama = teks.splitlines()[0]
        assert "Rp975.000" in baris_pertama
        # Bilah sematan Telegram hanya menampilkan satu baris; baris pertama
        # harus tetap pendek agar tidak terpotong di tengah angka.
        assert len(baris_pertama) <= 60
