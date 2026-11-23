"""Handler bot.

URUTAN PENDAFTARAN PENTING. ``catat.teks_biasa`` menangkap semua pesan teks
yang bukan perintah, jadi router ``catat`` harus didaftarkan PALING AKHIR —
kalau tidak, ia akan menelan masukan yang sedang ditunggu alur FSM lain
(misalnya /catat terpandu atau edit pending).
"""

from app.bot.handlers import admin, catat, edit, laporan, manual, umum  # noqa: F401

#: Urutan pendaftaran ke Dispatcher. Jangan diubah tanpa membaca catatan di atas.
ROUTERS = (
    umum.router,
    manual.router,
    laporan.router,
    edit.router,
    admin.router,
    catat.router,  # harus terakhir
)
