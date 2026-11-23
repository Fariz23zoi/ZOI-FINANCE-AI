"""Bentuk data hasil parsing, dipakai bersama oleh ketiga tingkat AI."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from app.database.models import TransactionType


@dataclass
class ParsedTransaction:
    """Hasil parsing satu pesan menjadi calon transaksi.

    ``sumber`` mencatat tingkat mana yang menghasilkannya (``parser``,
    ``openrouter``, ``gemini``, atau ``manual``). Nilai ini disimpan di
    ``pending_transactions.parsed_data`` sehingga kita bisa menilai ketepatan
    tiap tingkat dari data nyata, bukan dari dugaan.
    """

    transaction_type: Optional[TransactionType] = None
    amount: Optional[Decimal] = None
    category: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    transaction_date: Optional[date] = None
    sumber: str = "parser"
    #: Field yang tidak berhasil ditentukan dan perlu ditanyakan ke pengguna.
    kurang: list = field(default_factory=list)

    @property
    def lengkap(self) -> bool:
        """True bila cukup untuk ditawarkan sebagai konfirmasi.

        Kategori, deskripsi, dan lokasi sengaja TIDAK diwajibkan: kategori
        punya tujuan aman "Lain-lain", dan dua sisanya opsional. Yang wajib
        hanyalah jenis dan jumlah — tanpa keduanya transaksi tidak bermakna.
        """
        return self.transaction_type is not None and self.amount is not None and self.amount > 0

    def to_json(self) -> dict:
        """Bentuk siap simpan ke kolom JSONB.

        Decimal dan date diubah ke string karena JSON tidak punya tipe untuk
        keduanya. Decimal dikirim sebagai string, BUKAN float, supaya nilai
        uang tidak kehilangan presisi saat bolak-balik ke database.
        """
        data = asdict(self)
        data["transaction_type"] = (
            self.transaction_type.value if self.transaction_type else None
        )
        data["amount"] = str(self.amount) if self.amount is not None else None
        data["transaction_date"] = (
            self.transaction_date.isoformat() if self.transaction_date else None
        )
        return data

    @classmethod
    def from_json(cls, data: dict) -> "ParsedTransaction":
        """Baca kembali dari kolom JSONB."""
        jenis = data.get("transaction_type")
        jumlah = data.get("amount")
        tanggal = data.get("transaction_date")

        return cls(
            transaction_type=TransactionType(jenis) if jenis else None,
            amount=Decimal(jumlah) if jumlah is not None else None,
            category=data.get("category"),
            description=data.get("description"),
            location=data.get("location"),
            transaction_date=date.fromisoformat(tanggal) if tanggal else None,
            sumber=data.get("sumber", "parser"),
            kurang=list(data.get("kurang") or []),
        )
