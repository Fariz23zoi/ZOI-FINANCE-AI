"""Penyiapan data laporan.

Service ini hanya mengumpulkan data; pembentukan workbook ada di
``app/excel/generator.py``. Pemisahan ini membuat generator Excel bisa diuji
tanpa database, dan service ini bisa diuji tanpa openpyxl.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Transaction, TransactionType, User
from app.database.repositories import settings_repo, transaction_repo
from app.services import balance_service, permission_service
from app.services.balance_service import BarisBulanan, RekapPeriode, Saldo


@dataclass
class DataLaporan:
    """Semua data yang dibutuhkan workbook lima sheet."""

    saldo: Saldo
    bulan_ini: RekapPeriode
    semua_transaksi: List[Transaction]
    pemasukan: List[Transaction]
    pengeluaran: List[Transaction]
    bulanan: List[BarisBulanan]
    mata_uang: str
    zona_waktu: str


async def kumpulkan(session: AsyncSession, *, user: User) -> DataLaporan:
    """Kumpulkan seluruh data laporan dari PostgreSQL.

    Selalu dari database, bukan dari cache: PostgreSQL adalah sumber kebenaran
    dan Excel hanya laporan yang dihasilkan darinya.
    """
    pengaturan = await settings_repo.get(session)
    if pengaturan is None:
        raise balance_service.PengaturanBelumAda(
            "Pengaturan buku kas belum ada. Jalankan alembic upgrade head."
        )

    permission_service.boleh_ekspor(user, bool(pengaturan.member_can_export))

    saldo = await balance_service.hitung_saldo(session)
    bulan_ini = await balance_service.rekap_bulan_ini(session)
    semua = await transaction_repo.list_all(session)
    bulanan = await balance_service.rekap_bulanan(session)

    return DataLaporan(
        saldo=saldo,
        bulan_ini=bulan_ini,
        semua_transaksi=semua,
        pemasukan=[t for t in semua if t.transaction_type == TransactionType.INCOME],
        pengeluaran=[t for t in semua if t.transaction_type == TransactionType.EXPENSE],
        bulanan=bulanan,
        mata_uang=pengaturan.currency,
        zona_waktu=pengaturan.timezone,
    )
