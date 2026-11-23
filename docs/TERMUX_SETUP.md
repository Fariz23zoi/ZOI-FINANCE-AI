# TERMUX SETUP — ZOI FINANCE AI

Panduan menyiapkan dan menjalankan ZOI FINANCE AI dari **HP Android dengan Termux**.
Ditulis dengan asumsi Anda belum terbiasa dengan backend. Setiap perintah dijelaskan.

Yang perlu disiapkan: HP Android, Termux (**dari F-Droid**, bukan Play Store — versi
Play Store sudah tidak diperbarui), dan koneksi internet.

---

## 1. Pasang paket dasar

Buka Termux, lalu jalankan satu per satu:

```bash
pkg update && pkg upgrade -y
```

`pkg update` menyegarkan daftar paket, `pkg upgrade` memperbarui yang sudah ada.
Kalau ditanya mengganti file konfigurasi, jawab `Y`.

```bash
pkg install -y python git nano
```

- `python` — bahasa pemrogramannya
- `git` — untuk mengambil dan mengirim kode ke GitHub
- `nano` — editor teks sederhana di dalam terminal

Periksa hasilnya:

```bash
python --version
git --version
```

Python harus **3.11 atau lebih baru**. Lunafy menyediakan 3.11–3.14 dan kita
memakai 3.13 di produksi, jadi semakin dekat semakin baik.

### Kalau sebuah paket tidak ditemukan

Tidak semua paket ada di repositori Termux. Kalau `pkg install` gagal:

```bash
pkg search nama-paket
```

Jangan memaksa memasang paket desktop. Bila memang tidak tersedia, lewati dan baca
bagian 5 — sebagian besar pekerjaan tetap bisa dilakukan.

---

## 2. Beri Termux akses penyimpanan (opsional)

Berguna bila Anda ingin menyalin file laporan ke folder Download:

```bash
termux-setup-storage
```

Android akan menampilkan dialog izin. Setelah disetujui, folder HP Anda ada di
`~/storage/shared`.

---

## 3. Ambil kode dari GitHub

```bash
cd ~
git clone https://github.com/Fariz23zoi/ZOI-FINANCE-AI.git
cd ZOI-FINANCE-AI
```

Kalau repositori masih privat, Git akan meminta nama pengguna dan **Personal Access
Token** (bukan password GitHub Anda). Buat token di GitHub → Settings → Developer
settings → Personal access tokens.

Supaya token tidak diminta terus:

```bash
git config --global credential.helper store
```

Token tersimpan dalam teks biasa di `~/.git-credentials`. Itu dapat diterima di HP
pribadi Anda sendiri; jangan lakukan di perangkat yang dipakai bersama.

---

## 4. Siapkan lingkungan Python

```bash
cd ~/ZOI-FINANCE-AI
python -m venv .venv
source .venv/bin/activate
```

`venv` adalah lingkungan Python terpisah, supaya paket proyek ini tidak bercampur
dengan paket Termux lainnya. Setelah aktif, prompt Anda akan diawali `(.venv)`.

**Setiap kali membuka Termux lagi, ulangi:**

```bash
cd ~/ZOI-FINANCE-AI && source .venv/bin/activate
```

Pasang dependensi:

```bash
pip install --upgrade pip
pip install -r requirements-dev.txt
```

---

## 5. Bila `asyncpg` gagal dipasang

`asyncpg` adalah driver PostgreSQL. Ia punya bagian berbahasa C, sehingga pip perlu
mengompilasinya di Android — tidak ada *wheel* siap pakai untuk Termux.

Bila muncul galat kompilasi, pasang alat bangunnya lalu coba lagi:

```bash
pkg install -y clang make binutils
pip install asyncpg
```

**Kalau tetap gagal, itu bukan penghalang.** Anda tidak membutuhkan `asyncpg` untuk
mengembangkan dan menguji di HP:

```bash
# Pasang semuanya KECUALI asyncpg
grep -v asyncpg requirements-dev.txt > /tmp/req-termux.txt
pip install -r /tmp/req-termux.txt
```

Seluruh test berjalan di SQLite, dan bot bisa dijalankan lokal dengan SQLite juga.
`asyncpg` hanya diperlukan untuk menyambung ke PostgreSQL Supabase — dan di
server Lunafy, pemasangannya dilakukan oleh server (yang punya wheel siap pakai),
bukan oleh HP Anda.

Skema database pun tidak perlu asyncpg: `migrations/sql/001_003_skema_awal.sql`
bisa ditempel langsung ke SQL Editor Supabase. Lihat `docs/DEPLOYMENT.md`
bagian 4c.

**Batasan yang perlu diketahui:** SQLite tidak punya tipe DECIMAL dan menyimpan kolom
NUMERIC sebagai float. Untuk nilai Rupiah dengan dua desimal, hasilnya tetap tepat.
Tapi jaminan presisi yang sesungguhnya ada di PostgreSQL, jadi sebelum rilis
jalankan test di PostgreSQL lewat GitHub Actions (sudah disiapkan di
`.github/workflows/tests.yml`).

---

## 6. Buat file .env lokal

```bash
cp .env.example .env
nano .env
```

Di dalam nano: ketik seperti biasa, `Ctrl+O` lalu Enter untuk menyimpan, `Ctrl+X`
untuk keluar.

Untuk sekadar menguji di HP, isi seperti ini:

```
TELEGRAM_BOT_TOKEN=token_dari_BotFather
ADMIN_TELEGRAM_ID=telegram_id_numerik_anda
DATABASE_URL=sqlite+aiosqlite:///./zoi_local.db
OPENROUTER_MODELS=meta-llama/llama-3.3-70b-instruct:free
```

**Mencari Telegram ID Anda:** kirim pesan apa saja ke
[@userinfobot](https://t.me/userinfobot) di Telegram. Ia membalas dengan ID numerik
Anda. Pakai angkanya, **bukan** username.

**Membuat bot Telegram:** buka [@BotFather](https://t.me/BotFather), kirim
`/newbot`, ikuti petunjuknya. Ia memberi token berbentuk `8123456789:AAE...`.

⚠️ File `.env` **tidak boleh** masuk ke Git. `.gitignore` sudah mengaturnya —
jangan diubah. Kalau token bot pernah terkirim ke GitHub, segera buat token baru
lewat `/revoke` di BotFather.

---

## 7. Siapkan database lokal

```bash
alembic upgrade head
```

Perintah ini membuat tabel, menyemai 19 kategori berbahasa Indonesia, dan
mendaftarkan Anda sebagai administrator (diambil dari `ADMIN_TELEGRAM_ID`).

Memeriksa hasilnya:

```bash
alembic current        # harus menampilkan 003
```

---

## 8. Jalankan test

```bash
pytest -q
```

Hasil yang diharapkan: **298 test lulus**, tanpa perlu kredensial apa pun dan tanpa
koneksi ke Telegram maupun provider AI.

Menjalankan sebagian saja:

```bash
pytest tests/test_parser.py -v      # pemahaman bahasa Indonesia
pytest tests/test_pending.py -v     # proteksi klik ganda
pytest tests/test_excel.py -v       # laporan Excel
pytest -k "duplikat" -v             # semua test tentang duplikat
```

**Yang tidak bisa diuji di HP:**

| Tidak bisa diuji di Termux | Alasan | Penggantinya |
|---|---|---|
| Presisi NUMERIC PostgreSQL | SQLite tidak punya DECIMAL | Job `pytest-postgres` di GitHub Actions |
| Migrasi di PostgreSQL asli | butuh server PostgreSQL | Job CI yang sama |
| Panggilan nyata ke OpenRouter/Gemini | butuh kunci API dan kuota | Dipalsukan dengan `httpx.MockTransport` |
| Pengiriman pesan Telegram sungguhan | butuh jaringan dan bot aktif | `AsyncMock`; uji manual setelah deploy |

---

## 9. Jalankan bot secara lokal

```bash
python run.py
```

Bot akan tersambung ke Telegram dan mulai *long polling*. Kirim `/start` ke bot
Anda dari Telegram.

Menghentikan: `Ctrl+C`.

**Agar tidak mati saat layar HP padam:**

```bash
termux-wake-lock
```

Ini hanya untuk pengujian. Untuk pemakaian sehari-hari, bot harus jalan di Lunafy —
HP tidak dirancang menyalakan bot 24 jam.

---

## 10. Alur kerja Git harian

```bash
git status                       # lihat apa yang berubah
git diff                         # lihat isi perubahannya
git add .
git commit -m "feat: tambah fitur X"
git push
```

Sebelum `git push`, **selalu** jalankan test:

```bash
pytest -q && git push
```

Tanda `&&` berarti push hanya dijalankan bila test lulus.

Pastikan `.env` tidak ikut:

```bash
git status --porcelain | grep "\.env$"
```

Tidak ada keluaran = aman.

Mengambil perubahan terbaru dari GitHub:

```bash
git pull
```

---

## 11. Masalah yang sering muncul

**`ModuleNotFoundError: No module named 'app'`**
Anda tidak berada di folder proyek, atau venv belum aktif:
```bash
cd ~/ZOI-FINANCE-AI && source .venv/bin/activate
```

**`ValidationError: TELEGRAM_BOT_TOKEN Field required`**
File `.env` belum ada atau belum diisi. Ulangi bagian 6.

**`Hanya model gratis yang diizinkan`**
Ada nama model di `OPENROUTER_MODELS` yang tidak berakhiran `:free`. Ini disengaja —
bot menolak start daripada berisiko memakai model berbayar.

**`TypeError: connect() got an unexpected keyword argument 'sslmode'`**
Seharusnya tidak pernah muncul: `app/config.py` sudah menormalisasi URL-nya.
Bila tetap muncul, berarti `DATABASE_URL` diteruskan ke driver tanpa lewat
`get_settings()`. Laporkan sebagai bug.

**Termux mati saat pindah aplikasi**
Android mematikan proses di latar belakang. Pakai `termux-wake-lock`, dan matikan
optimasi baterai untuk Termux di pengaturan Android.

**`pip install` sangat lambat**
Wajar di HP. `openpyxl`, `aiogram`, dan `sqlalchemy` berukuran besar. Sabar, dan
pastikan memakai Wi-Fi.

---

## 12. Daftar periksa

```bash
cd ~/ZOI-FINANCE-AI && source .venv/bin/activate   # masuk ke lingkungan kerja
pytest -q                                          # jalankan test
alembic upgrade head                               # terapkan migrasi
python run.py                                      # jalankan bot
git add . && git commit -m "pesan" && git push     # simpan pekerjaan
deactivate                                         # keluar dari venv
```

Langkah berikutnya setelah semuanya jalan di HP: `docs/DEPLOYMENT.md`.
