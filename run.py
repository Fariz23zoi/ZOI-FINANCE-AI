"""Titik masuk ZOI FINANCE AI.

Dipakai baik di Termux (`python run.py`) maupun di panel Lunafy.

`main.py` di akar repo adalah alias file ini, untuk panel yang memakai
`main.py` sebagai nama file start bawaannya.
"""
import asyncio

from app.main import main

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
