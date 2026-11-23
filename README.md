# ZOI FINANCE AI

**Smart Finance. Simple Control.**

Sistem manajemen keuangan bersama lewat Telegram untuk 2–3 orang. Catat
pengeluaran dengan bahasa Indonesia sehari-hari, lihat saldo bersama, dan unduh
laporan Excel.

```
Anda:  Bayar parkir motor 2 ribu di pasar Ciamis

Bot:   Konfirmasi transaksi

       💸 Jenis: Pengeluaran
       💵 Jumlah: Rp2.000
       🏷 Kategori: Transportasi
       📝 Keterangan: Bayar parkir motor
       📍 Lokasi: Pasar Ciamis
       📅 Tanggal: 23 November 2026
       👤 Dicatat oleh: Fariz

       Simpan transaksi ini?
       [✅ Simpan]  [✏️ Edit]  [❌ Batalkan]
```

---

## Fitur

- **Bahasa Indonesia sehari-hari.** Memahami "2 ribu", "25rb", "1,5 juta",
  "500.000", serta "kemarin", "3 hari lalu", dan "di pasar Ciamis".
- **Selalu dikonfirmasi.** Tidak ada transaksi hasil AI yang tersimpan tanpa
  persetujuan Anda. Setiap bagian bisa diedit sebelum disimpan.
- **Satu buku kas bersama.** Semua anggota melihat saldo dan riwayat yang sama;
  setiap catatan menyimpan siapa yang mencatatnya.
- **Dua peran.** Admin bisa menghapus, mengelola anggota, dan mengubah catatan
  siapa pun; member mencatat dan mengubah catatannya sendiri.
- **Laporan Excel lima sheet.** Dashboard, Transaksi, Pemasukan, Pengeluaran,
  Rekap Bulanan — dengan format Rupiah, header dibekukan, filter, dan rumus.
- **Zero-cost.** Pra-parser bahasa Indonesia menangani kalimat yang paling sering
  dipakai tanpa memanggil AI sama sekali. Bila perlu AI, hanya model gratis yang
  dipakai — bot menolak start bila ada model berbayar di konfigurasinya.
- **Tetap jalan saat AI mati.** Pra-parser dan /catat tidak butuh jaringan ke
  provider mana pun.
- **Catatan tidak hilang.** Penghapusan bersifat *soft delete*, dan setiap
  perubahan tercatat di jejak audit dengan nilai sebelum dan sesudahnya.

## Perintah

| Perintah | Fungsi |
|---|---|
| *(pesan biasa)* | Catat transaksi lewat bahasa Indonesia |
| `/catat` | Catat langkah demi langkah (tanpa AI) |
| `/edit` | Ubah transaksi yang sudah tersimpan |
| `/saldo` | Saldo bersama dan rekap bulan ini |
| `/hariini` | Transaksi hari ini |
| `/bulanan` | Rekap per bulan dengan saldo akhir berjalan |
| `/anggota` | Daftar anggota |
| `/excel` | Buat dan kirim laporan Excel |
| `/bantuan` | Bantuan |
| `/hapus` | Hapus transaksi — **admin** |
| `/saldoawal` | Atur saldo awal — **admin** |

---

## Arsitektur

Satu proses Python, *long polling*, PostgreSQL sebagai sumber kebenaran.

```
Telegram → aiogram 3.x
             ↓  middleware: error_handler → auth → rate_limit
           handlers
             ↓
           services (aturan bisnis + penegakan hak akses)
             ↓                        ↓
   ai/router.py              excel/generator.py
   1. parser.py (regex Indonesia, Rp0)
   2. OpenRouter (model :free)
   3. Gemini (free tier)
   4. gagal → entri manual
             ↓
   database/ (SQLAlchemy 2.x async)
             ↓
        PostgreSQL
```

Rinciannya: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) ·
[`docs/DATABASE.md`](docs/DATABASE.md)

