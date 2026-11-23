# REPOSITORY AUDIT — ZOI FINANCE AI

**Tagline:** Smart Finance. Simple Control.
**Fase:** PHASE 1 — Repository Audit
**Tanggal audit:** 23 November 2026
**Repo target:** https://github.com/Fariz23zoi/ZOI-FINANCE-AI

Audit ini dibuat dengan meng-*clone* kelima repositori lalu membaca **source code aslinya**
(model data, service, handler, middleware, migrasi, test, CI, lisensi, riwayat Git) —
bukan hanya README. Setiap klaim di bawah berasal dari file yang benar-benar dibaca.

---

> ## ⚠️ Adendum — 23 November 2026: platform hosting berubah
>
> Dokumen ini ditulis ketika rencananya memakai **Altare** untuk hosting dan
> database. Rencana itu dibatalkan. Susunan sekarang:
>
> | | Sebelumnya | Sekarang |
> |---|---|---|
> | Proses bot | Altare App Hosting | **Lunafy** |
> | PostgreSQL | Altare Postgres | **Supabase** |
>
> **Bagian 7 ("Kompatibilitas") sudah tidak berlaku** untuk angka-angka
> platformnya: batas 25 koneksi, disk 1 GB, retensi backup 3 hari, dan kuota
> cron semuanya milik Altare. Batas yang berlaku sekarang ada di
> `docs/DEPLOYMENT.md` bagian 2.
>
> Yang **tetap berlaku** dari bagian 7, karena menyangkut kode dan bukan
> platform:
>
> * Jebakan `sslmode` + asyncpg — Supabase juga memberi `?sslmode=require`,
>   jadi normalisasi URL tetap wajib. Ditambah satu temuan baru: pooler
>   *transaction mode* Supabase tidak mendukung prepared statements.
> * Keputusan satu proses dan *long polling* — di Lunafy alasannya bahkan lebih
>   kuat, karena web server tidak diizinkan dan port berbiaya bulanan.
> * Pool koneksi kecil, kini karena RAM 256 MB, bukan karena kuota koneksi.
> * Keharusan backup mandiri, dengan rantai kegagalan yang berbeda (lihat
>   `docs/DEPLOYMENT.md` bagian 8).
>
> Bagian 1–6 dan 8–10 — audit keempat repo referensi, lisensi, komponen yang
> dipakai ulang, dan keputusan membangun implementasi bersih — tidak terpengaruh
> sama sekali. Semuanya tentang kode, bukan tentang siapa yang meng-hosting.
>
> Dokumen ini sengaja **tidak** ditulis ulang: ia catatan keputusan pada
> tanggalnya, dan mengubahnya seolah Altare tidak pernah dipertimbangkan akan
> menghilangkan jejak alasan di balik beberapa pilihan desain yang masih
> berlaku.

---

## 1. Ringkasan Metode

| Repo | Commit | Update terakhir | File | LOC | Bahasa | Lisensi |
|---|---|---|---|---|---|---|
| `Fariz23zoi/ZOI-FINANCE-AI` | 1 | 2026-11-23 | 2 | 0 | — | **tidak ada** |
| `RibasomR/finance-bot` | 11 | 2026-04-05 | 66 | 9.591 | Python | MIT |
| `nikamurkaa/finance-helper` | 16 | 2026-09-09 | 82 | 9.033 | Python | MIT |
| `cenoff/Money-Bot` | 10 | 2025-11-12 | 27 | 2.058 | Python | MIT |
| `alainrk/pago` | 58 | 2026-11-16 | 287 | 16.150 | **Go + React** | MIT |

Pemeriksaan keamanan lintas repo:

- **Secret ter-commit:** tidak ditemukan di kelima repo. Riwayat Git juga bersih dari file `.env`.
- **SQL injection:** tidak ditemukan. Semua repo Python memakai ORM / *parameterized query*.
- **`eval` / `exec` / `os.system` / `shell=True`:** tidak ditemukan.

---

## 2. Kondisi Repo Saat Ini — `Fariz23zoi/ZOI-FINANCE-AI`

**Isi:** hanya `README.md` (2 baris) dan `.gitignore` (template Python standar GitHub). Satu commit: "Initial commit".

**Artinya untuk kita:**

- Tidak ada pekerjaan lama yang bisa tertimpa. Kita mulai dari kanvas kosong — aman.
- `.gitignore` bawaan **sudah** mengabaikan `.env`, `__pycache__/`, `*.log`, `venv/`.
  Yang masih perlu ditambahkan nanti: `.env.*`, `!.env.example`, dan `output/`.
- **Belum ada file LICENSE.** Ini harus ditangani sebelum kita memakai ulang kode MIT
  mana pun (lihat bagian 8).

---

## 3. `RibasomR/finance-bot` — kandidat terkuat

### Arsitektur

```
bot/
  handlers/     common, transactions, view, categories, export, settings, voice
  keyboards/    7 modul inline/reply keyboard
  middlewares/  error_handler, locale, rate_limit
  models/       base, user, transaction, category   (SQLAlchemy 2.x Mapped[])
  services/     ai_service, database, export_service
  states/       6 modul FSM state
  utils/        logger (loguru), sanitizer, validators
  locales/      en, ru
config/config.py  Pydantic Settings
alembic/          3 migrasi berurutan
```

