# ARCHITECTURE — ZOI FINANCE AI

**Fase:** PHASE 2 — Architecture Design
**Dasar:** keputusan di `docs/REPOSITORY_AUDIT.md` bagian 10.
**Prinsip:** satu proses, modular, ringan, zero-cost, PostgreSQL sebagai sumber kebenaran.

---

## 1. Gambaran Umum

```
┌─────────────┐
│  Telegram   │  2–3 akun terotorisasi
└──────┬──────┘
       │ long polling (tanpa webhook, tanpa port)
┌──────▼───────────────────────────────────────────────┐
│  SATU PROSES PYTHON (aiogram 3.x)                    │
│                                                      │
│  middlewares:  auth → rate_limit → error_handler     │
│       ↓                                              │
│  handlers:  start catat saldo hariini bulanan        │
│             anggota excel hapus bantuan nlp          │
│       ↓                                              │
│  services:  permission  transaction  balance  report │
│       ↓                        ↓                     │
│  ai/router.py            excel/generator.py          │
│   1. parser.py (regex ID, Rp0)                       │
│   2. openrouter.py (model :free)                     │
│   3. gemini.py (free tier)                           │
│   4. gagal → entri manual                            │
│       ↓                                              │
│  database/ (SQLAlchemy 2.x async + repositories)     │
└──────┬───────────────────────────────────────────────┘
       │ asyncpg + TLS, pooler session mode, pool 3+2
┌──────▼──────┐
│ PostgreSQL  │  Supabase, sumber kebenaran
└─────────────┘
```

Satu proses karena server gratis Lunafy memberi 256 MB RAM untuk semuanya, dan untuk
3 pengguna layanan terpisah hanya menambah titik kegagalan. Long polling karena di
Lunafy port dialokasikan dengan biaya per bulan dan web server tidak diizinkan — jadi
tidak perlu URL publik, tidak perlu sertifikat, tidak perlu webhook secret.

Database terpisah di Supabase karena Lunafy tidak menyediakan database sama sekali,
dan karena server gratisnya dihapus bila tidak diperbarui tiap 7 hari. Catatan
keuangan tidak boleh ikut hilang bersama proses bot.

---

## 2. Struktur Direktori

```
ZOI-FINANCE-AI/
├── app/
│   ├── main.py                  bootstrap: config → db → bot → polling
│   ├── config.py                Pydantic Settings + normalisasi DATABASE_URL
│   ├── bot/
│   │   ├── handlers/            start, catat, saldo, hariini, bulanan,
│   │   │                        anggota, excel, hapus, bantuan, nlp, confirm
│   │   ├── keyboards/           confirm_kb, edit_kb, delete_kb
│   │   ├── middlewares/         auth, rate_limit, error_handler
│   │   └── filters/             IsAdmin, IsMember
│   ├── ai/
│   │   ├── router.py            orkestrasi 4 tingkat + penjagaan zero-cost
│   │   ├── openrouter.py        provider utama
│   │   ├── gemini.py            provider cadangan
│   │   ├── parser.py            pra-parser regex Indonesia (tanpa biaya)
│   │   ├── prompt.py            prompt bahasa Indonesia
│   │   └── scrub.py             redaksi data sensitif sebelum kirim ke AI
│   ├── database/
│   │   ├── models.py            6 tabel
│   │   ├── session.py           engine + sessionmaker + pool terbatas
│   │   └── repositories/        user, transaction, category, pending, audit, settings
│   ├── services/
│   │   ├── permission_service.py    penegakan peran (lapisan service)
│   │   ├── transaction_service.py   simpan/edit/hapus + duplikat + audit
│   │   ├── balance_service.py       saldo & rekap
│   │   └── report_service.py        data untuk Excel
│   ├── excel/generator.py       workbook 5 sheet
│   └── utils/                   money, dates, logger, sanitizer, validators
├── migrations/                  Alembic
├── tests/
├── docs/
├── Procfile
├── requirements.txt
├── .env.example
└── run.py
```

---

## 3. Lapisan dan Tanggung Jawab

| Lapisan | Boleh | Tidak boleh |
|---|---|---|
| `handlers/` | membaca pesan, memanggil service, membalas | query DB langsung, cek peran sendiri |
| `services/` | aturan bisnis, **penegakan peran**, transaksi DB | menyentuh objek aiogram |
| `repositories/` | query SQLAlchemy | aturan bisnis |
| `ai/` | parsing teks → dict | menulis ke DB |
| `excel/` | membangun workbook dari data | query DB |

**Penegakan peran ada di `services/`, bukan di `handlers/`.** Alasan dari audit: di
`finance-helper` pengecekan peran ada di lapisan data sehingga tidak bisa di-*bypass*
lewat handler lain. Filter aiogram (`IsAdmin`) hanya untuk UX — menyembunyikan tombol dan
memberi pesan ramah. Keputusan keamanan sesungguhnya diambil di service.

---

## 4. Alur Pencatatan Transaksi

```
Pesan masuk: "Bayar parkir motor 2 ribu di pasar Ciamis"
        │
  [middleware auth] telegram_id ada di users & is_active? ──tidak──> tolak, catat ke audit
        │ ya
  [ai/scrub.py] redaksi pola sensitif (deret digit panjang, kata kunci PIN/rekening)
        │
  [ai/router.py]
    1. parser.py regex ──berhasil & lengkap──┐
    2. OpenRouter (model :free) ─────────────┤
    3. Gemini (free tier) ───────────────────┤
    4. semuanya gagal → tawarkan entri manual, pesan asli TIDAK dibuang
                                             │
  [validasi] jumlah > 0, ≤ batas, kategori dikenal, tanggal masuk akal
        │ ada yang tidak jelas → tanya pengguna
  [pending_transactions] INSERT parsed_data JSONB, expires_at = now + 10 menit
        │
  Bot menampilkan ringkasan + [✅ Simpan] [✏️ Edit] [❌ Batalkan]
        │
  Pengguna menekan Simpan
        │
  [klaim atomik]  UPDATE pending_transactions
                  SET status='confirmed'
                  WHERE id=:id AND status='waiting' AND expires_at > now()
                  RETURNING id
        │ 0 baris → sudah diproses / kedaluwarsa → balas tanpa menyimpan apa pun
        │ 1 baris → kita pemegang klaim tunggal
  [cek duplikat] transaksi aktif dengan (jumlah, jenis, kategori, tanggal, pencatat)
                 yang sama dalam 5 menit terakhir? → tampilkan peringatan + minta
                 konfirmasi kedua
        │
  [transaction_service] INSERT transactions + INSERT audit_logs
                        dalam SATU transaksi database
        │
  Balas: "Tersimpan. Saldo sekarang Rp…"
```

**Proteksi klik-ganda** memakai `UPDATE … WHERE status='waiting' RETURNING` — bukan
"cek dulu lalu tulis". Pemeriksaan dan perubahan status terjadi dalam satu pernyataan
atomik, jadi dua klik yang datang bersamaan tidak mungkin keduanya menang. Ini menutup
kelemahan nomor 5 `finance-bot` di audit.

**Pending disimpan di PostgreSQL, bukan FSM memori.** Kalau proses bot *restart* saat
seseorang menunggu konfirmasi, data parsing tetap ada dan tombolnya masih bekerja.
Di Lunafy restart adalah hal biasa: dependensi dipasang ulang setiap start.

---

## 5. Mesin AI dan Penjagaan Zero-Cost

### Empat tingkat

| # | Tingkat | Biaya | Kapan dipakai |
|---|---|---|---|
| 1 | `parser.py` regex Indonesia | **Rp0** | pola jelas: "beli bensin 30rb", "bayar listrik 200 ribu" |
| 2 | OpenRouter model `:free` | Rp0 | kalimat kompleks, perlu kategori/lokasi |
| 3 | Gemini free tier | Rp0 | OpenRouter gagal/kuota habis |
| 4 | Entri manual | Rp0 | kedua provider mati |

Tingkat 1 lebih dulu bukan hanya demi penghematan: regex itu deterministik dan bisa
diuji, jadi kasus yang paling sering dipakai tidak pernah bergantung pada ketersediaan
layanan luar. Ini sekaligus jawaban atas kelemahan "satu provider saja" di audit.

### Penjagaan model berbayar

Tiga lapis, semuanya **sebelum** permintaan dikirim:

1. **Allowlist di konfigurasi.** `AI_OPENROUTER_MODELS` berisi daftar model; setiap nama
   wajib berakhiran `:free`. Nama yang tidak memenuhi syarat **ditolak saat startup**,
   bukan saat runtime — salah konfigurasi menggagalkan *boot*, bukan menagih biaya.
2. **Pemeriksaan per permintaan.** `router.py` memeriksa ulang nama model sesaat sebelum
   `POST`. Kalau tidak lolos, permintaan dibatalkan dan dicatat.
3. **Tidak ada eskalasi otomatis.** Tidak ada jalur kode yang mengganti model, menyalakan
   *billing*, atau membeli kredit. Kehabisan kuota = turun ke tingkat berikutnya, bukan
   naik ke model berbayar.

Nama model dapat dikonfigurasi karena ketersediaan model gratis berubah — aturan ZOI
bagian 8. Kalau kuota habis (HTTP 429 / respons kuota), provider itu ditandai *cooldown*
di memori supaya tidak dihujani permintaan ulang.

### Perlindungan data ke AI

`ai/scrub.py` berjalan sebelum teks dikirim keluar. Yang dikirim ke provider **hanya teks
transaksi** — tanpa `telegram_id`, tanpa nama anggota, tanpa saldo, tanpa riwayat.
Pola yang diredaksi: deret 12+ digit (mirip nomor kartu/rekening), dan teks di sekitar
kata `pin`, `password`, `sandi`, `otp`, `cvv`, `rekening`. Kalau pesan terlihat memuat
kredensial, bot menolak memprosesnya dengan AI dan menawarkan entri manual.

---

## 6. Peran dan Buku Kas Bersama

Satu buku kas. `transactions.created_by` adalah **atribusi**, bukan pemisah data —
inilah perbedaan inti dari `finance-bot` yang memfilter per `user_id`.

| Aksi | Admin | Member |
|---|:--:|:--:|
| Lihat saldo & seluruh riwayat | ✅ | ✅ |
| Tambah transaksi | ✅ | ✅ |
| Edit transaksi sendiri | ✅ | ✅ |
| Edit transaksi anggota lain | ✅ | ❌ |
| Hapus transaksi | ✅ | ❌ |
| Kelola anggota | ✅ | ❌ |
| Ekspor Excel | ✅ | ✅ (dapat dimatikan) |
| Ubah pengaturan & saldo awal | ✅ | ❌ |

Otorisasi memakai **`telegram_id` numerik**, tidak pernah `username` — username bisa
diganti kapan saja oleh pemiliknya. Pengguna tak dikenal tidak mendapat akses apa pun dan
percobaannya dicatat di `audit_logs`.

**Penghapusan bersifat *soft delete*** (`transactions.status='deleted'`). Catatan keuangan
tidak pernah benar-benar hilang dari database, sesuai aturan ZOI #11, dan tetap bisa
diaudit. Saldo hanya menjumlahkan baris berstatus `active`.

---

## 7. Uang, Waktu, dan Saldo

- **Uang:** `Decimal` di Python, `NUMERIC(18, 2)` di PostgreSQL. Tidak ada `float`
  di jalur mana pun, termasuk saat membaca keluaran AI (`Decimal(str(nilai))`).
  `(18,2)` dipilih karena `(15,2)` dan `(12,2)` yang dipakai repo referensi terlalu
  sempit untuk Rupiah.
- **Waktu:** semua `TIMESTAMPTZ` disimpan UTC. `transaction_date` bertipe `DATE` dalam
  pengertian kalender Asia/Jakarta. Tampilan selalu dikonversi ke Asia/Jakarta.
  Konsekuensinya "hari ini" ditentukan oleh tanggal Jakarta, bukan UTC — penting karena
  UTC+7 berarti pukul 00:00–07:00 Jakarta masih "hari sebelumnya" di UTC.
- **Saldo:** `saldo_awal + Σ(pemasukan aktif) − Σ(pengeluaran aktif)`, dihitung oleh
  PostgreSQL (`SUM` dengan `FILTER`), bukan di Python. Saldo tidak pernah disimpan
  sebagai kolom — tidak ada yang bisa menyimpang.

---

## 8. Ketahanan di Lunafy dan Supabase

| Risiko | Penanganan |
|---|---|
| Proses *restart* (sering di Lunafy: dependensi dipasang ulang tiap start) | Tidak ada status penting di memori. Pending ada di DB. Long polling menyambung sendiri. |
| RAM 256 MB | `pool_size=3, max_overflow=2`; file Excel dihapus setelah terkirim |
| Disk 512 MB | Log hanya ke stdout, tidak ke file; `output/` dibersihkan |
| TLS wajib | `DATABASE_URL` dinormalisasi: `sslmode` dibuang, `ssl=require` dipakai |
| Pooler tanpa prepared statement | Port 6543 terdeteksi; `prepared_statement_cache_size=0` + nama statement unik dipasang otomatis, dengan peringatan agar pindah ke session mode |
| Koneksi idle diputus pooler | `pool_pre_ping=True`, `pool_recycle=300` |
| Database jadi **read-only** di atas 500 MB | Pemantauan `pg_database_size()`, peringatan admin di 70% dan 90%; galat read-only dikenali dan dijelaskan khusus ke pengguna |
| Proyek Supabase dijeda karena aktivitas rendah 7 hari | Tugas keepalive menyentuh DB tiap 6 jam (`KEEPALIVE_HOURS`) |
| Server Lunafy dihapus karena lupa perbarui | Hanya proses bot yang hilang; catatan ada di Supabase. Dicegah dengan pengingat + `pg_dump` berkala |
| DB tidak terjangkau | Bot menolak start; pesan jujur ke pengguna; **tidak pernah** mengaku transaksi tersimpan |
| Kedua AI mati | Tawaran entri manual; pesan asli tidak dibuang |
| Jaringan Telegram putus | aiogram mencoba ulang; *error* disanitasi sebelum masuk log |

