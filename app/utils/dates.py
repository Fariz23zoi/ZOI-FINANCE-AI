"""Tanggal dan waktu.

Aturan: simpan UTC, tampilkan Asia/Jakarta.

Ini penting karena Jakarta UTC+7: pukul 00:00–07:00 Jakarta masih "hari
sebelumnya" menurut UTC. Memakai ``date.today()`` dari UTC akan membuat
transaksi dini hari masuk ke hari yang salah — kesalahan yang hanya muncul
pada pengguna yang mencatat lewat tengah malam, jadi sulit ditemukan.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

JAKARTA = ZoneInfo("Asia/Jakarta")


def utc_now() -> datetime:
    """Waktu sekarang dalam UTC, selalu *timezone-aware*."""
    return datetime.now(timezone.utc)


def local_today(tz: ZoneInfo = JAKARTA) -> date:
    """Tanggal kalender hari ini menurut zona waktu lokal."""
    return datetime.now(tz).date()


def to_local(dt: datetime, tz: ZoneInfo = JAKARTA) -> datetime:
    """Konversi datetime ke zona lokal.

    Datetime tanpa zona dianggap UTC — pilihan yang aman karena seluruh
    database menyimpan UTC.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz)


_BULAN_ID = [
    "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]


def format_date_id(d: date) -> str:
    """Format tanggal gaya Indonesia.

    Example:
        >>> format_date_id(date(2026, 11, 23))
        '23 November 2026'
    """
    return f"{d.day} {_BULAN_ID[d.month - 1]} {d.year}"


def format_month_id(d: date) -> str:
    """Format bulan dan tahun.

    Example:
        >>> format_month_id(date(2026, 11, 23))
        'November 2026'
    """
    return f"{_BULAN_ID[d.month - 1]} {d.year}"


def format_datetime_id(dt: datetime, tz: ZoneInfo = JAKARTA) -> str:
    """Format datetime (dikonversi ke lokal) gaya Indonesia."""
    lokal = to_local(dt, tz)
    return f"{format_date_id(lokal.date())} {lokal:%H:%M}"


def parse_indonesian_date(text: str, today: Optional[date] = None) -> Optional[date]:
    """Baca tanggal dari tulisan Indonesia sehari-hari.

    Didukung: hari ini, kemarin, kemaren, tadi, lusa, besok, kemarin lusa,
    "N hari lalu", DD/MM, DD-MM-YYYY, DD MMMM YYYY, YYYY-MM-DD.

    Pola ini meniru pendekatan ``parse_user_date`` di nikamurkaa/finance-helper
    (regex deterministik untuk kata waktu relatif), ditulis ulang untuk bahasa
    Indonesia. Keuntungannya: bekerja tanpa biaya AI dan bisa diuji penuh.

    :return: date, atau None bila tidak ada tanggal yang dikenali.
    """
    if not text:
        return None

    hari_ini = today or local_today()
    t = text.lower().strip()

    if re.search(r"\bkemarin\s+lusa\b|\bkemaren\s+lusa\b", t):
        return hari_ini - timedelta(days=2)
    if re.search(r"\b(hari\s+ini|tadi(\s+(pagi|siang|sore|malam))?|sekarang)\b", t):
        return hari_ini
    if re.search(r"\b(kemarin|kemaren)\b", t):
        return hari_ini - timedelta(days=1)
    if re.search(r"\bbesok\b", t):
        return hari_ini + timedelta(days=1)
    if re.search(r"\blusa\b", t):
        return hari_ini + timedelta(days=2)

    m = re.search(r"\b(\d{1,3})\s+hari\s+(?:yang\s+)?lalu\b", t)
    if m:
        return hari_ini - timedelta(days=int(m.group(1)))

    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t)
    if m:
        return _aman(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    bulan_map = {b.lower(): i + 1 for i, b in enumerate(_BULAN_ID)}
    bulan_map.update({
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "mei": 5, "jun": 6,
        "jul": 7, "agu": 8, "agt": 8, "sep": 9, "okt": 10, "nov": 11, "des": 12,
    })
    m = re.search(r"\b(\d{1,2})\s+([a-z]+)(?:\s+(\d{4}))?\b", t)
    if m and m.group(2) in bulan_map:
        tahun = int(m.group(3)) if m.group(3) else hari_ini.year
        return _aman(tahun, bulan_map[m.group(2)], int(m.group(1)))

    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", t)
    if m:
        hari, bulan = int(m.group(1)), int(m.group(2))
        if m.group(3):
            tahun = int(m.group(3))
            if tahun < 100:
                tahun += 2000
        else:
            tahun = hari_ini.year
        return _aman(tahun, bulan, hari)

    return None


def _aman(tahun: int, bulan: int, hari: int) -> Optional[date]:
    """Bentuk date, kembalikan None bila kombinasinya tidak sah."""
    try:
        return date(tahun, bulan, hari)
    except ValueError:
        return None


def month_bounds(d: date) -> tuple[date, date]:
    """Tanggal pertama dan terakhir dari bulan yang memuat ``d``."""
    awal = d.replace(day=1)
    akhir = (awal + timedelta(days=31)).replace(day=1) - timedelta(days=1)
    return awal, akhir
