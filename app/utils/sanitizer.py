"""Penyamaran data sensitif sebelum masuk log.

Diadaptasi dari RibasomR/finance-bot (MIT, Copyright (c) 2025-2026 RibasomR).
Lihat docs/THIRD_PARTY_NOTICES.md. Komentar diterjemahkan dan pola disesuaikan
untuk kebutuhan ZOI (token bot Telegram, URL asyncpg).

Aturan ZOI #7: secret tidak boleh pernah muncul di log, dokumentasi, pesan
Telegram, atau kode. Modul ini adalah penjaga terakhir — setiap pesan exception
dan setiap URL dilewatkan ke sini sebelum dicatat.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable

#: Nama kunci yang nilainya dianggap rahasia.
KUNCI_SENSITIF = frozenset({
    "token", "apikey", "apisecret", "password", "passwd", "pwd", "secret",
    "authorization", "auth", "bottoken", "telegrambottoken", "openrouterapikey",
    "geminiapikey", "databaseurl", "accesstoken", "refreshtoken", "privatekey",
    "secretkey", "pgpassword", "pin", "otp", "cvv",
})


def mask(value: str, visible: int = 4, char: str = "*") -> str:
    """Samarkan nilai, sisakan beberapa karakter awal untuk identifikasi.

    Panjang asli tidak dipertahankan: topengnya dibatasi 12 karakter supaya
    panjang secret tidak ikut terbocor lewat log.

    Example:
        >>> mask("sk-or-v1-abcdef123456")
        'sk-o************'
    """
    if not value or not isinstance(value, str):
        return "***"
    if len(value) <= visible:
        return char * len(value)
    return value[:visible] + char * min(len(value) - visible, 12)


def sanitize_url(url: str) -> str:
    """Samarkan kredensial yang tertanam di URL.

    Example:
        >>> sanitize_url("postgresql+asyncpg://admin:rahasia@pooler.supabase.com:5432/zoi")
        'postgresql+asyncpg://admin:***@pooler.supabase.com:5432/zoi'
    """
    if not url or not isinstance(url, str):
        return "***"
    return re.sub(r"([\w+.-]+://)([^:/@\s]*)(:[^@\s]+)?@", r"\1\2:***@", url)


def sanitize_dict(data: Dict[str, Any], kunci: Iterable[str] = KUNCI_SENSITIF) -> Dict[str, Any]:
    """Salin dict dengan nilai dari kunci sensitif disamarkan (rekursif)."""
    if not isinstance(data, dict):
        return data

    kunci = frozenset(kunci)
    hasil: Dict[str, Any] = {}
    for k, v in data.items():
        knorm = str(k).lower().replace("_", "").replace("-", "")
        sensitif = any(s in knorm for s in kunci)

        if sensitif and isinstance(v, str):
            hasil[k] = mask(v)
        elif isinstance(v, dict):
            hasil[k] = sanitize_dict(v, kunci)
        elif isinstance(v, list):
            hasil[k] = [sanitize_dict(i, kunci) if isinstance(i, dict) else i for i in v]
        else:
            hasil[k] = v
    return hasil


def sanitize_text(text: str) -> str:
    """Samarkan pola yang menyerupai secret di dalam teks bebas.

    Dipakai pada pesan exception dan potongan respons API yang akan dicatat.
    Urutan pemrosesan penting: token Telegram diproses lebih dulu karena
    formatnya khas, lalu kredensial URL, baru deret panjang yang generik.
    """
    if not text or not isinstance(text, str):
        return str(text)

    hasil = text

    # Token bot Telegram: "123456789:AAE..." — bentuknya sangat khas.
    hasil = re.sub(r"\b(\d{6,12}):([A-Za-z0-9_-]{30,})", r"\1:***", hasil)

    # Kredensial di URL.
    hasil = re.sub(r"([\w+.-]+://)([^:/@\s]*)(:[^@\s]+)@", r"\1\2:***@", hasil)

    # Kunci API dengan awalan yang dikenal.
    hasil = re.sub(r"\b(sk-[A-Za-z0-9_-]{8,}|AIza[A-Za-z0-9_-]{10,})", lambda m: mask(m.group(1)), hasil)

    # Deret alfanumerik panjang yang generik.
    hasil = re.sub(r"\b([A-Za-z0-9_-]{32,})\b", lambda m: mask(m.group(1), visible=6), hasil)

    return hasil


def sanitize_exception(exc: BaseException) -> str:
    """Pesan exception yang aman dicatat, lengkap dengan nama tipenya."""
    return f"{type(exc).__name__}: {sanitize_text(str(exc))}"
