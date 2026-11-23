# DEPLOYMENT — ZOI FINANCE AI

Bot berjalan di **Lunafy**, database PostgreSQL di **Supabase**.

Semua batas di bawah diambil dari dokumentasi resmi masing-masing pada
23 November 2026. **Periksa ulang sebelum deploy** — batas paket gratis berubah.

---

## 1. Mengapa bot dan database dipisah

Lunafy **tidak menyediakan database apa pun**: dokumentasi fiturnya tidak
menyebut PostgreSQL, MySQL, MariaDB, maupun Redis. Satu-satunya penyimpanan
adalah disk server sebesar 512 MB.

Itu saja sudah memaksa database keluar. Tapi ada alasan kedua yang lebih
penting: **server gratis Lunafy yang tidak diperbarui tepat waktu akan
dihapus**, dan perpanjangannya manual setiap 7 hari. Kalau buku kas tinggal di
disk server itu — misalnya sebagai file SQLite — satu kali lupa memperbarui
berarti seluruh catatan keuangan hilang. Tidak ada peringatan, tidak ada
pemulihan.

Dengan database di Supabase, kehilangan server Lunafy hanya berarti kehilangan
proses bot. Catatannya tetap utuh, dan bot bisa dipasang ulang dalam beberapa
menit.

```
Telegram  ──long polling──>  Lunafy (proses Python, 256 MB)
                                    │
                                    │ TLS, pooler session mode (IPv4)
                                    ▼
                             Supabase PostgreSQL 17
                             (sumber kebenaran)
```

---

## 2. Batas yang menentukan desain

**Lunafy — server gratis pertama**

| Hal | Nilai | Dampaknya |
|---|---|---|
| RAM / CPU / disk | 256 MB · 0,5 vCPU · 512 MB | Pool koneksi kecil (3+2); file Excel dihapus setelah terkirim |
| Perpanjangan | Manual tiap 7 hari | **Tidak diperbarui = server dihapus** |
| Runtime | Python 3.11–3.14 | Pilih 3.13 di startup settings |
| Dependensi | Dipasang ulang **setiap start** | Jaga `requirements.txt` tetap ringan |
| Restart otomatis setelah crash | Tidak dinyatakan | **Harus diuji sendiri** |
| Port | €0,50/port/bulan, **web server tidak diizinkan** | Long polling, bukan webhook |
| Deploy | File manager di browser | Tidak ada git/GitHub otomatis |
| Region | EU-West | Latensi ke Indonesia lebih tinggi; tidak kritis untuk bot |

Catatan: halaman Lunafy sendiri tidak konsisten soal RAM — halaman utama dan
pricing menyebut 256 MB, sedangkan beberapa halaman perbandingan menyebut
512 MB. Kode ini aman di angka yang lebih kecil.

**Supabase — paket Free**

| Hal | Nilai | Dampaknya |
|---|---|---|
| Ukuran database | **500 MB** → proyek jadi **read-only** | Pemantauan kuota di /saldo dan /excel |
| Disk | 1 GB | Bukan pemicu read-only; yang memicu adalah 500 MB di atas |
| Penjedaan otomatis | Aktivitas rendah selama 7 hari | Tugas keepalive tiap 6 jam |
| Jendela pemulihan | 90 hari setelah dijeda | Di luar itu, data berisiko |
| PostgreSQL | 17 | NUMERIC, JSONB, enum native semuanya dipakai |

---

## 3. Mode koneksi Supabase — pilih yang benar

Supabase menyediakan tiga mode, dan **dua di antaranya akan gagal untuk bot
ini**, masing-masing dengan cara berbeda:

| Mode | Host:Port | Paket Free | Untuk bot ini |
|---|---|:--:|---|
| Direct connection | `db.<ref>.supabase.co:5432` | **IPv6 saja** | ❌ gagal bila container hanya IPv4 |
| Pooler **session mode** | `aws-0-<region>.pooler.supabase.com:5432` | IPv4 | ✅ **pakai ini** |
| Pooler transaction mode | `aws-0-<region>.pooler.supabase.com:6543` | IPv4 | ⚠️ tidak mendukung prepared statements |

Dokumentasi Supabase menyebut session mode "best for: persistent backend on
IPv4-only networks" — itu tepat menggambarkan bot ini.

Transaction mode gagal dengan cara yang membingungkan: aplikasi start normal,
lalu query mulai gagal karena asyncpg memakai prepared statements secara
default. `app/config.py` mendeteksi port 6543 dan memasang
`prepared_statement_cache_size=0` plus nama statement unik, sehingga tetap
bekerja — tapi tetap mencatat peringatan dan menyarankan session mode.