### Teknologi

| | |
|---|---|
| Bahasa | Python 3.11+ (3.13 di produksi) |
| Telegram | aiogram 3.33 |
| Database | PostgreSQL 17 · SQLAlchemy 2.1 (async, asyncpg) · Alembic |
| AI utama | OpenRouter — hanya model `:free` |
| AI cadangan | Google Gemini free tier |
| Excel | OpenPyXL |
| HTTP | httpx |
| Konfigurasi | Pydantic Settings |
| Hosting bot | Lunafy (server Python gratis) |
| Database | Supabase PostgreSQL 17 |
| Pengembangan | Android Termux |

---

## Mulai cepat

### Di HP (Termux) — panduan lengkap: [`docs/TERMUX_SETUP.md`](docs/TERMUX_SETUP.md)

```bash
pkg install -y python git nano
git clone https://github.com/Fariz23zoi/ZOI-FINANCE-AI.git
cd ZOI-FINANCE-AI
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env && nano .env     # isi token dan Telegram ID Anda
alembic upgrade head
pytest -q                             # 298 test, tanpa kredensial
python run.py
```

### Di produksi — panduan lengkap: [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)

Bot di **Lunafy**, database di **Supabase**. Keduanya dipisah karena Lunafy
tidak menyediakan database, dan server gratisnya dihapus bila tidak diperbarui
tiap 7 hari — catatan keuangan tidak boleh ikut hilang bersama server.

1. **Supabase** — pastikan proyek Active, lalu jalankan
   `migrations/sql/001_003_skema_awal.sql` di SQL Editor setelah mengganti
   `__ADMIN_TELEGRAM_ID__` dengan Telegram ID Anda.
2. **Lunafy** — buat server Python 3.13, unggah `app/`, `main.py`, `run.py`,
   dan `requirements.txt`, isi tab Variables, lalu start dengan
   `python main.py`.

Pakai connection string **Session pooler (port 5432)** dari Supabase. Direct
connection pada paket Free hanya IPv6, dan transaction mode (6543) tidak
mendukung prepared statements.

Lalu dari Telegram, sebagai admin:

```
/saldoawal 1500000
/anggota tambah 987654321 Nama Anggota
```

---

## Konfigurasi

Salin `.env.example` ke `.env`. Yang wajib:

