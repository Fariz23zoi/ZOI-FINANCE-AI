"""Model database ZOI FINANCE AI.

Rancangan lengkap beserta alasan setiap keputusan: docs/DATABASE.md.

Tiga aturan yang dipegang di seluruh file ini:

1. Uang memakai ``Numeric(18, 2)`` dengan anotasi ``Decimal`` — bukan ``float``.
   ``(18, 2)`` dipilih karena ``(15,2)`` dan ``(12,2)`` yang dipakai repo
   referensi terlalu sempit untuk Rupiah.
2. Relasi memakai ``ON DELETE RESTRICT``, bukan ``CASCADE``. Pada buku kas
   bersama, CASCADE berarti menghapus satu anggota melenyapkan transaksinya —
   dan saldo bersama berubah tanpa jejak.
3. Transaksi tidak pernah dihapus fisik; ``status`` diubah menjadi ``deleted``.
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

#: JSONB di PostgreSQL (bisa diindeks, lebih padat), JSON biasa di SQLite agar
#: seluruh test bisa berjalan di Termux tanpa PostgreSQL.
JSONType = JSON().with_variant(JSONB(), "postgresql")

#: Primary key 64-bit. Di SQLite harus dirender INTEGER, bukan BIGINT:
#: SQLite hanya memberi perilaku autoincrement pada kolom bertipe tepat
#: "INTEGER PRIMARY KEY". Dengan BIGINT, INSERT gagal dengan
#: "NOT NULL constraint failed" karena id tidak terisi sendiri — diverifikasi
#: langsung. SQLite menyimpan INTEGER sebagai 64-bit, jadi tidak ada
#: jangkauan yang hilang. Di PostgreSQL tetap BIGINT/BIGSERIAL.
BigPK = BigInteger().with_variant(Integer, "sqlite")


class Base(DeclarativeBase):
    """Kelas dasar deklaratif."""


# ── Enum ────────────────────────────────────────────────────────


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    MEMBER = "member"


class TransactionType(str, enum.Enum):
    INCOME = "income"
    EXPENSE = "expense"


class TransactionStatus(str, enum.Enum):
    ACTIVE = "active"
    DELETED = "deleted"


class PendingStatus(str, enum.Enum):
    WAITING = "waiting"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


# ── Tabel ───────────────────────────────────────────────────────


class User(Base):
    """Anggota yang berwenang mengakses buku kas bersama.

    Otorisasi memakai ``telegram_id`` numerik, bukan ``username`` — username
    bisa diganti kapan saja oleh pemiliknya sehingga tidak aman sebagai dasar
    otorisasi.

    Anggota yang keluar di-``is_active=False``, tidak dihapus, supaya
    ``Transaction.created_by`` pada transaksi lamanya tetap sah.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # BigInteger: Telegram ID melampaui jangkauan INTEGER.
    telegram_id: Mapped[int] = mapped_column(
        BigInteger, unique=True, nullable=False, index=True
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=UserRole.MEMBER,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    transactions_created: Mapped[List["Transaction"]] = relationship(
        back_populates="creator", foreign_keys="Transaction.created_by"
    )

    __table_args__ = (Index("ix_users_is_active", "is_active"),)

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN

    def __repr__(self) -> str:
        return f"<User id={self.id} telegram_id={self.telegram_id} role={self.role.value}>"


class Category(Base):
    """Kategori pemasukan atau pengeluaran.

    Kategori "Lain-lain" wajib ada di kedua jenis: itu tujuan aman ketika AI
    tidak yakin, sehingga pencatatan tidak pernah gagal hanya karena kategori
    tidak dikenal.
    """

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    transaction_type: Mapped[TransactionType] = mapped_column(
        SAEnum(TransactionType, name="transaction_type", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    transactions: Mapped[List["Transaction"]] = relationship(back_populates="category")

    __table_args__ = (
        UniqueConstraint("name", "transaction_type", name="uq_category_name_type"),
        Index("ix_categories_type_active", "transaction_type", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<Category id={self.id} name={self.name!r} type={self.transaction_type.value}>"


class Transaction(Base):
    """Satu catatan keuangan di buku kas bersama.

    Tidak ada kolom yang memisahkan data per pengguna: ``created_by`` adalah
    atribusi, bukan pemisah. Semua anggota membaca baris yang sama. Ini
    perbedaan inti dari RibasomR/finance-bot yang memfilter per ``user_id``.
    """

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)

    transaction_type: Mapped[TransactionType] = mapped_column(
        SAEnum(TransactionType, name="transaction_type", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # DATE, bukan TIMESTAMP: tanggal kalender menurut Asia/Jakarta.
    # Lihat app/utils/dates.py untuk alasannya (UTC+7 menggeser dini hari).
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)

    created_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    status: Mapped[TransactionStatus] = mapped_column(
        SAEnum(TransactionStatus, name="transaction_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=TransactionStatus.ACTIVE,
        server_default="active",
    )

    category: Mapped["Category"] = relationship(back_populates="transactions")
    creator: Mapped["User"] = relationship(
        back_populates="transactions_created", foreign_keys=[created_by]
    )
    updater: Mapped[Optional["User"]] = relationship(foreign_keys=[updated_by])

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
        CheckConstraint("amount <= 999999999999.99", name="ck_transactions_amount_max"),
        Index("ix_transactions_date", "transaction_date"),
        Index("ix_transactions_status", "status"),
        Index("ix_transactions_date_status", "transaction_date", "status"),
        Index("ix_transactions_type_status", "transaction_type", "status"),
        Index("ix_transactions_created_by", "created_by"),
        Index("ix_transactions_dup_check", "created_by", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<Transaction id={self.id} {self.transaction_type.value} "
            f"{self.amount} {self.status.value}>"
        )


class AccountSettings(Base):
    """Pengaturan buku kas — baris tunggal.

    ``CHECK (id = 1)`` memastikan tidak mungkin ada dua baris pengaturan yang
    saling bertentangan: saldo awal ganda akan membuat saldo salah tanpa gejala
    yang kelihatan.
    """

    __tablename__ = "account_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    initial_balance: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="IDR", server_default="IDR"
    )
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="Asia/Jakarta", server_default="Asia/Jakarta"
    )
    member_can_export: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (CheckConstraint("id = 1", name="ck_account_settings_singleton"),)


class PendingTransaction(Base):
    """Transaksi hasil parsing yang menunggu konfirmasi pengguna.

    Disimpan di database, bukan di FSM memori aiogram. Alasannya: proses bot
    bisa restart kapan saja — di Lunafy, dependensi dipasang ulang setiap start
    dan server gratis diperbarui tiap 7 hari. Dengan FSM memori, data parsing
    hilang dan tombol konfirmasi menjadi mati tanpa penjelasan.

    ``source_text`` menyimpan pesan asli — aturan ZOI: jangan membuang pesan
    pengguna. Berguna juga saat ada selisih dan kita perlu tahu apa yang
    sebenarnya ditulis anggota.
    """

    __tablename__ = "pending_transactions"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    parsed_data: Mapped[dict] = mapped_column(JSONType, nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[PendingStatus] = mapped_column(
        SAEnum(PendingStatus, name="pending_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=PendingStatus.WAITING,
        server_default="waiting",
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    transaction_id: Mapped[Optional[int]] = mapped_column(
        BigPK, ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_pending_user_status", "telegram_user_id", "status"),
        Index("ix_pending_status_expires", "status", "expires_at"),
    )

    def __repr__(self) -> str:
        return f"<PendingTransaction id={self.id} status={self.status.value}>"


class AuditLog(Base):
    """Jejak audit setiap perubahan yang menyentuh uang atau hak akses.

    Sengaja TANPA foreign key pada ``user_id`` dan ``transaction_id``.
    Jejak audit harus bertahan lebih lama dari baris yang dirujuknya: FK
    dengan CASCADE akan menghapus bukti, sedangkan FK dengan RESTRICT akan
    memblokir operasi administratif yang sah. Nilainya disimpan apa adanya
    sebagai catatan sejarah, bukan relasi hidup.

    ``telegram_id`` tetap dicatat meski orang itu tidak ada di ``users`` —
    itu satu-satunya cara mengetahui ada yang mencoba masuk tanpa izin.
    """

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    transaction_id: Mapped[Optional[int]] = mapped_column(BigPK, nullable=True)
    details: Mapped[Optional[dict]] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_audit_created_at", "created_at"),
        Index("ix_audit_action", "action"),
        Index("ix_audit_transaction", "transaction_id"),
    )

    def __repr__(self) -> str:
        return f"<AuditLog id={self.id} action={self.action!r}>"


class AuditAction:
    """Nama aksi audit yang dikenali. Bukan enum DB supaya aksi baru tidak
    memerlukan migrasi."""

    TRANSACTION_CREATE = "transaction_create"
    TRANSACTION_UPDATE = "transaction_update"
    TRANSACTION_DELETE = "transaction_delete"
    MEMBER_ADD = "member_add"
    MEMBER_UPDATE = "member_update"
    MEMBER_DEACTIVATE = "member_deactivate"
    SETTINGS_UPDATE = "settings_update"
    UNAUTHORIZED_ACCESS = "unauthorized_access"
    EXPORT_GENERATED = "export_generated"
    AI_PROVIDER_FAILURE = "ai_provider_failure"
    QUOTA_WARNING = "quota_warning"
