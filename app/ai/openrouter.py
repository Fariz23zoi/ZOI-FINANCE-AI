"""Provider AI utama: OpenRouter, hanya model gratis.

Penjagaan zero-cost berlapis. Lapisan di modul ini adalah pemeriksaan
per-permintaan: nama model diperiksa ULANG tepat sebelum ``POST``, meski
``app/config.py`` sudah menolak model non-gratis saat startup. Dua pemeriksaan
di dua tempat berbeda membuat tidak ada satu pun jalur kode yang bisa
mengirim permintaan ke model berbayar.
"""

from __future__ import annotations

from typing import List, Optional

import httpx

from app.ai.errors import (
    AIConfigError,
    AIInvalidResponse,
    AIQuotaExceeded,
    AITemporaryError,
)
from app.ai.prompt import SYSTEM_PROMPT
from app.utils.logger import get_logger
from app.utils.sanitizer import sanitize_exception, sanitize_text

logger = get_logger(__name__)

NAMA = "openrouter"
BASE_URL = "https://openrouter.ai/api/v1"

#: Penanda model gratis di OpenRouter.
SUFIKS_GRATIS = ":free"


def pastikan_model_gratis(model: str) -> None:
    """Pastikan model yang akan dipanggil adalah model gratis.

    :raises AIConfigError: bila nama model tidak berakhiran ``:free``.
    """
    if not model or not model.endswith(SUFIKS_GRATIS):
        raise AIConfigError(
            f"Model {model!r} bukan model gratis OpenRouter (harus berakhiran "
            f"'{SUFIKS_GRATIS}'). Permintaan dibatalkan."
        )


async def minta(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    model: str,
    prompt: str,
    timeout: float = 12.0,
) -> str:
    """Kirim satu permintaan ke OpenRouter dan kembalikan isi jawabannya.

    :return: teks jawaban model (belum diparse).
    :raises AIConfigError: kunci tidak ada, model tidak gratis, atau 401/403.
    :raises AIQuotaExceeded: HTTP 429 atau pesan kuota habis.
    :raises AITemporaryError: timeout, 5xx, atau galat jaringan.
    :raises AIInvalidResponse: bentuk jawaban tidak sesuai harapan.
    """
    if not api_key:
        raise AIConfigError("OPENROUTER_API_KEY belum diatur.")

    # Pemeriksaan kedua, tepat sebelum permintaan dikirim.
    pastikan_model_gratis(model)

    try:
        resp = await client.post(
            f"{BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                # Header ini diminta OpenRouter untuk atribusi aplikasi.
                "X-Title": "ZOI FINANCE AI",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                # temperature 0: ekstraksi data harus deterministik, bukan kreatif.
                "temperature": 0.0,
                "max_tokens": 400,
            },
            timeout=timeout,
        )
    except httpx.TimeoutException as exc:
        raise AITemporaryError(f"OpenRouter timeout setelah {timeout}s") from exc
    except httpx.HTTPError as exc:
        raise AITemporaryError(f"OpenRouter tidak terjangkau: {sanitize_exception(exc)}") from exc

    if resp.status_code == 200:
        return _ambil_isi(resp.json())

    # Potong respons: isinya bisa memuat echo permintaan kita.
    cuplikan = resp.text[:200]

    if resp.status_code in (401, 403):
        raise AIConfigError(
            f"OpenRouter menolak kunci API (HTTP {resp.status_code}). "
            "Periksa OPENROUTER_API_KEY."
        )
    if resp.status_code == 429:
        raise AIQuotaExceeded("OpenRouter rate limit / kuota gratis habis (HTTP 429).")
    if resp.status_code == 402:
        # 402 pada model :free berarti kuota gratis harian sudah habis.
        # Ini BUKAN alasan untuk pindah ke model berbayar.
        raise AIQuotaExceeded("Kuota gratis OpenRouter habis (HTTP 402).")
    if resp.status_code == 404:
        raise AIConfigError(
            f"Model {model!r} tidak ditemukan di OpenRouter. Ketersediaan model "
            "gratis berubah dari waktu ke waktu; perbarui OPENROUTER_MODELS."
        )
    if 500 <= resp.status_code < 600:
        raise AITemporaryError(f"OpenRouter galat server (HTTP {resp.status_code}).")

    logger.warning("OpenRouter HTTP %s: %s", resp.status_code, cuplikan)
    raise AITemporaryError(f"OpenRouter galat tak terduga (HTTP {resp.status_code}).")


def _ambil_isi(data: dict) -> str:
    """Ambil isi jawaban dari bentuk respons OpenAI-compatible."""
    pilihan: Optional[List[dict]] = data.get("choices")

    if not pilihan:
        # Beberapa model gratis mengembalikan error di dalam body HTTP 200.
        galat = data.get("error")
        if galat:
            # Pesan galat provider adalah teks dari luar; bisa saja memuat
            # echo permintaan kita. Disanitasi sebelum diteruskan ke log.
            pesan = sanitize_text(str(galat.get("message", galat))[:200])
            if "rate" in pesan.lower() or "quota" in pesan.lower() or "limit" in pesan.lower():
                raise AIQuotaExceeded(f"OpenRouter: {pesan}")
            raise AITemporaryError(f"OpenRouter: {pesan}")
        raise AIInvalidResponse("Respons OpenRouter tidak memuat 'choices'.")

    isi = (pilihan[0].get("message") or {}).get("content") or ""
    isi = isi.strip()

    if not isi:
        raise AIInvalidResponse("OpenRouter mengembalikan jawaban kosong.")
    return isi