| Variabel | Keterangan |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Dari [@BotFather](https://t.me/BotFather) |
| `ADMIN_TELEGRAM_ID` | ID **numerik** Anda, dari [@userinfobot](https://t.me/userinfobot) |
| `DATABASE_URL` | Session pooler Supabase, atau `sqlite+aiosqlite:///./zoi_local.db` untuk lokal |
| `OPENROUTER_MODELS` | Daftar dipisah koma; **setiap nama wajib berakhiran `:free`** |

Opsional: `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, `GEMINI_MODELS`, `TIMEZONE`,
`CURRENCY`, `MAX_TRANSACTION_AMOUNT`, `PENDING_EXPIRE_MINUTES`, `LOG_LEVEL`.

Tanpa kunci AI, bot tetap berguna: pra-parser bahasa Indonesia dan `/catat`
bekerja sepenuhnya tanpa jaringan ke provider mana pun.

`DATABASE_URL` dari Supabase bisa ditempel apa adanya, termasuk
`?sslmode=require` — `app/config.py` menormalisasinya untuk asyncpg, dan
mendeteksi mode pooler yang butuh penyesuaian.

---

## Pengujian

```bash
pytest -q                        # semuanya (SQLite in-memory)
pytest tests/test_parser.py -v   # pemahaman bahasa Indonesia
pytest -k duplikat -v            # proteksi duplikat
```

Seluruh test berjalan tanpa kredensial, tanpa database eksternal, dan tanpa
jaringan. Panggilan AI dipalsukan dengan `httpx.MockTransport`; objek Telegram
dengan `AsyncMock`.

Menjalankan suite yang sama di PostgreSQL:

```bash
ZOI_TEST_DATABASE_URL=postgresql+asyncpg://user:pass@host/db pytest -q
```

**Status:** 298 test, lulus di SQLite dan PostgreSQL 16.15.
CI (`.github/workflows/tests.yml`) menjalankan keduanya, ditambah uji migrasi
naik-turun-naik.

Presisi uang dijamin oleh `NUMERIC` PostgreSQL. SQLite tidak punya tipe DECIMAL,
jadi untuk verifikasi akhir jalankan juga suite di PostgreSQL.

---

## Backup

PostgreSQL adalah sumber kebenaran; Excel hanya laporan yang dihasilkan darinya.

Backup otomatis berjalan di **GitHub Actions** setiap minggu, bukan di Lunafy —
server gratis Lunafy dihapus bila tidak diperbarui tiap 7 hari, jadi backup
yang berjalan di sana akan mati bersama hal yang dilindunginya.

Setiap kali berjalan, workflow itu bukan hanya membuat file: ia **memulihkan
dump-nya ke PostgreSQL kosong**, lalu membandingkan jumlah baris dan **saldo**
dengan sumbernya. Dump yang belum pernah dibuktikan bisa dipulihkan bukan
backup. Hasilnya dienkripsi AES256 dan disimpan sebagai artifact 90 hari.

Manual, kapan saja:

```bash
DATABASE_URL="postgresql://..." ./scripts/backup.sh
```

Prosedur lengkap, termasuk alasan **tidak** memakai database kedua yang hidup:
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) bagian 9.

## Keamanan

Ringkasnya: otorisasi lewat Telegram ID numerik (bukan username), peran ditegakkan
di lapisan service, hanya teks transaksi yang dikirim ke provider AI, pesan yang
memuat PIN/password/kunci API tidak dikirim ke mana pun, uang selalu `Decimal`,
penghapusan bersifat *soft delete*, dan setiap perubahan tercatat di jejak audit.

Termasuk daftar **apa yang tidak dilindungi**:
[`docs/SECURITY.md`](docs/SECURITY.md).

---

## Dokumentasi

| Dokumen | Isi |
|---|---|
| [`docs/REPOSITORY_AUDIT.md`](docs/REPOSITORY_AUDIT.md) | Audit empat repo referensi dan alasan membangun implementasi bersih |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Lapisan, alur pencatatan, mesin AI, ketahanan di hosting gratis |
| [`docs/DATABASE.md`](docs/DATABASE.md) | Enam tabel, rumus saldo, migrasi, pemantauan kuota |
| [`docs/SECURITY.md`](docs/SECURITY.md) | Model ancaman, penanganan secret, batas yang diketahui |
| [`docs/TERMUX_SETUP.md`](docs/TERMUX_SETUP.md) | Pemasangan di Android, langkah demi langkah |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Deploy ke Lunafy + Supabase, verifikasi, backup, pemecahan masalah |
| [`docs/THIRD_PARTY_NOTICES.md`](docs/THIRD_PARTY_NOTICES.md) | Atribusi MIT untuk kode yang dipakai ulang |

---

## Lisensi

MIT — lihat [`LICENSE`](LICENSE).

Sebagian kode diadaptasi dari [RibasomR/finance-bot](https://github.com/RibasomR/finance-bot)
(MIT). Pola desain dari [nikamurkaa/finance-helper](https://github.com/nikamurkaa/finance-helper),
[alainrk/pago](https://github.com/alainrk/pago), dan
[cenoff/Money-Bot](https://github.com/cenoff/Money-Bot) — semuanya MIT.
Rinciannya di [`docs/THIRD_PARTY_NOTICES.md`](docs/THIRD_PARTY_NOTICES.md).

Proyek ini berdiri sendiri, terpisah dari ZOI Universe dan ZOI AI Clipper.
