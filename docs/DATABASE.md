# DATABASE — ZOI FINANCE AI

**Fase:** PHASE 2 — Database Design
**DBMS:** PostgreSQL 17 (Supabase) · SQLAlchemy 2.x async (asyncpg) · Alembic

PostgreSQL adalah **sumber kebenaran**. Excel hanya laporan yang dihasilkan dari sini.

---

## 1. Aturan Dasar

1. Uang: `NUMERIC(18, 2)` ↔ `Decimal`. **Tidak ada `float`/`REAL` di mana pun.**
2. Waktu: `TIMESTAMPTZ` disimpan UTC; `transaction_date` bertipe `DATE` (kalender Jakarta).
3. Saldo **tidak pernah disimpan** sebagai kolom — selalu dihitung.
4. Transaksi tidak pernah dihapus fisik — *soft delete* lewat `status`.
5. Setiap perubahan uang menulis `audit_logs` dalam **transaksi database yang sama**.
6. Semua relasi pakai *foreign key*; kolom yang dipakai untuk filter diberi indeks.

---

## 2. Enum

```sql
CREATE TYPE user_role          AS ENUM ('admin', 'member');
CREATE TYPE transaction_type   AS ENUM ('income', 'expense');
CREATE TYPE transaction_status AS ENUM ('active', 'deleted');
CREATE TYPE pending_status     AS ENUM ('waiting', 'confirmed', 'cancelled', 'expired');
```

---

## 3. `users`

| Kolom | Tipe | Keterangan |
|---|---|---|
| `id` | `SERIAL PK` | |
| `telegram_id` | `BIGINT UNIQUE NOT NULL` | **dasar otorisasi**, bukan username |
| `full_name` | `VARCHAR(255) NOT NULL` | nama tampil anggota |
| `username` | `VARCHAR(255) NULL` | informatif saja, bisa berubah |
| `role` | `user_role NOT NULL DEFAULT 'member'` | |
| `is_active` | `BOOLEAN NOT NULL DEFAULT TRUE` | nonaktifkan tanpa menghapus riwayat |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |

Indeks: `telegram_id` (unik), `(is_active)`.

`BIGINT` karena Telegram ID melampaui jangkauan `INTEGER`.
Anggota yang keluar di-`is_active = FALSE`, **tidak dihapus**, supaya `created_by` pada
transaksi lamanya tetap sah.

---

## 4. `categories`

| Kolom | Tipe | Keterangan |
|---|---|---|
| `id` | `SERIAL PK` | |
| `name` | `VARCHAR(100) NOT NULL` | |
| `transaction_type` | `transaction_type NOT NULL` | kategori pemasukan vs pengeluaran |
| `is_active` | `BOOLEAN NOT NULL DEFAULT TRUE` | |

Batasan: `UNIQUE (name, transaction_type)`.

Kategori awal (disemai oleh migrasi, bahasa Indonesia):

*Pengeluaran:* Makanan & Minuman · Transportasi · Belanja Harian · Tagihan & Utilitas ·
Kesehatan · Pendidikan · Rumah Tangga · Komunikasi & Pulsa · Hiburan · Sosial & Keluarga ·
Pekerjaan · Lain-lain

*Pemasukan:* Gaji · Usaha · Penjualan · Bonus · Hadiah · Pinjaman Masuk · Lain-lain

Kategori "Lain-lain" ada di kedua jenis dan **wajib ada** — ini tujuan aman ketika AI
tidak yakin, sehingga transaksi tidak pernah gagal hanya karena kategori tidak dikenal.

---

## 5. `transactions`

