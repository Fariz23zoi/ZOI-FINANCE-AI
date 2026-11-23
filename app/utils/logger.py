"""Penyiapan logging.

Memakai ``logging`` dari pustaka standar, bukan loguru seperti finance-bot:
satu dependensi lebih sedikit untuk dipasang di Termux, dan kebutuhan kita
sederhana.

Keluaran hanya ke stdout, tidak ke file. Panel Lunafy menampilkan stdout di
konsolnya, sementara disk server hanya 512 MB — file log yang bertumbuh akan
bersaing dengan dependensi untuk ruang yang sama, dan ikut hilang saat server
dibuat ulang.

Untuk jejak jangka panjang, pakai tabel ``audit_logs`` di database: isinya
tidak kedaluwarsa dan tidak bergantung pada server.
"""

from __future__ import annotations

import logging
import sys


def setup_logging(level: str = "INFO") -> None:
    """Siapkan logging ke stdout dengan format ringkas."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # aiogram sangat cerewet di level INFO; httpx mencatat setiap permintaan
    # beserta URL-nya, yang bisa memuat kunci API pada beberapa provider.
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