Stack: `aiogram 3.13.1`, `SQLAlchemy 2.0.35` (async), `asyncpg`, `alembic`, `pydantic-settings`,
`openpyxl`, `httpx`, `loguru`, `redis` (rate limit), `aiosqlite` (dev).

**Ini hampir identik dengan stack pilihan ZOI FINANCE AI.**

### Kekuatan

1. **Uang disimpan benar.** `Numeric(precision=15, scale=2)` dengan `Mapped[Decimal]`, dan
   hasil parsing AI langsung dikonversi `Decimal(str(...))`. Sesuai aturan ZOI #10.
2. **Alur konfirmasi AI sudah ada dan persis seperti yang ZOI minta.** Di
   `handlers/voice.py`: transkripsi → parse → `state.set_state(waiting_confirmation)` →
   tampilkan ringkasan → tombol `voice:confirm` / `voice:edit` / `cancel`. Transaksi baru
   ditulis ke DB **hanya** di dalam handler `voice:confirm`. Bahkan sudah ada sub-alur
   edit per-field (`voice_edit:amount`, `voice_edit:category`).
3. **AI service tangguh.** `services/ai_service.py` punya: *exponential backoff* dengan
   *jitter*, batas *deadline* total (25 s) selain timeout per-attempt (10 s), penanganan
   khusus HTTP 401 / 403 / 429, pemotongan teks input (1.000 karakter),
   pembersihan *markdown fence* (```json) sebelum `json.loads`, validasi tipe/jumlah
   setelah parse, dan percobaan model alternatif bila model utama ditolak.
4. **Sanitasi log kelas satu.** `utils/sanitizer.py` menyediakan `mask_sensitive_value`,
   `sanitize_dict` (daftar ~18 nama kunci sensitif), `sanitize_url` (menutup password di
   `postgresql://user:pass@host`), `sanitize_headers`, dan `sanitize_exception_message`
   (menutup token 16+ karakter di pesan *exception*). Ini langsung memenuhi aturan
   ZOI #7 "never expose secrets".
5. **Validasi input.** `utils/validators.py`: `sanitize_text` (escape HTML + buang karakter
   kontrol), `validate_amount` (regex + batas atas + maksimal 2 desimal).
6. **Migrasi Alembic nyata**, tiga versi berurutan dengan penamaan tanggal yang rapi.
7. **Konfigurasi divalidasi.** `pydantic-settings` dengan `field_validator` untuk
   `LOG_LEVEL` dan `MAX_TRANSACTION_AMOUNT`, pola *singleton* `get_settings()`.

### Kelemahan

1. **Nol test, nol CI.** Tidak ada direktori `tests/`, tidak ada workflow GitHub Actions.
   Untuk aplikasi keuangan ini kelemahan serius — dan ZOI justru mewajibkan test (bagian 17).
2. **Tidak ada otorisasi sama sekali.** Tidak ada *whitelist* Telegram ID, tidak ada peran
   admin/member, tidak ada pembatasan siapa yang boleh memakai bot. Siapa pun yang
   menemukan bot bisa memakainya. ZOI mewajibkan *whitelist* + dua peran.
3. **Buku kas per-pengguna, bukan bersama.** `transactions.user_id` → FK ke `users` dengan
   `ondelete="CASCADE"`, dan semua *query* difilter per `user_id`. Model "satu buku kas
   bersama untuk 2–3 orang" **tidak ada** dan harus dirancang ulang.
4. **`pending transaction` hanya di memori FSM aiogram**, tidak ada tabel
   `pending_transactions` dengan `expires_at`. Kalau proses *restart* saat seseorang
   sedang menunggu konfirmasi, data parsing hilang. ZOI mewajibkan penyimpanan *pending*
   yang persisten (bagian 10 & 12).
5. **Tidak ada proteksi klik-ganda / idempotensi.** Jika tombol "Simpan" ditekan dua kali
   atau Telegram mengirim *update* yang sama dua kali, bisa lahir transaksi ganda.
6. **Jalur *quick add* menyimpan tanpa konfirmasi.** `handle_quick_add` memanggil
   `create_transaction` langsung. Harus dihapus/diubah untuk ZOI.
7. **Satu provider AI saja.** Satu `AI_BASE_URL` + satu `AI_API_KEY` yang
   OpenAI-compatible. Tidak ada *router*, tidak ada *fallback* ke provider kedua,
   tidak ada penjagaan "model gratis saja".
8. **Butuh Redis** untuk *rate limiting* — infrastruktur tambahan yang ZOI tidak minta.
9. **Komentar & *docstring* sebagian besar berbahasa Rusia** (`config/config.py`,
   `models/*.py`, `utils/validators.py`, `services/export_service.py`). Menyalin kode ini
   berarti ikut menyalin komentar yang tidak terbaca bagi pengembang proyek ini.
10. **Hanya RUB & USD**, tidak ada IDR, tidak ada *timezone* Asia/Jakarta, tidak ada
    pemahaman "ribu / rb / juta".
11. **Bug yang menunggu meledak:** `_get_httpx_client_kwargs` memakai `proxies=`.
    Diverifikasi: pada httpx 0.28.1 `AsyncClient.__init__` **tidak lagi punya** parameter
    `proxies`. Repo mengunci `httpx==0.27.2` sehingga aman di sana, tapi kode ini akan
    langsung *error* bila disalin ke proyek dengan httpx terbaru. Kalau kita memakai ulang
    `ai_service.py`, bagian proxy ini harus ditulis ulang dengan `proxy=` (tunggal).
12. Export Excel hanya **satu sheet**; ZOI butuh lima sheet.

### Masalah keamanan khusus

- **Tidak ada otorisasi** (poin 2 di atas) — ini risiko keamanan terbesar: buku kas
  terbuka untuk publik.
- **Tidak ada *audit log*.** Tidak ada catatan siapa mengubah/menghapus apa.
- Penghapusan transaksi tidak dibatasi peran (tidak ada peran).
- Sisi positif: `str(e)` dari *exception* selalu dilewatkan `sanitize_exception_message`
  sebelum masuk log, dan respons API dipotong 200 karakter sebelum dicatat.

---

## 4. `nikamurkaa/finance-helper`

### Arsitektur

Empat layanan terpisah, semuanya Python:

```
services/bot-service/        aiogram 3.13.1, 18 modul handler/helper
services/api-gateway/        FastAPI, proxy + auth Mini App
services/finance-service/    FastAPI + SQLAlchemy 2.0 + Alembic (sumber data)
services/analytics-service/  FastAPI + APScheduler + openpyxl (laporan)
```

Plus Telegram Mini App (HTML), OCR struk (`pytesseract` + `Pillow`), impor mutasi bank.

### Kekuatan

1. **Satu-satunya repo dengan model "keuangan bersama" yang sudah jalan.**
   `Workspace` + `WorkspaceMember` + `MemberRole(owner/editor/viewer)`, dengan
   `UniqueConstraint("workspace_id", "user_id")`. Penegakan peran benar-benar ada di
   `crud.py` — mis. `if require_write and membership.role == MemberRole.viewer: ...`
   dan `if membership.role != MemberRole.owner: raise ...` untuk mengubah keanggotaan,
   termasuk penjagaan `owner_role_immutable`. **Inilah pola yang ZOI butuhkan.**
2. **Parser bahasa alami deterministik tanpa AI.** `bot-service/app/utils.py` punya
   `parse_natural_operation`, `parse_user_date`, regex untuk "сегодня / вчера /
   N hari lalu / YYYY-MM-DD / DD.MM.YYYY", dan regex jumlah `^[+]?\d+(?:[.,]\d+)?$`.
   **Ini sangat berharga untuk ZOI**: pola yang sama bisa dipakai untuk "kemarin",
   "2 ribu", "25rb", "1,5 juta" — dan jalan **tanpa biaya AI sama sekali**.
3. **Autentikasi antar-layanan** dengan header `X-API-Key` (`security.py`).
4. Ada test (10 file), CI (`ci.yml`), dokumen skenario test, dan panduan *deployment*.
5. Fitur matang: limit/anggaran per kategori, *alias* kata kunci kategori untuk
   pemilihan kategori otomatis, ringkasan harian terjadwal, ekspor CSV + XLSX.
6. Dokumentasi dua bahasa (EN/RU) dan tangkapan layar yang jelas.

### Kelemahan

1. **Terlalu berat untuk ZOI.** Empat proses + Mini App untuk 2–3 pengguna adalah
   *over-engineering*. Di paket gratis Altare ini memakan kuota proses dan RAM tanpa
   manfaat nyata (lihat bagian 7).
2. **Tidak ada AI/LLM.** Pemahaman bahasa murni regex + kata kunci. Permintaan ZOI
   ("Bayar parkir motor 2 ribu di pasar Ciamis" → kategori Transportasi, lokasi
   Pasar Ciamis) melampaui kemampuan parser ini.
3. **Tidak ada konfirmasi sebelum menyimpan.** Konfirmasi hanya dipakai untuk
   **penghapusan** (`confirm_delete_kb`). Penambahan transaksi langsung tersimpan.
4. **Anotasi tipe uang menyesatkan.** `amount: Mapped[float] = mapped_column(Numeric(12, 2))`.
   Kolom DB benar (NUMERIC), tapi anotasi `float` mengundang kesalahan di kode aplikasi.
   `Numeric(12, 2)` juga lebih sempit dari yang nyaman untuk Rupiah
   (maksimum ~9,99 miliar) — untuk IDR sebaiknya `Numeric(18, 2)`.
5. `pytesseract` butuh *binary* Tesseract OCR — **tidak praktis dipasang di Termux**
   maupun di *buildpack* Altare.
6. Struktur direktori tidak lazim (`finance_helper/source_files/...`), menyulitkan
   pemakaian ulang langsung.
7. Komentar dan *docstring* berbahasa Rusia.
8. Dibuat sebagai proyek skripsi — fokusnya memamerkan keluasan arsitektur, bukan
   kesederhanaan operasional.

### Masalah keamanan khusus

- `require_internal_key` **melewati pemeriksaan bila `internal_api_key` kosong**
  (`if settings.internal_api_key and ...`). Kalau variabel itu lupa diisi, API internal
  terbuka tanpa autentikasi. Pola "aman secara default" yang salah — jangan ditiru.
- Permukaan serangan lebih luas: empat layanan HTTP, bukan satu proses *polling*.

---

## 5. `cenoff/Money-Bot`

### Arsitektur

Datar, tanpa paket: `main.py`, `logic.py`, `sql.py`, `keyboard.py`, `graphs.py`,
`constants.py`, lalu `tests/` (7 file). Stack: `aiogram 3.22.0`, `aiosqlite`,
`pandas` + `XlsxWriter`, `matplotlib`, `APScheduler`.

### Kekuatan

1. **Satu-satunya repo Python dengan test yang serius.** 995 baris test untuk 2.058 baris
   aplikasi (≈48%), `pytest` + `pytest-cov` dengan `--cov-report=term-missing`,
   CI GitHub Actions, *badge* Codecov, dan konfigurasi `ruff`. **Pola test-nya patut
   dicontoh** meski kodenya tidak.
2. Sangat mudah dibaca — bagus sebagai rujukan "bot Telegram minimal".
3. `APScheduler` untuk langganan berulang (tagihan bulanan) — ide bagus untuk
   pengembangan ZOI kelak.
4. Grafik `matplotlib` dijalankan di `ThreadPoolExecutor` karena tidak mendukung async —
   penanganan yang benar.

### Kelemahan

1. **`amount REAL`** — floating-point untuk uang, langsung melanggar aturan ZOI #10.
2. **SQLite saja**, tanpa ORM dan tanpa migrasi. `CREATE TABLE IF NOT EXISTS` ditulis
   manual di `connect_database()`. ZOI butuh PostgreSQL + Alembic.
3. **Tidak ada pemasukan.** Hanya `expenses`, `savings`, `subscriptions`. ZOI butuh
   pemasukan *dan* pengeluaran dalam satu buku kas.
4. **Tidak ada AI.** Kategori dipilih dari *keyboard* 13 tombol.
5. **Tidak ada otorisasi, tidak ada peran, tidak ada *audit log*.**
6. Memakai `pandas` + `XlsxWriter`, bukan `openpyxl` seperti pilihan ZOI; `pandas` +
   `matplotlib` + `numpy` adalah dependensi berat (kompilasi di Termux sering gagal).
7. Memakai dua pustaka DB sekaligus (`aiosqlite` *dan* `sqlite3`) karena pandas tidak
   mendukung async — solusi tambal-sulam.
8. Nama file cacat di repo: `requirements-dev.txt\xa0` (ada karakter *non-breaking space*).

---

## 6. `alainrk/pago`

### Arsitektur

**Go 1.26 + React/TypeScript**, bukan Python:

```
cmd/web, cmd/migrate, cmd/seed     Go entrypoints
internal/ai (deepseek), db, model, repository, scheduler, web
frontend/  React + TypeScript (Vite), PWA, WebAuthn/passkey
migrations/ versi Go bernomor
```

### Kekuatan — murni **konseptual**, bukan kode

1. **Alur "tulis bahasa biasa → tinjau field → simpan"** sama seperti kebutuhan ZOI:
   "type *irish pub 4.50 yesterday* and **review the parsed fields before saving**".
2. **Deteksi duplikat**: memperingatkan ketika transaksi baru mirip transaksi yang baru
   saja disimpan. ZOI butuh proteksi duplikat (bagian 10) — idenya langsung relevan.
3. **Klasifikasi *intent*** di `internal/ai/prompt.go`, termasuk *intent* `clone`
   ("clone, duplicate, repeat, copy, same again") — pola *prompt* yang rapi.
4. ***Prompt engineering* yang baik**: instruksi eksplisit "Respond with ONLY the JSON
   object but without markdown syntax… don't include the triple backticks".
   Ini mengurangi kerja pembersihan keluaran AI.
5. Transaksi berulang, pencarian *full-text* lintas tahun, 26 file test, CI.
6. Dokumen desain di `docs/plans/` dan `specs/` — contoh bagus "desain dulu, kode kemudian".

### Kelemahan

1. **Bahasa berbeda.** Kode Go tidak bisa dipakai ulang di proyek Python. Nilai pakainya
   terbatas pada ide dan *prompt*.
2. **Bot Telegram-nya sudah dihapus.** README menyatakan: "Pago used to be a Telegram bot
   too. The bot is gone". Sisa referensi Telegram hanya di dokumen spesifikasi lama.
   Jadi repo ini **bukan** lagi rujukan integrasi Telegram.
3. **`Amount float64`** di seluruh kode aplikasi (`internal/model/transactions.go`,
   `internal/ai/deepseek.go`, `internal/web/dto.go`) meski kolom DB `decimal(15,2)`.
   Melanggar prinsip uang ZOI di level aplikasi.
4. Satu provider AI (DeepSeek), tanpa *fallback*.
5. Butuh *frontend* React + WebAuthn/passkey — tidak relevan, menambah banyak
   permukaan kerja yang ZOI tidak minta.
6. Paling besar dan paling kompleks (287 file) — paling jauh dari "lightweight".

---

## 7. Kompatibilitas dengan ZOI FINANCE AI

### Fakta *platform* yang sudah diverifikasi

Saya memeriksa dokumentasi Altare karena ini menentukan desain, bukan hanya *deployment*.

**Paket Always Free — Postgres** (`docs.altare.gg/databases/postgres`):

| Batas | Nilai |
|---|---|
| Jumlah database | 1 |
| Memori / disk | 256 MB / 1 GB |
| Koneksi maksimum | **25** |
| Retensi *backup* | **3 hari** (nightly 01:00–06:00 UTC) |
| TLS | **Wajib** (`sslmode=require`) |

*Restore* selalu membuat database **baru** (`<nama>-copy`) dan ikut menghitung kuota
database. Karena kuota paket gratis hanya **1** database, *restore* tidak bisa dilakukan
sebelum database lama dihapus — risiko operasional yang harus didokumentasikan di
`docs/DEPLOYMENT.md`.

**Paket Always Free — App Hosting** (`docs.altare.gg/apps`):

- Python **3.13 (default)**, tersedia 3.11–3.14.
- *Start command* lewat `Procfile` (entri `web`) atau kolom **Start command**.
- **Bot/worker tanpa port didukung** — "Bots and workers that don't serve traffic don't
  need a port". Jadi **Telegram long polling bisa dipakai, webhook tidak diperlukan.**
- *Env var* lewat `altr env set <app> KEY=VALUE` atau `--file .env.production`,
  tersimpan terenkripsi, maksimum 200 variabel / 32 KB per app. Menyimpan variabel
  **memicu *redeploy***.
- `altr deploy` men-*deploy* **commit terakhir di GitHub, bukan file lokal** — cocok
  sekali dengan alur Termux: `commit` → `push` → `altr deploy`.
- Batas gratis: 8 proses per app, log 3 hari / 100 MB, 5 *cron job* (minimal tiap 5 menit,
  memanggil URL).
- **Perilaku *restart* saat proses *crash* tidak didokumentasikan.** Ini **belum terverifikasi**
  dan wajib diuji langsung di PHASE 9 — jangan diasumsikan.

### Konsekuensi desain

1. **Satu proses saja.** Arsitektur empat layanan `finance-helper` memakan 4 dari 8 kuota
   proses tanpa manfaat untuk 3 pengguna. ZOI harus **satu proses** *long polling*.
2. ***Connection pool* harus kecil.** Dengan batas 25 koneksi, SQLAlchemy perlu dibatasi
   eksplisit (mis. `pool_size=5, max_overflow=2, pool_pre_ping=True, pool_recycle=300`).
   Nilai *default* SQLAlchemy bisa menghabiskan kuota saat *redeploy* tumpang-tindih.
3. **Jebakan `sslmode` + asyncpg — sudah diverifikasi langsung.** Altare memberi URL
   berisi `?sslmode=require`, tetapi `sslmode` adalah parameter libpq/psycopg yang
   **tidak dikenal asyncpg**. Saya menguji ini (SQLAlchemy 2.1.9 + asyncpg 0.32.0):

   - `create_async_engine("postgresql+asyncpg://...?sslmode=require")` **berhasil tanpa
     peringatan** — SQLAlchemy meneruskan `sslmode` apa adanya ke `asyncpg.connect()`.
   - `asyncpg.connect()` **tidak punya** parameter `sslmode` dan **tidak punya** `**kwargs`,
     sehingga gagal saat **koneksi pertama** dengan
     `TypeError: connect() got an unexpected keyword argument 'sslmode'`.
   - Mengganti ke `?ssl=require` menghasilkan `connect_args` yang benar (`{'ssl': 'require'}`).

   Mode kegagalannya **menipu**: aplikasi *start* dengan mulus dan baru mati saat *query*
   pertama ke database. Karena itu `DATABASE_URL` wajib dinormalisasi di `config.py` —
   buang `sslmode` dari *query string*, lalu berikan TLS lewat `?ssl=require` atau
   `connect_args={"ssl": "require"}`. **Tangani sejak awal; ini akan menjadi *error*
   pertama saat deploy ke Altare kalau dilewatkan.**
4. **Disk 1 GB + *backup* 3 hari = *backup* sendiri wajib.** Catatan keuangan harus
   bertahan lebih lama dari 3 hari. Rencana: `pg_dump` berkala + simpan ke U3
   (object storage Altare, tanpa biaya *egress*), ditambah ekspor Excel sebagai salinan
   yang bisa dibaca manusia.
5. **Peringatan kuota bisa dibuat nyata.** Aturan ZOI "peringatkan admin, jangan
   diam-diam kehilangan data" dapat diimplementasikan dengan `pg_database_size()`
   dibandingkan batas 1 GB, lalu kirim pesan ke admin pada ambang 70% / 90%.
6. **Termux:** `pandas`, `numpy`, `matplotlib`, `pytesseract` sebaiknya dihindari — sering
   gagal dikompilasi di Android. Stack ZOI (`aiogram`, `sqlalchemy`, `asyncpg`,
   `alembic`, `openpyxl`, `httpx`, `pydantic`) semuanya tersedia sebagai *wheel* murni
   Python atau punya *build* Termux yang umum. `asyncpg` perlu `clang` + `postgresql`
   dari `pkg` — akan diverifikasi di PHASE 5.
7. **Hindari Redis.** *Rate limiting* ala `finance-bot` berbasis Redis tidak perlu untuk
   3 pengguna; cukup *in-memory* (atau Valkey Altare kalau nanti benar-benar dibutuhkan).

### Tabel kesesuaian

| Kebutuhan ZOI | finance-bot | finance-helper | Money-Bot | pago |
|---|:--:|:--:|:--:|:--:|
| Python + aiogram 3.x | ✅ | ✅ | ✅ | ❌ (Go) |
| PostgreSQL + SQLAlchemy 2 + Alembic | ✅ | ✅ | ❌ | ❌ |
| Uang pakai Decimal/NUMERIC | ✅ | ⚠️ anotasi `float` | ❌ `REAL` | ⚠️ `float64` |
| Satu buku kas bersama | ❌ | ✅ *workspace* | ❌ | ❌ |
| Peran admin / member | ❌ | ✅ owner/editor/viewer | ❌ | ❌ |
| *Whitelist* Telegram ID | ❌ | ❌ | ❌ | ❌ |
| AI → transaksi | ✅ | ❌ | ❌ | ✅ |
| **Dual** AI + *fallback* | ❌ | ❌ | ❌ | ❌ |
| Penjagaan "model gratis saja" | ❌ | ❌ | ❌ | ❌ |
| Konfirmasi sebelum simpan | ✅ | ❌ | ❌ | ✅ |
| *Pending* persisten + kedaluwarsa | ❌ | ❌ | ❌ | ❌ |
| Proteksi duplikat / klik-ganda | ❌ | ❌ | ❌ | ✅ konsep |
| Hapus hanya admin | ❌ | ⚠️ sebagian | ❌ | ❌ |
| *Audit log* | ❌ | ❌ | ❌ | ❌ |
| Excel 5 sheet | ❌ 1 sheet | ⚠️ ekspor datar | ⚠️ 3 sheet | ❌ CSV |
| Bahasa Indonesia + IDR | ❌ | ❌ | ❌ | ❌ |
| Asia/Jakarta | ❌ | ❌ | ❌ | ❌ |
| Test otomatis | ❌ | ✅ | ✅ | ✅ |

**Tidak ada satu pun repo** yang menyediakan: dual AI + *fallback*, penjagaan model gratis,
*whitelist* Telegram ID, buku kas bersama *dengan* hapus khusus admin, *pending* persisten,
*audit log*, bahasa Indonesia/IDR, atau Excel lima sheet. Itu **tujuh** kebutuhan inti ZOI
yang harus dibangun sendiri — dan justru itulah bagian yang paling menentukan.

---

## 8. Lisensi dan Syarat Pemakaian Ulang

Keempat repo referensi berlisensi **MIT**:

| Repo | Pemegang hak cipta |
|---|---|
| `RibasomR/finance-bot` | Copyright (c) 2025-2026 RibasomR |
| `nikamurkaa/finance-helper` | Copyright (c) 2026 Nicole Zhurbenko |
| `cenoff/Money-Bot` | Copyright (c) 2025 Oleh Zavieriukhin |
| `alainrk/pago` | Copyright (c) 2025 Alain Di Chiappari |

**Syarat MIT:** pemakaian, modifikasi, dan distribusi diizinkan — **dengan kewajiban
menyertakan pemberitahuan hak cipta dan teks lisensi** pada salinan atau bagian penting
dari perangkat lunak tersebut.

**Kewajiban kita bila memakai ulang kode:**

1. Buat `LICENSE` untuk ZOI-FINANCE-AI (repo ini **belum punya**). MIT adalah pilihan
   paling sederhana karena kompatibel dengan keempat sumber.
2. Buat `docs/THIRD_PARTY_NOTICES.md` yang memuat teks lisensi MIT lengkap + baris
   hak cipta setiap repo yang kodenya benar-benar kita pakai.
3. Pada setiap file yang berisi kode turunan, tambahkan komentar kepala, misalnya:
   `# Diadaptasi dari RibasomR/finance-bot (MIT, Copyright (c) 2025-2026 RibasomR)`.
4. **Ide, pola arsitektur, dan nama perintah tidak dilindungi hak cipta.** Meniru
   *pendekatan* (mis. "simpan *pending* di FSM lalu minta konfirmasi") tanpa menyalin
   baris kodenya tidak menimbulkan kewajiban atribusi — tapi mencantumkannya tetap
   praktik yang baik.
5. Lisensi MIT **tidak** bersifat *copyleft*, jadi tidak ada kewajiban membuka kode ZOI.

---

## 9. Komponen yang Layak Dipakai Ulang

**Salin kodenya (dengan atribusi MIT), setelah menerjemahkan komentar ke bahasa Indonesia:**

| Sumber | Komponen | Alasan |
|---|---|---|
| finance-bot | `utils/sanitizer.py` | Memenuhi aturan ZOI #7 secara langsung. Matang dan berdiri sendiri. |
| finance-bot | `utils/validators.py` (`sanitize_text`, `validate_amount`) | Validasi *amount* berbasis `Decimal`, siap disesuaikan untuk IDR. |
| finance-bot | *Backoff* + *deadline* di `ai_service.py` | `_calculate_backoff_delay`, pola *deadline* total, penanganan 401/403/429, pembersihan *markdown fence*. Inti ketangguhan `app/ai/router.py`. |
| finance-bot | `middlewares/error_handler.py` | *Exception* disanitasi sebelum masuk log. |
| finance-bot | Pola `config/config.py` | Struktur `pydantic-settings` + `field_validator` + `get_settings()`. |
| finance-bot | Penamaan versi Alembic | `YYYY_MM_DD_HHMM-NNN_deskripsi` — rapi dan mudah diurutkan. |

**Tiru polanya, tulis kode sendiri:**

| Sumber | Pola | Penerapan di ZOI |
|---|---|---|
| finance-bot | Konfirmasi AI berbasis FSM + edit per-field | Jadi `app/bot/handlers/confirm.py`, **tapi** *state*-nya dipindah ke tabel `pending_transactions` agar tahan *restart*. |
| finance-helper | `MemberRole` + penegakan peran di lapisan data | Jadi `app/services/permission_service.py`; disederhanakan jadi dua peran (`admin`, `member`) pada satu buku kas. |
| finance-helper | `parse_natural_operation` + `parse_user_date` (regex) | **Pra-parser Indonesia deterministik** di `app/ai/parser.py`: "ribu/rb/k", "juta", "kemarin", pemisah ribuan/desimal. Dicoba **sebelum** AI → hemat kuota, dan menjadi jalan keluar saat kedua provider AI mati. |
| finance-helper | Penegakan peran di lapisan data, bukan di handler | Cegah *bypass* lewat jalur handler lain. |
| pago | Deteksi duplikat | Perbandingan (jumlah, kategori, tanggal, pencatat) dalam jendela waktu singkat sebelum menyimpan. |
| pago | *Prompt* "JSON saja, tanpa backtick" | Dipakai di `app/ai/openrouter.py` dan `app/ai/gemini.py`. |
| pago | Dokumen desain sebelum kode | Pola untuk `docs/ARCHITECTURE.md` di PHASE 2. |
| Money-Bot | Struktur `pytest` + `pytest-cov` + CI | Pola untuk `tests/` dan `.github/workflows/`. |

**Jangan dipakai:**

- Lapisan DB `Money-Bot` (`REAL` untuk uang, SQLite, tanpa migrasi).
- `pandas` / `matplotlib` / `numpy` / `pytesseract` (berat, bermasalah di Termux).
- Arsitektur empat layanan `finance-helper`.
- Pola `require_internal_key` yang melewati pemeriksaan saat kunci kosong.
- Argumen `proxies=` pada httpx (sudah dihapus di httpx ≥ 0.28).
- Seluruh basis kode `pago` (Go) dan *frontend* React.
- Jalur *quick add* `finance-bot` yang menyimpan tanpa konfirmasi.

---

## 10. Rekomendasi

### Keputusan: **bangun implementasi baru yang bersih**, dengan `RibasomR/finance-bot` sebagai **rujukan struktur dan pola**, bukan sebagai *fork*.

**Alasan:**

1. **Tujuh kebutuhan inti ZOI tidak ada di repo mana pun** (bagian 7). Itu bukan
   penyesuaian kecil — itu lapisan otorisasi, lapisan AI, dan model data yang baru.
2. **Model data harus dirancang ulang.** `finance-bot` memfilter per `user_id` di
   hampir setiap *query*; ZOI butuh satu buku kas bersama dengan `created_by` sebagai
   atribusi, bukan sebagai pemisah data. Mem-*fork* lalu membongkar ini lebih berisiko
   daripada menulis ulang, karena satu filter `user_id` yang tertinggal berarti anggota
   tidak melihat transaksi anggota lain — bug yang sunyi dan serius di aplikasi keuangan.
3. ***Fork* mewarisi nol test.** Kita tidak punya jaring keselamatan untuk mendeteksi
   kerusakan saat membongkar model datanya.
4. **Ukurannya sudah pas untuk ditulis sendiri.** ~9.600 baris `finance-bot` termasuk
   dua *locale*, tujuh modul *keyboard*, dan fitur yang ZOI tidak minta. Inti ZOI jauh
   lebih kecil.
5. **Hambatan bahasa.** Komentar Rusia di seluruh file inti membuat pemeliharaan jangka
   panjang sulit bagi pengembang proyek ini.
6. **Mulai dari repo bersih sejalan dengan aturan ZOI #2 dan #3** — tidak ada pekerjaan
   lama yang bisa tertimpa.

**Yang tetap kita ambil:** empat modul *utility* `finance-bot` (sanitizer, validators,
pola backoff AI, error handler) disalin dengan atribusi MIT — ini bagian paling matang
dan paling bebas dari asumsi arsitektur, sehingga memberi manfaat terbesar dengan
risiko paling kecil.

### Catatan untuk PHASE 2 (Desain Arsitektur)

Keputusan yang harus diselesaikan di PHASE 2, berdasarkan temuan audit ini:

1. `pending_transactions` persisten di PostgreSQL (`parsed_data` JSONB, `expires_at`,
   `status`), bukan FSM di memori. Tambah *unique guard* agar konfirmasi ganda tidak
   melahirkan transaksi ganda.
2. Dua peran (`admin`, `member`) dengan penegakan **di lapisan service**, bukan di handler.
   *Whitelist* Telegram ID numerik lewat *middleware* yang berjalan sebelum semua handler.
3. `app/ai/router.py`: pra-parser regex Indonesia → OpenRouter (model `:free`) → Gemini
   (*free tier*) → entri manual. Nama model **dapat dikonfigurasi**; daftar *allowlist*
   model gratis dicek sebelum setiap permintaan sehingga model berbayar tidak mungkin
   terpakai walau salah konfigurasi.
4. `Numeric(18, 2)` untuk jumlah (bukan `(15,2)` atau `(12,2)`) agar nyaman untuk Rupiah.
5. Normalisasi `DATABASE_URL` untuk asyncpg + TLS (bagian 7, poin 3) — tangani di
   `config.py` sejak awal.
6. Batasi *connection pool* secara eksplisit (batas 25 koneksi).
7. `audit_logs` ditulis dalam **transaksi database yang sama** dengan perubahan yang
   dicatatnya, agar jejak audit tidak bisa menyimpang dari data.
8. Pemantauan kuota DB (`pg_database_size()`) + peringatan ke admin pada 70% / 90%.
9. Semua waktu disimpan UTC, ditampilkan Asia/Jakarta.

### Yang masih harus diverifikasi langsung (jangan diasumsikan)

- Perilaku *restart* otomatis saat proses *crash* di Altare — **tidak terdokumentasi**.
- Apakah `asyncpg` bisa dikompilasi di Termux (butuh `clang` + `postgresql`).
- Apakah model `:free` OpenRouter yang dipilih benar-benar tersedia dan kuotanya cukup.
- Apakah `altr deploy` memerlukan entri `web` di `Procfile` untuk proses tanpa port.

---

## 11. Status PHASE 1

| Item | Status |
|---|---|
| Repo ZOI-FINANCE-AI diperiksa | ✅ kosong, 2 file, aman dimulai |
| Empat repo referensi di-*clone* dan dibaca | ✅ source code, bukan hanya README |
| Lisensi diverifikasi | ✅ keempatnya MIT, pemegang hak cipta dicatat |
| Arsitektur dibandingkan | ✅ bagian 3–6 + tabel bagian 7 |
| Komponen pakai-ulang diidentifikasi | ✅ bagian 9 |
| Keamanan dievaluasi | ✅ tanpa secret/SQLi/eval; temuan per repo dicatat |
| Batas *platform* Altare diverifikasi | ✅ Postgres & App Hosting paket gratis |
| Strategi implementasi ditentukan | ✅ implementasi bersih + pakai-ulang terbatas |
| `docs/REPOSITORY_AUDIT.md` dibuat | ✅ dokumen ini |

**File yang dibuat:** `docs/REPOSITORY_AUDIT.md` (satu-satunya perubahan; tidak ada file
lain dibuat atau diubah).
**Test dijalankan:** tidak ada test ZOI — PHASE 1 adalah fase audit dan belum ada kode
untuk diuji. Test suite repo referensi juga tidak dijalankan; penilaian kualitas test
didasarkan pada pembacaan file test, konfigurasi `pytest`, dan *workflow* CI mereka.

**Verifikasi teknis yang benar-benar dijalankan** (SQLAlchemy 2.1.9, asyncpg 0.32.0,
httpx 0.28.1):

| Yang diuji | Hasil |
|---|---|
| `create_async_engine` dengan `?sslmode=require` | Diterima tanpa peringatan, `sslmode` diteruskan ke driver |
| `asyncpg.connect(..., sslmode=...)` | **Gagal:** `TypeError: connect() got an unexpected keyword argument 'sslmode'` |
| `create_async_engine` dengan `?ssl=require` | Benar → `connect_args {'ssl': 'require'}` |
| `httpx.AsyncClient` parameter `proxies` | **Tidak ada lagi** di httpx 0.28.1 |

**Langkah berikutnya:** PHASE 2 — Desain Arsitektur (`docs/ARCHITECTURE.md` dan
`docs/DATABASE.md`), berdasarkan sembilan keputusan di bagian 10.

---

## Lampiran — Sumber

- Altare — Postgres: https://docs.altare.gg/databases/postgres
- Altare — App Hosting: https://docs.altare.gg/apps
- Altare — Harga / paket: https://altare.gg/en/pricing
- RibasomR/finance-bot: https://github.com/RibasomR/finance-bot
- nikamurkaa/finance-helper: https://github.com/nikamurkaa/finance-helper
- cenoff/Money-Bot: https://github.com/cenoff/Money-Bot
- alainrk/pago: https://github.com/alainrk/pago
