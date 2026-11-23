"""Exception untuk lapisan AI.

Dibedakan karena router bereaksi berbeda pada masing-masing: kuota habis
memicu cooldown, galat sementara memicu percobaan ulang, dan konfigurasi
salah tidak boleh dicoba ulang sama sekali.
"""

from __future__ import annotations


class AIError(Exception):
    """Dasar semua galat AI."""


class AIConfigError(AIError):
    """Konfigurasi salah — mis. kunci API tidak ada, model tidak gratis.

    TIDAK boleh dicoba ulang: mengulang permintaan dengan konfigurasi yang
    sama hanya membuang waktu dan kuota.
    """


class AITemporaryError(AIError):
    """Galat sementara — timeout, 5xx, jaringan. Layak dicoba ulang."""


class AIQuotaExceeded(AIError):
    """Kuota gratis habis atau rate limit provider (HTTP 429).

    Memicu cooldown: provider ini dilewati untuk beberapa waktu agar tidak
    dihujani permintaan yang pasti gagal. Aturan ZOI: jangan terus mengirim
    permintaan setelah kuota gratis habis.
    """


class AIInvalidResponse(AIError):
    """Provider menjawab, tapi jawabannya tidak bisa dipakai."""
