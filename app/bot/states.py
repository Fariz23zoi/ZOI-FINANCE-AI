"""State FSM aiogram.

FSM dipakai HANYA untuk mengingat "field apa yang sedang diedit" dan untuk
alur /catat terpandu. Data transaksi itu sendiri TIDAK disimpan di FSM —
tempatnya di tabel ``pending_transactions``, supaya tidak hilang saat proses
bot di-restart — dan di Lunafy, restart adalah hal biasa karena dependensi
dipasang ulang setiap start dan server gratis diperbarui tiap 7 hari. Lihat docs/ARCHITECTURE.md bagian 4.
"""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class EditPending(StatesGroup):
    """Menunggu nilai baru untuk satu field pending."""

    menunggu_jumlah = State()
    menunggu_keterangan = State()
    menunggu_tanggal = State()
    menunggu_lokasi = State()


class CatatManual(StatesGroup):
    """Alur /catat terpandu, untuk saat AI tidak tersedia atau tidak dipakai."""

    pilih_jenis = State()
    isi_jumlah = State()
    pilih_kategori = State()
    isi_keterangan = State()


class TambahAnggota(StatesGroup):
    menunggu_id = State()
    menunggu_nama = State()


class EditTransaksi(StatesGroup):
    """Mengubah transaksi yang SUDAH tersimpan.

    Dipisahkan dari ``EditPending``: yang itu mengubah calon transaksi yang
    belum masuk buku kas, yang ini mengubah catatan keuangan yang sudah
    memengaruhi saldo — jadi setiap perubahannya menulis ke ``audit_logs``.
    """

    menunggu_jumlah = State()
    menunggu_keterangan = State()
    menunggu_tanggal = State()
    menunggu_lokasi = State()