---

## 4. Siapkan Supabase

### 4a. Pastikan proyeknya aktif

Proyek paket Free dijeda setelah aktivitas rendah selama 7 hari. Buka
[dashboard Supabase](https://supabase.com/dashboard), pilih proyeknya, dan bila
tertulis *Paused*, klik **Resume project**.

Tunggu sampai statusnya *Active / Healthy* sebelum melanjutkan.

### 4b. Ambil connection string

Di dashboard proyek: tombol **Connect** → pilih **Session pooler**.

Bentuknya:

```
postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
```

Tempel apa adanya, termasuk `?sslmode=require` bila ada — `app/config.py`
menormalisasinya menjadi `ssl=require` untuk asyncpg.

> Kenapa itu perlu: `sslmode` adalah parameter libpq yang tidak dikenal
> asyncpg. Sudah diverifikasi langsung bahwa `create_async_engine` menerima URL
> itu tanpa peringatan, lalu gagal pada query **pertama** dengan
> `TypeError: connect() got an unexpected keyword argument 'sslmode'`.
> Aplikasi start mulus, lalu mati saat dipakai.

### 4c. Pasang skema

**Cara termudah dari HP** — tanpa perlu Alembic atau asyncpg di Termux:

1. Buka `migrations/sql/001_003_skema_awal.sql` di repo ini.
2. Ganti `__ADMIN_TELEGRAM_ID__` dengan Telegram ID numerik Anda. Cari ID-nya
   dengan mengirim pesan ke [@userinfobot](https://t.me/userinfobot). Tanpa
   tanda kutip, tanpa `@`.
3. Dashboard Supabase → **SQL Editor** → **New query** → tempel seluruh isi
   file → **Run**.

File itu dihasilkan dari migrasi Alembic dan sudah diuji pada PostgreSQL 16.15
kosong: 7 tabel, 4 tipe enum, 22 indeks, 3 CHECK constraint, 19 kategori,
1 baris pengaturan, 1 administrator, dan `alembic_version = 003`. Karena
`alembic_version` ikut diisi, migrasi berikutnya cukup dijalankan dengan
`alembic upgrade head` seperti biasa.

**Alternatif, bila asyncpg bisa dipasang di Termux:**

```bash
DATABASE_URL="postgresql://postgres.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres" \
ADMIN_TELEGRAM_ID=123456789 \
TELEGRAM_BOT_TOKEN=dummy \
OPENROUTER_MODELS=a:free \
alembic upgrade head
```

Verifikasi lewat SQL Editor:

```sql
SELECT version_num FROM alembic_version;                 -- 003
SELECT transaction_type, count(*) FROM categories GROUP BY 1;   -- 12 expense, 7 income
SELECT telegram_id, role FROM users;                      -- ID Anda, admin
```

---

## 5. Siapkan Lunafy

### 5a. Buat server

Di [panel Lunafy](https://panel.lunafy.run): buat server **Python**, pilih
**Python 3.13** di startup settings.

### 5b. Unggah kode

Lunafy memakai file manager di browser; tidak ada deploy otomatis dari GitHub.

**Jangan unggah seluruh repo** — disk hanya 512 MB dan dependensi dipasang ulang
setiap start. Yang perlu diunggah:

```
app/            ← seluruh folder
main.py
run.py
requirements.txt
```

Yang **tidak** perlu: `tests/`, `docs/`, `migrations/`, `.github/`,
`requirements-dev.txt`, `alembic.ini`. Migrasi dijalankan dari Supabase SQL
Editor (bagian 4c), bukan dari server bot.

> `main.py` ada khusus untuk ini: banyak panel memakai `main.py` sebagai nama
> file start bawaannya. Isinya hanya alias `run.py`, jadi kedua nama bekerja.

Cara praktis dari HP: buat zip berisi keempat hal di atas, unggah lewat file
manager, lalu extract di sana.

### 5c. Isi variabel lingkungan

Tab **Variables** di panel. **Jangan unggah file `.env`** — panel menyimpan
variabel terpisah dari kode, dan itu memang tempatnya.

| Variabel | Nilai |
|---|---|
| `TELEGRAM_BOT_TOKEN` | token dari @BotFather |
| `ADMIN_TELEGRAM_ID` | Telegram ID numerik Anda |
| `DATABASE_URL` | connection string session pooler dari bagian 4b |
| `OPENROUTER_API_KEY` | kunci OpenRouter |
| `OPENROUTER_MODELS` | `meta-llama/llama-3.3-70b-instruct:free,google/gemma-2-9b-it:free` |
| `GEMINI_API_KEY` | kunci Gemini |
| `TIMEZONE` | `Asia/Jakarta` |
| `LOG_LEVEL` | `INFO` |
| `DB_POOL_SIZE` | `3` |
| `KEEPALIVE_HOURS` | `6` |

Setiap nama di `OPENROUTER_MODELS` **wajib** berakhiran `:free`. Kalau tidak,
bot menolak start — itu disengaja: lebih baik gagal boot daripada menimbulkan
tagihan.

Bila panel tidak punya tab Variables yang bisa menampung semua ini, buat file
`.env` lewat file manager dengan isi yang sama. `pydantic-settings` membacanya
otomatis. Pastikan file itu **tidak** ikut masuk ke Git.

### 5d. Start command

```
python main.py
```

Kalau panel punya variabel seperti "Main file" atau "Bot file", isi dengan
`main.py`.

### 5e. Jalankan

Tekan **Start** di konsol. Dependensi dipasang dari `requirements.txt` pada
setiap start, jadi start pertama akan lebih lama.

---

## 6. Verifikasi — jangan anggap berhasil tanpa keempatnya

Di konsol Lunafy, cari baris berikut:

```
Koneksi database OK.
Terhubung sebagai @namabot (id=...)
Keepalive database tiap 6 jam.
Mulai long polling.
```

Lalu uji dari Telegram:

```
/start                        → bot menyapa dengan nama Anda
/saldo                        → saldo tampil (awalnya Rp0)
beli bensin 30rb              → layar konfirmasi muncul
   tekan Simpan               → "Transaksi tersimpan" + nomor transaksi
/excel                        → file xlsx terkirim, 5 sheet
```

Dan satu uji yang hanya bisa Anda lakukan sendiri:

```
Hentikan proses dari konsol, lalu perhatikan apakah ia naik sendiri.
```

Lunafy tidak mendokumentasikan perilaku restart otomatis. Kalau tidak naik
sendiri, Anda perlu memeriksanya secara berkala — dan itu sebaiknya diketahui
sekarang, bukan saat bot sudah mati tiga hari tanpa disadari.

Kalau salah satu dari semua ini gagal, deploy **belum** berhasil.

---

## 7. Konfigurasi awal lewat Telegram

Sebagai administrator:

```
/saldoawal 1500000                       # wajib — bot tidak menebak saldo awal
/anggota tambah 987654321 Nama Anggota   # ID numerik, bukan username
/anggota                                 # pastikan daftarnya benar
```

Minta setiap anggota mengirim `/start`. Mereka mencari Telegram ID-nya lewat
[@userinfobot](https://t.me/userinfobot).

Kunci API **tidak pernah** dikirim lewat pesan Telegram — semuanya lewat tab
Variables di panel.

---

## 8. Dua risiko yang harus Anda kelola sendiri

### Perpanjangan Lunafy tiap 7 hari

Server gratis yang tidak diperbarui **dihapus**. Yang hilang hanya proses bot,
bukan catatan keuangan — tapi tetap perlu dipasang ulang.

Saran praktis: pasang pengingat berulang di HP setiap 5 hari, bukan 7, supaya
ada jeda bila Anda sedang sibuk. Panel juga mengirim peringatan sebelum
kedaluwarsa.

### Penjedaan Supabase

Proyek paket Free dijeda setelah aktivitas database rendah selama 7 hari.
Tugas keepalive bawaan bot menyentuh database tiap 6 jam, jadi selama bot
berjalan, proyeknya tidak akan dijeda.

Tapi perhatikan rantainya: **kalau server Lunafy dihapus, keepalive ikut
berhenti**, dan tujuh hari kemudian proyek Supabase dijeda. Setelah dijeda,
jendela pemulihannya 90 hari. Jadi dua kelalaian berurutan — lupa perbarui
Lunafy, lalu membiarkannya tiga bulan — bisa menghilangkan data. Backup
berkala (bagian 9) adalah jaring pengaman untuk itu.

---

## 9. Backup

PostgreSQL adalah sumber kebenaran; Excel hanya laporan yang dihasilkan darinya.

### Otomatis, tiap minggu, di GitHub Actions

`.github/workflows/backup.yml` menjalankan backup setiap Senin 02:23 WIB.

**Ia berjalan di GitHub Actions, bukan di Lunafy — dan itu inti rancangannya.**
Server gratis Lunafy dihapus bila tidak diperbarui tiap 7 hari; backup yang
dijalankan di sana akan mati bersama hal yang seharusnya ia lindungi. GitHub
Actions punya jadwal sendiri dan tidak bergantung pada bot.

Efek samping yang disengaja: job ini menyentuh database setiap minggu,
sehingga proyek Supabase paket Free tidak akan pernah dijeda karena aktivitas
rendah — bahkan bila botnya mati. Masalah resume manual ikut hilang.

Yang dilakukan setiap kali berjalan:

1. `pg_dump --format=custom` seluruh skema `public`.
2. Memastikan ketujuh tabel ZOI ada di dalam dump.
3. **Memulihkan dump itu ke PostgreSQL 17 kosong**, lalu membandingkan jumlah
   baris keenam tabel dengan sumbernya.
4. Membandingkan **saldo** sumber dan hasil restore. Jumlah baris bisa cocok
   sementara nilainya rusak; saldo menguji angkanya.
5. Mengenkripsi dump dengan AES256, lalu mengunggahnya sebagai artifact
   (retensi 90 hari).

Langkah 3 dan 4 itu yang membedakan backup dari sekadar file. Dump yang belum
pernah dibuktikan bisa dipulihkan bukan backup — ia hanya terasa seperti
backup.

Workflow-nya juga menolak hasil yang kosong secara eksplisit. Tanpa itu,
`diff` dua file kosong akan **lulus**, sehingga verifikasi bisa berhasil
justru ketika semuanya gagal. `pg_restore` dijalankan dengan
`--exit-on-error`, karena tanpanya ia mengabaikan error dan tetap keluar
dengan status sukses.

**Secret yang perlu dipasang** (Settings → Secrets and variables → Actions):

| Secret | Isi |
|---|---|
| `BACKUP_DATABASE_URL` | connection string Session pooler dari Supabase |
| `BACKUP_PASSPHRASE` | kata sandi untuk mengenkripsi dump; simpan di pengelola sandi |

Tanpa keduanya, workflow gagal di langkah pertama dengan pesan yang jelas —
bukan diam-diam menghasilkan backup kosong.

### Manual, sewaktu-waktu

```bash
DATABASE_URL="postgresql://..." ./scripts/backup.sh
DATABASE_URL="postgresql://..." ./scripts/backup.sh ~/storage/shared/Download
```

Bisa dari Termux (`pkg install postgresql`). Skrip ini juga memeriksa isi
dump-nya dan menolak melanjutkan bila ada tabel yang hilang.

Lakukan sebelum perubahan besar: mengubah saldo awal, menghapus banyak
transaksi, atau mengganti provider database.

### Salinan yang bisa dibaca manusia

Jalankan `/excel` di Telegram dan simpan filenya. Berguna bukan untuk
pemulihan teknis, melainkan untuk memeriksa sendiri bahwa isinya masuk akal.

### Memulihkan

```bash
gpg --decrypt zoi-2026-11-23.dump.gpg > zoi.dump
pg_restore -d "$DATABASE_URL" --clean --if-exists --exit-on-error zoi.dump
```

`--exit-on-error` penting: tanpa itu, pemulihan yang sebagian gagal akan
tampak berhasil.

### Mengapa tidak ada database kedua yang hidup

Pernah dipertimbangkan: Neon sebagai database utama dengan Supabase sebagai
cadangan yang direplikasi. Ditolak, dengan alasan yang konkret:

* **Kuota compute Neon tidak cocok.** Paket Free memberi 100 CU-hours per
  proyek per bulan dan compute yang scale-to-zero setelah 5 menit idle, yang
  tidak bisa dimatikan. Bot ini memegang connection pool persisten, sehingga
  compute tidak pernah tidur: 0,25 CU × 730 jam = 182,5 CU-hours, kuota habis
  dalam ±17 hari setiap bulan. Memakainya berarti membongkar pool dan membuang
  keepalive — kebalikan dari yang dibutuhkan Supabase.
* **Dua database hidup menambah divergensi senyap.** Untuk buku kas, salinan
  basi yang mungkin dipulihkan lebih berbahaya daripada tidak punya salinan,
  karena tidak ada cara mengetahui transaksi mana yang hilang.
* **Replikasi lintas provider tidak tersedia di free tier.** Yang realistis
  hanya `pg_dump`/`pg_restore` berkala — snapshot bertanda waktu, bukan
  backup berkelanjutan.
* **Skalanya tidak sebanding.** Tiga pengguna, beberapa ribu transaksi
  setahun, ±200 byte per baris: seluruh buku kas beberapa ratus KB, dan
  dump-nya 24 KB pada data uji.

Satu database utama ditambah backup terverifikasi yang berjalan di luar
Lunafy memberi hampir seluruh manfaatnya tanpa menambah mode kegagalan baru.

---

## 10. Pemecahan masalah

**Bot tidak membalas, konsol tidak menampilkan "Terhubung sebagai"**
Token salah, atau proses tidak berjalan. Periksa konsol dari atas.

**`Koneksi database gagal` lalu bot berhenti**
Ini disengaja — bot menolak start tanpa database, karena bot yang menerima
pesan tapi tidak bisa menyimpannya lebih berbahaya daripada bot yang mati.
Penyebab tersering:
- Proyek Supabase sedang dijeda → Resume di dashboard
- `DATABASE_URL` memakai direct connection (IPv6) → ganti ke session pooler
- Password salah → ambil ulang dari tombol Connect

**`TypeError: connect() got an unexpected keyword argument 'sslmode'`**
Seharusnya tidak muncul; `app/config.py` menanganinya. Bila muncul, berarti
`DATABASE_URL` dipakai tanpa melewati `get_settings()` — laporkan sebagai bug.

**Query gagal setelah bot berjalan beberapa saat**
Kemungkinan `DATABASE_URL` memakai transaction mode (port 6543). Periksa
peringatan di konsol dan ganti ke port 5432.

**Database read-only**
Ukuran database melewati 500 MB. Bot memberi pesan khusus untuk ini dan
menyatakan dengan jelas bahwa transaksi **tidak tersimpan**. Jalankan `/excel`,
buat `pg_dump`, lalu periksa pertumbuhan `audit_logs` dan
`pending_transactions`.

**Bot membalas "belum terdaftar" kepada Anda sendiri**
`ADMIN_TELEGRAM_ID` tidak cocok dengan ID Telegram Anda, atau Anda belum
mengganti `__ADMIN_TELEGRAM_ID__` saat menjalankan SQL. Periksa:
```sql
SELECT telegram_id, role, is_active FROM users;
```

**Proses mati karena kehabisan memori**
256 MB cukup untuk pemakaian normal, tetapi `/excel` dengan ribuan transaksi
adalah operasi paling berat. Bila itu terjadi, turunkan `DB_POOL_SIZE` ke 2.

**AI selalu gagal, tapi bot tetap jalan**
Itu memang rancangannya: pra-parser bahasa Indonesia dan `/catat` bekerja
tanpa AI. Periksa konsol untuk kata `kuota`, `cooldown`, atau `provider`.

**Model gratis tiba-tiba hilang**
Ketersediaan model gratis berubah. Perbarui `OPENROUTER_MODELS` di tab
Variables, lalu restart.

---

## 11. Daftar periksa sebelum menyatakan selesai

Supabase:
- [ ] Proyek berstatus Active / Healthy
- [ ] `migrations/sql/001_003_skema_awal.sql` sudah dijalankan
- [ ] `SELECT version_num FROM alembic_version` → `003`
- [ ] 19 kategori ada, 1 baris `account_settings`, 1 admin dengan ID Anda
- [ ] Connection string yang dipakai adalah **session pooler port 5432**

Lunafy:
- [ ] Python 3.13 dipilih
- [ ] `app/`, `main.py`, `run.py`, `requirements.txt` sudah terunggah
- [ ] Semua variabel terisi, setiap model OpenRouter berakhiran `:free`
- [ ] Start command `python main.py`
- [ ] Konsol menampilkan keempat baris di bagian 6
- [ ] Perilaku restart sudah diuji sendiri

Telegram:
- [ ] `/start`, `/saldo`, `/excel` bekerja
- [ ] Pesan biasa menghasilkan konfirmasi, dan Simpan benar-benar menyimpan
- [ ] `/saldoawal` sudah diatur
- [ ] Semua anggota ditambahkan dan sudah mengirim `/start`
- [ ] Akun di luar daftar ditolak

Operasional:
- [ ] Pengingat perpanjangan Lunafy terpasang di HP (setiap 5 hari)
- [ ] Satu `pg_dump` sudah dibuat dan disimpan di luar kedua layanan