| Kolom | Tipe | Keterangan |
|---|---|---|
| `id` | `BIGSERIAL PK` | |
| `transaction_type` | `transaction_type NOT NULL` | |
| `amount` | `NUMERIC(18,2) NOT NULL` | `CHECK (amount > 0)` |
| `category_id` | `INT NOT NULL REFERENCES categories(id) ON DELETE RESTRICT` | |
| `description` | `TEXT NULL` | mis. "Bayar parkir motor" |
| `location` | `VARCHAR(255) NULL` | mis. "Pasar Ciamis" |
| `transaction_date` | `DATE NOT NULL` | tanggal kalender Jakarta |
| `created_by` | `INT NOT NULL REFERENCES users(id) ON DELETE RESTRICT` | atribusi |
| `updated_by` | `INT NULL REFERENCES users(id) ON DELETE RESTRICT` | |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |
| `updated_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |
| `status` | `transaction_status NOT NULL DEFAULT 'active'` | |

Batasan dan indeks:

```sql
CHECK (amount > 0)
CHECK (amount <= 999999999999.99)
INDEX (transaction_date)
INDEX (status)
INDEX (transaction_date, status)      -- /hariini, /bulanan, rekap Excel
INDEX (transaction_type, status)      -- sheet PEMASUKAN / PENGELUARAN
INDEX (created_by)                    -- cek "transaksi siapa" untuk izin edit
INDEX (created_by, created_at)        -- deteksi duplikat
```

**`ON DELETE RESTRICT`, bukan `CASCADE`.** Perbedaan penting dari `finance-bot` yang
memakai `CASCADE` pada `user_id`: di sana menghapus satu pengguna akan **melenyapkan
seluruh transaksinya**. Pada buku kas bersama itu berarti kehilangan catatan keuangan
yang masih memengaruhi saldo bersama. `RESTRICT` membuat hal itu mustahil.

Tidak ada kolom `user_id` yang membagi data. Semua anggota membaca tabel yang sama.

---

## 6. `account_settings`

| Kolom | Tipe | Keterangan |
|---|---|---|
| `id` | `INT PK` | `CHECK (id = 1)` — baris tunggal |
| `initial_balance` | `NUMERIC(18,2) NOT NULL DEFAULT 0` | diatur manual oleh admin |
| `currency` | `VARCHAR(3) NOT NULL DEFAULT 'IDR'` | |
| `timezone` | `VARCHAR(64) NOT NULL DEFAULT 'Asia/Jakarta'` | |
| `member_can_export` | `BOOLEAN NOT NULL DEFAULT TRUE` | sakelar `/excel` untuk member |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |
| `updated_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |

`CHECK (id = 1)` memastikan tidak mungkin ada dua baris pengaturan yang saling bertentangan
— saldo awal yang ganda akan membuat saldo salah tanpa gejala.

---

## 7. `pending_transactions`

| Kolom | Tipe | Keterangan |
|---|---|---|
| `id` | `BIGSERIAL PK` | |
| `telegram_user_id` | `BIGINT NOT NULL` | pemilik pending |
| `parsed_data` | `JSONB NOT NULL` | hasil parsing + sumbernya (`parser`/`openrouter`/`gemini`) |
| `source_text` | `TEXT NOT NULL` | **pesan asli disimpan** — aturan ZOI: jangan dibuang |
| `status` | `pending_status NOT NULL DEFAULT 'waiting'` | |
| `expires_at` | `TIMESTAMPTZ NOT NULL` | dibuat + 10 menit |
| `transaction_id` | `BIGINT NULL REFERENCES transactions(id)` | terisi saat dikonfirmasi |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |

Indeks: `(telegram_user_id, status)`, `(status, expires_at)`.

**Klaim atomik** untuk mencegah transaksi ganda:

```sql
UPDATE pending_transactions
   SET status = 'confirmed'
 WHERE id = :id
   AND status = 'waiting'
   AND expires_at > now()
RETURNING id;
```

Nol baris artinya pending sudah dikonfirmasi, dibatalkan, atau kedaluwarsa — bot membalas
apa adanya dan **tidak menyimpan apa pun**. Karena pemeriksaan dan perubahan status
terjadi dalam satu pernyataan, dua klik bersamaan tidak mungkin keduanya lolos.

`transaction_id` memberi jejak dua arah: setiap transaksi hasil AI bisa dilacak kembali ke
teks aslinya. Berguna saat ada selisih dan kita perlu tahu apa yang sebenarnya ditulis
anggota.

Pembersihan: baris berstatus `waiting` yang `expires_at` sudah lewat ditandai `expired`
saat ada aktivitas berikutnya, bukan lewat penjadwal terpisah — satu hal lagi yang
bisa gagal tanpa diketahui.

---

## 8. `audit_logs`

| Kolom | Tipe | Keterangan |
|---|---|---|
| `id` | `BIGSERIAL PK` | |
| `user_id` | `INT NULL` | **tanpa FK** — jejak tetap utuh apa pun yang terjadi pada `users` |
| `telegram_id` | `BIGINT NULL` | tetap tercatat untuk pengguna tak dikenal |
| `action` | `VARCHAR(50) NOT NULL` | lihat daftar di bawah |
| `transaction_id` | `BIGINT NULL` | **tanpa FK**, alasan sama |
| `details` | `JSONB NULL` | nilai sebelum/sesudah pada aksi edit |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT now()` | |

Indeks: `(created_at)`, `(action)`, `(transaction_id)`.

Aksi yang dicatat: `transaction_create`, `transaction_update`, `transaction_delete`,
`member_add`, `member_update`, `member_deactivate`, `settings_update`,
`unauthorized_access`, `export_generated`, `ai_provider_failure`, `quota_warning`.

**Sengaja tanpa *foreign key*.** Jejak audit harus bertahan lebih lama dari baris yang
dirujuknya; FK dengan `CASCADE` akan menghapus bukti, dan FK dengan `RESTRICT` akan
memblokir operasi administratif yang sah. Nilai `user_id` dan `transaction_id` disimpan
apa adanya sebagai catatan sejarah, bukan sebagai relasi hidup.

`unauthorized_access` dicatat beserta `telegram_id`-nya meski orang itu tidak ada di
`users` — ini satu-satunya cara mengetahui ada yang mencoba masuk.

---

## 9. Rumus Saldo

```sql
SELECT s.initial_balance
     + COALESCE(SUM(t.amount) FILTER (WHERE t.transaction_type = 'income'),  0)
     - COALESCE(SUM(t.amount) FILTER (WHERE t.transaction_type = 'expense'), 0)
       AS balance
  FROM account_settings s
  LEFT JOIN transactions t ON t.status = 'active'
 WHERE s.id = 1
 GROUP BY s.initial_balance;
```

Dihitung PostgreSQL dengan `NUMERIC`, bukan di Python. Baris berstatus `deleted`
tidak ikut dihitung tetapi tetap tersimpan.

Rekap bulanan memakai `date_trunc('month', transaction_date)`; `transaction_date` sudah
dalam kalender Jakarta sehingga tidak ada pergeseran bulan akibat UTC.

---

## 10. Koneksi

```python
# app/database/session.py
create_async_engine(
    normalized_url,              # sslmode dibuang → ssl=require
    pool_size=3,
    max_overflow=2,
    pool_pre_ping=True,          # koneksi mati dibuang sebelum dipakai
    pool_recycle=300,
    echo=False,                  # jangan pernah True di produksi: SQL berisi data
)
```

Pool dibuat kecil karena dua batas sekaligus: server gratis Lunafy memberi 256 MB RAM
untuk seluruh proses, dan proyek Supabase Free punya kuota koneksi terbatas. Untuk
2–3 pengguna, 3+2 sudah lapang.

**Normalisasi URL wajib.** Supabase memberi `?sslmode=require`, tetapi asyncpg tidak
mengenal parameter itu dan gagal saat koneksi pertama dengan
`TypeError: connect() got an unexpected keyword argument 'sslmode'` — sudah diverifikasi
di `docs/REPOSITORY_AUDIT.md` bagian 7. `config.py` membuang `sslmode` dari *query string*
dan menggantinya dengan `ssl=require`.

`pool_pre_ping=True` penting karena proses bot berumur panjang sementara database bisa
memutus koneksi idle; tanpa ini, *query* pertama setelah masa senggang akan gagal.

---

## 11. Migrasi

Alembic, penamaan `YYYY_MM_DD_HHMM-NNN_deskripsi` (pola dari finance-bot).

| # | Isi |
|---|---|
| `001_initial_schema` | 4 enum, 6 tabel, semua indeks dan batasan |
| `002_seed_categories` | kategori awal Indonesia + baris `account_settings` id=1 |
| `003_seed_admin` | admin dari `ADMIN_TELEGRAM_ID` (idempoten) |

Semua migrasi punya `downgrade()` yang benar. Migrasi dijalankan sebagai langkah terpisah
sebelum proses bot naik — **tidak** otomatis saat *startup*, agar dua instance saat
*redeploy* tidak bermigrasi bersamaan.

---

## 12. Pemantauan Kuota

Ambang read-only Supabase paket Free adalah **ukuran database 500 MB** — bukan disk.
Supabase memberi 1 GB disk, tetapi yang memicu read-only adalah kuota ukuran database:

```sql
SELECT pg_database_size(current_database());
```

Diperiksa saat `/saldo` dan `/excel`. Ambang 70% → peringatan ke admin; 90% →
peringatan mendesak + saran `pg_dump`. Aturan ZOI: peringatkan admin, jangan diam-diam
kehilangan atau merusak data keuangan.

Read-only bukan sekadar melambat: penulisan berhenti sepenuhnya, sehingga transaksi
baru tidak bisa disimpan. `app/bot/middlewares/error_handler.py` mengenali galat itu
dan memberi pesan khusus yang menyatakan dengan jelas bahwa transaksi **tidak
tersimpan** — bukan pesan galat umum.

Perkiraan nyata: satu baris transaksi ± 200 byte. 500 MB menampung ratusan ribu baris —
tiga pengguna tidak akan mendekatinya dalam bertahun-tahun. Pemantauan ini terutama
menjaga dari pertumbuhan `audit_logs` dan `pending_transactions` yang tak terduga.

---

## 13. Backup dan Restore

Supabase paket Free punya backup hariannya sendiri, tetapi tetap perlu backup mandiri.
Alasannya bukan soal retensi, melainkan rantai kegagalan: server Lunafy gratis dihapus
bila tidak diperbarui tiap 7 hari, itu menghentikan tugas keepalive, lalu proyek
Supabase dijeda tujuh hari kemudian, dengan jendela pemulihan 90 hari. Backup yang Anda
pegang sendiri tidak bergantung pada rantai itu.

Karena itu backup mandiri wajib:

```bash
pg_dump "$DATABASE_URL" -Fc -f zoi-$(date +%F).dump    # bulanan
/excel di Telegram                                      # salinan terbaca manusia
```

Prosedur lengkap ada di `docs/DEPLOYMENT.md` bagian 9.

---

## 14. Memasang Skema

Dua jalur, keduanya menghasilkan database yang sama:

| Jalur | Kapan dipakai |
|---|---|
| `migrations/sql/001_003_skema_awal.sql` lewat SQL Editor Supabase | Pemasangan pertama dari HP, tanpa perlu asyncpg di Termux |
| `alembic upgrade head` | Bila asyncpg tersedia, dan untuk setiap migrasi setelah 003 |

File SQL itu dihasilkan dengan `alembic upgrade head --sql` dan ikut mengisi
`alembic_version`, jadi Alembic mengenali database sebagai sudah berada di 003 dan
migrasi berikutnya berjalan normal.

**Catatan untuk migrasi baru:** agar `--sql` tetap bekerja, migrasi tidak boleh
bercabang berdasarkan hasil query dan tidak boleh memakai parameter terikat pada
`sa.text()`. Keduanya pernah menghasilkan SQL yang gagal tanpa pesan error — migrasi
002 menulis `VALUES (NULL, ...)` sehingga 19 kategori tidak masuk, dan migrasi 003
menulis `WHERE telegram_id = NULL` lalu melewatkan INSERT admin. Keduanya kini memakai
literal SQL dan `ON CONFLICT`. Lihat komentar di masing-masing file migrasi.
