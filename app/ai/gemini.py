"""Provider AI cadangan: Google Gemini, free tier.

Dipakai hanya ketika OpenRouter gagal atau kuotanya habis. Gemini tidak
memakai penanda nama ":free" seperti OpenRouter; batas gratisnya ditentukan
oleh tier akun, bukan oleh nama model. Karena itu penjagaan di sini berupa
daftar model yang dikonfigurasi admin (GEMINI_MODELS) — aturannya tetap sama:
tidak ada eskalasi otomatis dan tidak ada pengaktifan billing dari dalam kode.
"""

from __future__ import annotations

import httpx

from app.ai.errors import (
    AIConfigError,
    AIInvalidResponse,
    AIQuotaExceeded,
    AITemporaryError,
)
from app.ai.prompt import SYSTEM_PROMPT
from app.utils.logger import get_logger
from app.utils.sanitizer import sanitize_exception

logger = get_logger(__name__)

NAMA = "gemini"
BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


async def minta(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    model: str,
    prompt: str,
    timeout: float = 12.0,
) -> str:
    """Kirim satu permintaan ke Gemini dan kembalikan isi jawabannya.

    Kunci API dikirim lewat header ``x-goog-api-key``, bukan lewat query
    string ``?key=``. Alasannya: URL sering ikut tercatat di log klien HTTP,
    sehingga kunci di query string mudah bocor ke log.
    """
    if not api_key:
        raise AIConfigError("GEMINI_API_KEY belum diatur.")
    if not model:
        raise AIConfigError("Nama model Gemini kosong.")

    try:
        resp = await client.post(
            f"{BASE_URL}/models/{model}:generateContent",
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
            json={
                "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.0,
                    "maxOutputTokens": 400,
                    # Gemini bisa menjamin JSON di sisi server. Ini menghapus
                    # sumber kegagalan yang paling sering pada model gratis:
                    # jawaban yang dibungkus markdown fence.
                    "responseMimeType": "application/json",
                },
            },
            timeout=timeout,
        )
    except httpx.TimeoutException as exc:
        raise AITemporaryError(f"Gemini timeout setelah {timeout}s") from exc
    except httpx.HTTPError as exc:
        raise AITemporaryError(f"Gemini tidak terjangkau: {sanitize_exception(exc)}") from exc

    if resp.status_code == 200:
        return _ambil_isi(resp.json())

    cuplikan = resp.text[:200]

    if resp.status_code in (401, 403):
        raise AIConfigError(
            f"Gemini menolak kunci API (HTTP {resp.status_code}). Periksa GEMINI_API_KEY."
        )
    if resp.status_code == 429:
        raise AIQuotaExceeded("Kuota / rate limit Gemini free tier habis (HTTP 429).")
    if resp.status_code == 404:
        raise AIConfigError(
            f"Model Gemini {model!r} tidak ditemukan. Perbarui GEMINI_MODELS."
        )
    if 500 <= resp.status_code < 600:
        raise AITemporaryError(f"Gemini galat server (HTTP {resp.status_code}).")

    logger.warning("Gemini HTTP %s: %s", resp.status_code, cuplikan)
    raise AITemporaryError(f"Gemini galat tak terduga (HTTP {resp.status_code}).")


def _ambil_isi(data: dict) -> str:
    """Ambil teks jawaban dari bentuk respons Gemini."""
    kandidat = data.get("candidates")

    if not kandidat:
        # Gemini menolak permintaan lewat promptFeedback, bukan lewat status
        # HTTP. Tanpa penanganan ini, penolakan terlihat seperti jawaban kosong.
        umpan = data.get("promptFeedback") or {}
        alasan = umpan.get("blockReason")
        if alasan:
            raise AIInvalidResponse(f"Gemini menolak permintaan: {alasan}")
        raise AIInvalidResponse("Respons Gemini tidak memuat 'candidates'.")

    pertama = kandidat[0]

    alasan_selesai = pertama.get("finishReason")
    if alasan_selesai in ("SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT"):
        raise AIInvalidResponse(f"Gemini menghentikan jawaban: {alasan_selesai}")

    bagian = (pertama.get("content") or {}).get("parts") or []
    isi = "".join(b.get("text", "") for b in bagian).strip()

    if not isi:
        if alasan_selesai == "MAX_TOKENS":
            raise AIInvalidResponse("Jawaban Gemini terpotong (MAX_TOKENS).")
        raise AIInvalidResponse("Gemini mengembalikan jawaban kosong.")

    return isi
