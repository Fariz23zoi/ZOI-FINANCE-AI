"""Alias titik masuk untuk panel hosting.

Banyak panel (termasuk Lunafy) memakai `main.py` sebagai nama file start
bawaannya. File ini ada supaya bot tetap jalan dengan pengaturan bawaan itu,
tanpa perlu mengubah apa pun di panel.

`run.py` dan `main.py` melakukan hal yang sama persis — pakai yang mana saja.
Logika aplikasinya ada di `app/main.py`.
"""

from run import main  # noqa: F401

if __name__ == "__main__":
    import asyncio

    from app.main import main as _main

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass
