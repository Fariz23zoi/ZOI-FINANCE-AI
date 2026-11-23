"""Perhitungan saldo dan rekap.

Saldo TIDAK pernah disimpan sebagai kolom — selalu dihitung dari data. Kolom
saldo yang disimpan bisa menyimpang dari transaksinya tanpa gejala, dan pada
buku kas bersama penyimpangan seperti itu mustahil dijelaskan.

Penjumlahan dilakukan PostgreSQL dengan NUMERIC, bukan di Python.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories import settings_repo, transaction_repo
from app.utils.dates import local_today, month_bounds


class PengaturanBelumAda(Exception):
    """Baris account_settings tidak ada — migrasi 002 belum dijalankan.

    Dilempar, bukan ditebak dengan nilai default: saldo awal yang ditebak akan
    membuat seluruh saldo salah tanpa ada yang menyadarinya.
    """


@dataclass
class Saldo:
    saldo_awal: Decimal
    total_pemasukan: Decimal
    total_pengeluaran: Decimal
    jumlah_transaksi: int

    @property
    def saldo_sekarang(self) -> Decimal:
        """saldo_awal + total pemasukan − total pengeluaran."""
        return self.saldo_awal + self.total_pemasukan - self.total_pengeluaran


@dataclass
class RekapPeriode:
    mulai: date
    sampai: date
    pemasukan: Decimal
    pengeluaran: Decimal
    jumlah_transaksi: int

    @property
    def selisih(self) -> Decimal:
        return self.pemasukan - self.pengeluaran


@dataclass
class BarisBulanan:
    bulan: date
    pemasukan: Decimal
    pengeluaran: Decimal
    jumlah_transaksi: int
    saldo_akhir: Decimal

    @property
    def selisih(self) -> Decimal:
        return self.pemasukan - self.pengeluaran


async def _saldo_awal(session: AsyncSession) -> Decimal:
    pengaturan = await settings_repo.get(session)
    if pengaturan is None:
        raise PengaturanBelumAda(
            "Pengaturan buku kas belum ada. Jalankan migrasi database "
            "(alembic upgrade head) sebelum memakai bot."
        )
    return Decimal(str(pengaturan.initial_balance))


async def hitung_saldo(session: AsyncSession) -> Saldo:
    """Saldo bersama saat ini."""
    awal = await _saldo_awal(session)
    total = await transaction_repo.sum_by_type(session)

    return Saldo(
        saldo_awal=awal,
        total_pemasukan=total["income"],
        total_pengeluaran=total["expense"],
        jumlah_transaksi=total["count"],
    )


async def rekap_periode(
    session: AsyncSession, mulai: date, sampai: date
) -> RekapPeriode:
    """Rekap untuk rentang tanggal, inklusif di kedua ujung."""
    total = await transaction_repo.sum_by_type(session, mulai=mulai, sampai=sampai)
    return RekapPeriode(
        mulai=mulai,
        sampai=sampai,
        pemasukan=total["income"],
        pengeluaran=total["expense"],
        jumlah_transaksi=total["count"],
    )


async def rekap_hari_ini(session: AsyncSession, hari_ini: Optional[date] = None) -> RekapPeriode:
    h = hari_ini or local_today()
    return await rekap_periode(session, h, h)


async def rekap_bulan_ini(session: AsyncSession, hari_ini: Optional[date] = None) -> RekapPeriode:
    h = hari_ini or local_today()
    awal, akhir = month_bounds(h)
    return await rekap_periode(session, awal, akhir)


async def rekap_bulanan(session: AsyncSession) -> List[BarisBulanan]:
    """Rekap seluruh bulan dengan saldo akhir berjalan.

    Saldo akhir dihitung kumulatif dari bulan terlama, dimulai dari saldo
    awal, sehingga baris terakhir selalu sama dengan saldo sekarang. Kalau
    keduanya berbeda, ada bug — dan itu diuji di tests/.
    """
    awal = await _saldo_awal(session)
    baris = await transaction_repo.monthly_summary(session)

    hasil: List[BarisBulanan] = []
    berjalan = awal

    for b in baris:
        berjalan = berjalan + b["income"] - b["expense"]
        hasil.append(
            BarisBulanan(
                bulan=b["month"],
                pemasukan=b["income"],
                pengeluaran=b["expense"],
                jumlah_transaksi=b["count"],
                saldo_akhir=berjalan,
            )
        )

    return hasil