Aturan yang dipegang di seluruh kode: **jangan pernah membalas "tersimpan" sebelum
`COMMIT` berhasil.** Ini aturan ZOI #8 dan #12 di tingkat implementasi.

---

## 9. Konfigurasi

Dua lingkungan terpisah, satu sumber kode.

| | Termux (lokal) | Produksi |
|---|---|---|
| Sumber config | file `.env` | tab Variables di panel Lunafy |
| Database | SQLite/Postgres lokal, atau *mock* | Supabase PostgreSQL 17 |
| AI | *mock* untuk test | OpenRouter + Gemini |
| Dibutuhkan untuk test | tidak ada kredensial | — |

`config.py` memvalidasi saat *startup*: token ada, `DATABASE_URL` sah, daftar model AI
semuanya `:free`, `ADMIN_TELEGRAM_ID` berupa angka. Konfigurasi salah = gagal *boot*
dengan pesan jelas, bukan perilaku aneh saat dipakai.

Secret tidak pernah masuk log, pesan Telegram, dokumentasi, atau kode — `utils/sanitizer.py`
(diadaptasi dari finance-bot, MIT) menyaring semua *exception* dan URL sebelum dicatat.

---

## 10. Pengujian

| Lapisan | Cara uji | Butuh jaringan? |
|---|---|---|
| `utils/money`, `ai/parser` | unit, murni | tidak |
| `services/*` | SQLite in-memory via `aiosqlite` | tidak |
| `ai/router` | `httpx.MockTransport` | tidak |
| `excel/generator` | bangun workbook, baca ulang dengan openpyxl | tidak |
| handler | `AsyncMock` untuk objek aiogram | tidak |
| migrasi Alembic | `upgrade head` di PostgreSQL asli | **ya** |

Target: seluruh test inti berjalan di Termux tanpa kredensial apa pun. Hanya uji migrasi
dan uji integrasi provider AI yang butuh akses luar; keduanya ditandai `@pytest.mark.integration`
dan dilewati secara *default*.

---

## 11. Perintah Bot

| Perintah | Akses | Fungsi |
|---|---|---|
| `/start` | terotorisasi | identifikasi + instruksi |
| `/catat` | semua | entri transaksi terpandu |
| `/edit` | semua² | ubah transaksi tersimpan |
| `/saldo` | semua | saldo bersama |
| `/hariini` | semua | transaksi hari ini (Jakarta) |
| `/bulanan` | semua | rekap bulan ini |
| `/anggota` | semua | daftar anggota (admin: + kelola) |
| `/excel` | semua¹ | buat & kirim laporan 5 sheet |
| `/hapus` | **admin** | hapus transaksi |
| `/bantuan` | semua | bantuan |
| *teks biasa* | semua | jalur AI → konfirmasi |

¹ dapat dimatikan untuk member lewat pengaturan.
² member hanya bisa mengubah transaksi yang dicatatnya sendiri; daftar
pilihannya pun disaring agar tidak menampilkan yang tidak bisa dipilih.

---

## 12. Yang Dipakai Ulang dari Audit

| Dari | Komponen | Status |
|---|---|---|
| finance-bot (MIT) | `sanitizer.py` | disalin, komentar diterjemahkan, atribusi dicantumkan |
| finance-bot (MIT) | `validators.py` | disalin & disesuaikan untuk IDR |
| finance-bot (MIT) | backoff + deadline AI | disalin ke `ai/router.py`; bagian `proxies=` **ditulis ulang** (httpx ≥ 0.28) |
| finance-bot (MIT) | pola `error_handler` | disalin |
| finance-helper | pola peran di lapisan data | ditiru, ditulis ulang, 2 peran |
| finance-helper | pra-parser regex | ditiru, ditulis ulang untuk bahasa Indonesia |
| pago | deteksi duplikat | ditiru sebagai konsep |
| pago | prompt "JSON saja, tanpa backtick" | ditiru |
| Money-Bot | struktur pytest + CI | ditiru |

Kewajiban atribusi MIT: `LICENSE` + `docs/THIRD_PARTY_NOTICES.md` + komentar kepala pada
file turunan.

---

## 13. Yang Sengaja Tidak Dibangun

Supaya tetap ringan dan sesuai permintaan: tanpa webhook, tanpa Redis, tanpa Mini App,
tanpa OCR struk, tanpa transkripsi suara, tanpa multi-mata-uang, tanpa anggaran per
kategori, tanpa transaksi berulang, tanpa Docker. Masing-masing bisa ditambahkan kelak
tanpa membongkar arsitektur ini.

**Berikutnya:** PHASE 3 — fondasi proyek, model database, dan migrasi Alembic pertama.
