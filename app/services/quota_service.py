"""Pemantauan kuota database.

Batas yang dipantau adalah **ukuran database** pada Supabase paket Free:
begitu melewati **500 MB**, proyek masuk **read-only mode**. Itu bukan sekadar
melambat — penulisan berhenti, sehingga transaksi baru tidak bisa disimpan.
Aturan ZOI bagian 7: peringatkan administrator sebelum itu terjadi, jangan
diam-diam kehilangan atau merusak data keuangan.

Perhatikan bedanya: Supabase memberi 1 GB *disk*, tetapi read-only dipicu oleh
kuota *ukuran database* 500 MB. Yang kita ukur adalah yang kedua, lewat
``pg_database_size()``.

Diperiksa saat ada aktivitas (/saldo dan /excel), bukan lewat penjadwal
terpisah: bot ini satu proses tanpa HTTP, dan menambah penjadwal berarti
menambah hal yang bisa gagal tanpa diketahui.
"""

from __future__ import annotations

import time
from typing import Optional

from app.config import get_settings
from app.database.models import AuditAction, User
from app.database.repositories import audit_repo, user_repo
from app.database.session import database_size_bytes, session_scope
from app.utils.logger import get_logger

logger = get_logger(__name__)

#: Ambang read-only Supabase paket Free: ukuran database 500 MB.
BATAS_BYTE = 500 * 1024 * 1024

AMBANG_PERINGATAN = 0.70
AMBANG_MENDESAK = 0.90

#: Jangan mengirim peringatan yang sama berulang kali dalam sehari.
JEDA_PERINGATAN = 86400.0
_terakhir_diperingatkan: dict = {}


def _format_byte(n: int) -> str:
    for satuan in ("B", "KB", "MB", "GB"):
        if n < 1024 or satuan == "GB":
            return f"{n:.1f} {satuan}" if satuan != "B" else f"{n} B"
        n /= 1024.0
    return f"{n:.1f} GB"


async def periksa_dan_peringatkan(bot, pemicu: Optional[User] = None) -> Optional[float]:
    """Periksa pemakaian disk; peringatkan admin bila melewati ambang.

    Kegagalan pemeriksaan TIDAK boleh mengganggu perintah yang sedang
    dijalankan pengguna — pemantauan adalah tambahan, bukan jalur utama.

    :return: rasio pemakaian (0..1), atau None bila tidak bisa diperiksa.
    """
    try:
        ukuran = await database_size_bytes()
    except Exception:  # pragma: no cover
        return None

    if ukuran is None:
        return None

    rasio = ukuran / BATAS_BYTE

    if rasio < AMBANG_PERINGATAN:
        return rasio

    mendesak = rasio >= AMBANG_MENDESAK
    kunci = "mendesak" if mendesak else "peringatan"

    sekarang = time.monotonic()
    if sekarang - _terakhir_diperingatkan.get(kunci, 0.0) < JEDA_PERINGATAN:
        return rasio
    _terakhir_diperingatkan[kunci] = sekarang

    teks = "\n".join([
        "🚨 <b>Database hampir read-only</b>" if mendesak
        else "⚠️ <b>Peringatan ukuran database</b>",
        "",
        f"Terpakai: <b>{_format_byte(ukuran)}</b> dari {_format_byte(BATAS_BYTE)} "
        f"({rasio * 100:.1f}%)",
        "",
        "Supabase paket Free mengubah proyek menjadi <b>read-only</b> bila "
        "ukuran database melewati 500 MB. Catatan lama tetap bisa dibaca, "
        "tetapi transaksi baru <b>tidak akan bisa disimpan</b>.",
        "",
        "Langkah yang disarankan:",
        "1. Jalankan /excel dan simpan filenya sebagai salinan.",
        "2. Buat backup: <code>pg_dump \"$DATABASE_URL\" -Fc -f zoi.dump</code>",
        "3. Periksa pertumbuhan tabel audit_logs dan pending_transactions.",
        "4. Bila perlu, naikkan paket Supabase sebelum batas tercapai.",
    ])

    logger.warning("Kuota database %.1f%% terpakai (%s).", rasio * 100, _format_byte(ukuran))

    async with session_scope() as session:
        admins = [u for u in await user_repo.list_all(session, hanya_aktif=True) if u.is_admin]
        await audit_repo.log(
            session,
            action=AuditAction.QUOTA_WARNING,
            user_id=pemicu.id if pemicu else None,
            telegram_id=pemicu.telegram_id if pemicu else None,
            details={"ukuran_byte": ukuran, "rasio": round(rasio, 4)},
        )
        sasaran = [a.telegram_id for a in admins]

    for tid in sasaran:
        try:
            await bot.send_message(tid, teks)
        except Exception as exc:  # pragma: no cover
            from app.utils.sanitizer import sanitize_exception

            logger.warning("Gagal mengirim peringatan kuota: %s", sanitize_exception(exc))

    return rasio
