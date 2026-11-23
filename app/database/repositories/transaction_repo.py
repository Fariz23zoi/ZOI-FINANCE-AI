"""Akses data transaksi.

Seluruh anggota membaca tabel yang sama: tidak ada filter per pengguna.
``created_by`` adalah atribusi, bukan pemisah data.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional, Sequence

from sqlalchemy import Select, and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.database.models import Transaction, TransactionStatus, TransactionType


def _aktif(stmt: Select) -> Select:
    """Batasi query pada transaksi berstatus aktif.

    Baris berstatus ``deleted`` tetap tersimpan (aturan ZOI #11: catatan
    keuangan tidak dibuang) tapi tidak ikut dihitung di saldo maupun laporan.
    """
    return stmt.where(Transaction.status == TransactionStatus.ACTIVE)


async def create(
    session: AsyncSession,
    *,
    transaction_type: TransactionType,
    amount: Decimal,
    category_id: int,
    transaction_date: date,
    created_by: int,
    description: Optional[str] = None,
    location: Optional[str] = None,
) -> Transaction:
    trx = Transaction(
        transaction_type=transaction_type,
        amount=amount,
        category_id=category_id,
        transaction_date=transaction_date,
        created_by=created_by,
        description=description,
        location=location,
        status=TransactionStatus.ACTIVE,
    )
    session.add(trx)
    await session.flush()
    return trx


async def get_by_id(
    session: AsyncSession, transaction_id: int, termasuk_terhapus: bool = False
) -> Optional[Transaction]:
    stmt = (
        select(Transaction)
        .options(joinedload(Transaction.category), joinedload(Transaction.creator))
        .where(Transaction.id == transaction_id)
    )
    if not termasuk_terhapus:
        stmt = _aktif(stmt)
    hasil = await session.execute(stmt)
    return hasil.unique().scalar_one_or_none()


async def list_by_date_range(
    session: AsyncSession,
    mulai: date,
    sampai: date,
    jenis: Optional[TransactionType] = None,
    limit: Optional[int] = None,
) -> List[Transaction]:
    """Transaksi aktif dalam rentang tanggal, inklusif di kedua ujung."""
    stmt = _aktif(
        select(Transaction)
        .options(joinedload(Transaction.category), joinedload(Transaction.creator))
        .where(Transaction.transaction_date >= mulai, Transaction.transaction_date <= sampai)
    ).order_by(Transaction.transaction_date.asc(), Transaction.id.asc())

    if jenis is not None:
        stmt = stmt.where(Transaction.transaction_type == jenis)
    if limit:
        stmt = stmt.limit(limit)

    hasil = await session.execute(stmt)
    return list(hasil.unique().scalars())


async def list_all(
    session: AsyncSession, jenis: Optional[TransactionType] = None
) -> List[Transaction]:
    """Seluruh transaksi aktif. Dipakai untuk laporan Excel."""
    stmt = _aktif(
        select(Transaction).options(
            joinedload(Transaction.category), joinedload(Transaction.creator)
        )
    ).order_by(Transaction.transaction_date.asc(), Transaction.id.asc())

    if jenis is not None:
        stmt = stmt.where(Transaction.transaction_type == jenis)

    hasil = await session.execute(stmt)
    return list(hasil.unique().scalars())


async def sum_by_type(
    session: AsyncSession, mulai: Optional[date] = None, sampai: Optional[date] = None
) -> dict:
    """Total pemasukan dan pengeluaran.

    Penjumlahan dilakukan PostgreSQL dengan NUMERIC, bukan di Python — tidak
    ada konversi float di jalur mana pun.

    :return: ``{"income": Decimal, "expense": Decimal, "count": int}``
    """
    syarat = [Transaction.status == TransactionStatus.ACTIVE]
    if mulai:
        syarat.append(Transaction.transaction_date >= mulai)
    if sampai:
        syarat.append(Transaction.transaction_date <= sampai)

    stmt = select(
        func.coalesce(
            func.sum(Transaction.amount).filter(
                Transaction.transaction_type == TransactionType.INCOME
            ),
            0,
        ),
        func.coalesce(
            func.sum(Transaction.amount).filter(
                Transaction.transaction_type == TransactionType.EXPENSE
            ),
            0,
        ),
        func.count(Transaction.id),
    ).where(and_(*syarat))

    pemasukan, pengeluaran, jumlah = (await session.execute(stmt)).one()
    return {
        "income": Decimal(str(pemasukan)),
        "expense": Decimal(str(pengeluaran)),
        "count": int(jumlah),
    }


async def monthly_summary(session: AsyncSession) -> List[dict]:
    """Rekap per bulan, terurut dari bulan terlama.

    Pengelompokan memakai ``EXTRACT(YEAR/MONTH)`` pada kolom DATE, BUKAN
    ``date_trunc``. Alasannya ditemukan lewat pengujian di PostgreSQL 16.15:

    ``date_trunc('month', <date>)`` memilih *overload* ``timestamptz``, bukan
    ``timestamp``. Hasilnya ``2026-10-01 00:00:00+07`` (memakai ``TimeZone``
    server), yang oleh asyncpg dikembalikan sebagai ``2026-09-30 17:00+00``.
    Memanggil ``.date()`` di atasnya menghasilkan **2026-09-30** — bulan
    September untuk transaksi bulan Oktober.

    Yang membuat bug ini berbahaya: ia hanya muncul bila ``TimeZone`` server
    bukan UTC. Di satu lingkungan rekapnya benar, di lingkungan lain
    label bulannya bergeser satu hari ke belakang tanpa pesan galat apa pun.

    ``EXTRACT`` bekerja langsung pada nilai DATE sehingga tidak ada konversi
    zona waktu sama sekali, dan hasilnya sama di PostgreSQL maupun SQLite.
    """
    tahun = func.extract("year", Transaction.transaction_date).label("tahun")
    bulan = func.extract("month", Transaction.transaction_date).label("bulan")

    stmt = (
        select(
            tahun,
            bulan,
            func.coalesce(
                func.sum(Transaction.amount).filter(
                    Transaction.transaction_type == TransactionType.INCOME
                ),
                0,
            ),
            func.coalesce(
                func.sum(Transaction.amount).filter(
                    Transaction.transaction_type == TransactionType.EXPENSE
                ),
                0,
            ),
            func.count(Transaction.id),
        )
        .where(Transaction.status == TransactionStatus.ACTIVE)
        .group_by(tahun, bulan)
        .order_by(tahun, bulan)
    )

    baris = (await session.execute(stmt)).all()
    hasil = []
    for th, bl, pemasukan, pengeluaran, jumlah in baris:
        hasil.append(
            {
                # Selalu tanggal 1 bulan tersebut: penanda bulan, bukan tanggal
                # transaksi. SQLite mengembalikan EXTRACT sebagai string, jadi
                # keduanya dilewatkan int() lebih dulu.
                "month": date(int(th), int(bl), 1),
                "income": Decimal(str(pemasukan)),
                "expense": Decimal(str(pengeluaran)),
                "count": int(jumlah),
            }
        )
    return hasil


async def find_possible_duplicate(
    session: AsyncSession,
    *,
    transaction_type: TransactionType,
    amount: Decimal,
    category_id: int,
    transaction_date: date,
    created_by: int,
    jendela_menit: int = 5,
) -> Optional[Transaction]:
    """Cari transaksi aktif yang hampir pasti duplikat.

    Kecocokan pada (jenis, jumlah, kategori, tanggal, pencatat) dalam jendela
    waktu singkat. Konsep ini ditiru dari alainrk/pago yang memperingatkan
    ketika transaksi baru mirip transaksi yang baru saja disimpan.

    Ini perlindungan terhadap kesalahan manusia (mengirim pesan yang sama dua
    kali), dan BUKAN pengganti proteksi klik-ganda. Klik ganda ditangani di
    tingkat database oleh ``pending_repo.claim`` yang bersifat atomik.

    Catatan implementasi. Pembandingan ``created_at`` dilakukan di Python,
    bukan di klausa WHERE. Alasannya ditemukan lewat pengujian: ``created_at``
    memakai ``server_default=func.now()``, yang di PostgreSQL menghasilkan
    ``timestamptz`` tetapi di SQLite menghasilkan string UTC tanpa zona.
    Membandingkannya di SQL dengan parameter datetime ber-zona membuat SQLite
    melakukan perbandingan string antara ``2026-11-23 01:50:00`` dan
    ``2026-11-23 08:45:00+07:00`` — selalu gagal, tanpa pesan error.

    Karena hanya satu baris terakhir yang diambil, memindahkan pembandingan
    ke Python tidak menambah biaya query dan membuat perilakunya sama di
    kedua backend.
    """
    stmt = _aktif(
        select(Transaction).where(
            Transaction.transaction_type == transaction_type,
            Transaction.amount == amount,
            Transaction.category_id == category_id,
            Transaction.transaction_date == transaction_date,
            Transaction.created_by == created_by,
        )
    ).order_by(Transaction.id.desc())

    hasil = await session.execute(stmt.limit(1))
    kandidat = hasil.scalar_one_or_none()

    if kandidat is None or kandidat.created_at is None:
        return None

    dibuat = kandidat.created_at
    if dibuat.tzinfo is None:
        # SQLite (dan PostgreSQL bila kolomnya tanpa zona): nilai tersimpan
        # dalam UTC.
        dibuat = dibuat.replace(tzinfo=timezone.utc)

    umur = datetime.now(timezone.utc) - dibuat
    if umur <= timedelta(minutes=jendela_menit):
        return kandidat

    return None


async def apply_update(
    session: AsyncSession, transaction_id: int, updated_by: int, **nilai
) -> bool:
    """Ubah transaksi aktif. True bila ada baris yang terubah.

    Dilakukan lewat ORM, bukan dengan ``UPDATE`` massal. Alasannya ditemukan
    lewat pengujian: UPDATE massal memperbarui kolom ``category_id`` di memori,
    tetapi **relasi** ``Transaction.category`` yang sudah termuat tetap
    menunjuk ke kategori lama. Pemanggil yang menampilkan hasilnya karena itu
    akan memberi tahu pengguna "transaksi diperbarui" sambil menampilkan
    kategori yang belum berubah — salah tanpa pesan error.

    ``refresh`` dipanggil eksplisit untuk relasi yang terpengaruh. Di
    SQLAlchemy async, relasi yang kedaluwarsa tidak bisa dimuat ulang secara
    implisit saat diakses, jadi pemuatannya harus diminta di sini.
    """
    nilai = {k: v for k, v in nilai.items() if v is not None}
    if not nilai:
        return False

    trx = await session.get(Transaction, transaction_id)
    if trx is None or trx.status != TransactionStatus.ACTIVE:
        return False

    for kolom, v in nilai.items():
        setattr(trx, kolom, v)
    trx.updated_by = updated_by

    await session.flush()

    if "category_id" in nilai:
        await session.refresh(trx, ["category"])

    return True


async def soft_delete(session: AsyncSession, transaction_id: int, updated_by: int) -> bool:
    """Tandai transaksi sebagai terhapus tanpa membuang barisnya.

    Syarat ``status == ACTIVE`` membuat operasi ini idempoten: menghapus dua
    kali tidak mengubah apa pun pada percobaan kedua dan mengembalikan False,
    sehingga pemanggil bisa membalas dengan jujur.
    """
    hasil = await session.execute(
        update(Transaction)
        .where(Transaction.id == transaction_id, Transaction.status == TransactionStatus.ACTIVE)
        .values(status=TransactionStatus.DELETED, updated_by=updated_by)
    )
    return bool(hasil.rowcount)


async def list_recent(
    session: AsyncSession, limit: int = 10, created_by: Optional[int] = None
) -> Sequence[Transaction]:
    """Transaksi aktif terbaru, untuk dipilih saat edit atau hapus.

    ``created_by`` menyaring per pencatat. Dipakai pada alur /edit untuk
    member: mereka hanya boleh mengubah catatannya sendiri, jadi menampilkan
    transaksi anggota lain di daftar pilihan hanya akan berujung penolakan.
    Penyaringan di sini soal UX; hak aksesnya tetap ditegakkan di
    ``app/services/permission_service.py``.
    """
    stmt = _aktif(
        select(Transaction).options(
            joinedload(Transaction.category), joinedload(Transaction.creator)
        )
    )
    if created_by is not None:
        stmt = stmt.where(Transaction.created_by == created_by)

    hasil = await session.execute(stmt.order_by(Transaction.id.desc()).limit(limit))
    return list(hasil.unique().scalars())
