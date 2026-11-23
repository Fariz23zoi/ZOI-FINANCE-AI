# SECURITY — ZOI FINANCE AI

Dokumen ini menjelaskan apa yang dilindungi, bagaimana cara melindunginya, dan
**apa yang TIDAK dilindungi**. Bagian terakhir itu sama pentingnya: batas yang
tidak diketahui lebih berbahaya daripada batas yang diketahui.

---

## 1. Otorisasi

**Hanya Telegram ID numerik.** Tidak pernah username.

Username bisa diganti pemiliknya kapan saja. Kalau otorisasi bergantung pada
username, orang lain yang mengambil username yang dilepas bisa mewarisi aksesnya.
Karena itu `app/utils/validators.py` **menolak** masukan yang diawali `@` dengan
pesan yang menjelaskan sebabnya.

Nama dan username tetap dicatat, tetapi hanya sebagai informasi tampilan dan
diperbarui otomatis. Perubahan nama tidak pernah memengaruhi hak akses — ini diuji
di `tests/test_middleware.py`.

**Pengguna di luar daftar tidak pernah mencapai handler mana pun.**
`AuthMiddleware` berjalan sebelum semua handler. Pengguna yang tidak ada di tabel
`users`, atau yang `is_active = false`, mendapat penolakan dan percobaannya dicatat
ke `audit_logs` dengan aksi `unauthorized_access` — beserta Telegram ID-nya, meski
orang itu tidak ada di `users`. Itu satu-satunya cara mengetahui ada yang mencoba
masuk.

**Tidak ada cara mengangkat diri sendiri menjadi admin.** Administrator pertama
hanya bisa lahir dari migrasi 003 yang membaca `ADMIN_TELEGRAM_ID`. Tidak ada
perintah Telegram yang bisa membuat admin dari nol, dan tidak ada admin bawaan.
Tanpa konfigurasi itu bot menolak semua orang — itu disengaja: bot keuangan yang
menerima siapa saja lebih berbahaya daripada bot yang menolak pemiliknya.

---

## 2. Peran dan di mana ditegakkan

| Aksi | Admin | Member |
|---|:--:|:--:|
| Lihat saldo & seluruh riwayat | ✅ | ✅ |
| Tambah transaksi | ✅ | ✅ |
| Edit transaksi sendiri | ✅ | ✅ |
| Edit transaksi anggota lain | ✅ | ❌ |
| Hapus transaksi | ✅ | ❌ |
| Kelola anggota | ✅ | ❌ |
| Ubah saldo awal & pengaturan | ✅ | ❌ |
| Ekspor Excel | ✅ | ✅ (dapat dimatikan) |

**Penegakannya ada di lapisan service**, di `app/services/permission_service.py`,
dan dipanggil dari dalam setiap service yang mengubah data.

Filter aiogram (`IsAdmin`, `IsMember`) **hanya untuk UX** — menentukan handler mana
yang menanggapi dan memberi pesan yang ramah. Filter bisa terlewat bila ada handler
lain yang cocok lebih dulu; service tidak. Pola ini diambil dari
nikamurkaa/finance-helper, yang menegakkan peran di lapisan data sehingga tidak
bisa di-*bypass* lewat jalur handler lain.

Dua pengaman tambahan:

- **Admin terakhir tidak bisa diturunkan atau dinonaktifkan.** Tanpa admin, tidak
  ada lagi yang bisa mengelola anggota atau menghapus transaksi, dan satu-satunya
  jalan keluar adalah mengubah database secara manual.
- **Kepemilikan pending diperiksa pada setiap callback.** `callback_data` terlihat
  oleh klien dan ID-nya bisa ditebak, jadi `claim`, `cancel`, dan
  `update_parsed_data` semuanya menyertakan `telegram_user_id` dalam klausa WHERE.
  Pesan galat untuk pending milik orang lain dibuat **sama** dengan pesan untuk
  pending yang tidak ada, supaya keberadaannya tidak terbocorkan.

---

## 3. Yang dikirim ke provider AI

**Hanya teks transaksi.** Tanpa Telegram ID, tanpa nama anggota, tanpa saldo, tanpa
riwayat, tanpa daftar anggota. Prompt di `app/ai/prompt.py` hanya memuat teks pesan,
tanggal hari ini, dan daftar nama kategori.

`app/ai/scrub.py` adalah lapisan terakhir sebelum teks keluar, dengan dua tingkat:

**Tolak** — pesan tidak dikirim ke mana pun, pengguna ditawari entri manual:
kata `pin`, `password`, `sandi`, `otp`, `cvv`, `kode verifikasi`, `seed phrase`,
`private key`, dan pola kunci API (`sk-…`, `AIza…`, `ghp_…`).

Pencocokan memakai batas kata, sehingga "bayar **pin**jaman 500rb" tidak ikut
tertolak. Ini diuji di `tests/test_scrub.py`.

**Redaksi** — pesan dikirim setelah dibersihkan: deret 12–24 digit (panjang nomor
kartu dan rekening bank Indonesia) diganti `[nomor]`. Jumlah uang biasa tidak
tersentuh, sehingga parsing tetap berjalan.

**Tidak ada data yang dikirim ketika pesan ditolak** — diuji dengan memeriksa bahwa
jumlah panggilan HTTP ke kedua provider tetap nol.

---

## 4. Penjagaan zero-cost

Tiga lapis, semuanya **sebelum** permintaan dikirim:

1. **Saat startup** (`app/config.py`): setiap nama di `OPENROUTER_MODELS` wajib
   berakhiran `:free`. Satu nama yang tidak memenuhi syarat membuat **seluruh**
   daftar ditolak dan bot gagal boot. Salah konfigurasi menggagalkan *boot*, bukan
   menimbulkan tagihan.
2. **Per permintaan** (`app/ai/openrouter.py`): nama model diperiksa ULANG tepat
   sebelum `POST`. Dua pemeriksaan di dua tempat berbeda berarti tidak ada satu pun
   jalur kode yang bisa mengirim permintaan ke model berbayar.
3. **Tidak ada eskalasi.** Tidak ada jalur kode yang mengganti model, menyalakan
   *billing*, atau membeli kredit. Kehabisan kuota (HTTP 429/402) membuat provider
   masuk *cooldown* 15 menit dan sistem **turun** ke tingkat berikutnya, bukan naik
   ke model berbayar.

---

## 5. Integritas data keuangan

**Tidak ada float.** Uang memakai `Decimal` di Python dan `NUMERIC(18, 2)` di
PostgreSQL, termasuk saat membaca keluaran AI (`Decimal(str(nilai))`). Satu-satunya
konversi ke `float` terjadi pada langkah terakhir saat menulis ke sel Excel, karena
format xlsx menyimpan angka sebagai IEEE 754 double — dan seluruh perhitungan sudah
selesai di PostgreSQL sebelum itu.

**Saldo tidak pernah disimpan.** Selalu dihitung dari `saldo_awal + Σpemasukan −
Σpengeluaran` oleh PostgreSQL. Kolom saldo yang disimpan bisa menyimpang dari
transaksinya tanpa gejala.

**Penghapusan bersifat *soft delete*.** `transactions.status` diubah menjadi
`deleted`; barisnya tetap ada. Saldo hanya menjumlahkan baris `active`. Seluruh isi
transaksi yang dihapus disalin ke `audit_logs`, jadi bila kelak ada pertanyaan
tentang catatan yang hilang, jawabannya ada di sana.

**Relasi memakai `ON DELETE RESTRICT`, bukan `CASCADE`.** Dengan CASCADE,
menghapus satu anggota akan melenyapkan seluruh transaksinya — dan pada buku kas
bersama, saldo berubah tanpa jejak. Anggota yang keluar dinonaktifkan, tidak
dihapus.

**Jejak audit masuk dalam transaksi database yang sama** dengan perubahan yang
dicatatnya. Kalau perubahannya dibatalkan, baris auditnya ikut dibatalkan. Tidak ada
fungsi penghapusan di `audit_repo` — jejak audit yang bisa dihapus dari dalam
aplikasi tidak berguna sebagai jejak audit. Tabel `audit_logs` sengaja **tanpa
foreign key**, agar jejaknya bertahan lebih lama dari baris yang dirujuknya.

---

## 6. Konfirmasi dan proteksi duplikat

**Transaksi hasil AI tidak pernah langsung tersimpan.** Setiap hasil parsing masuk
ke tabel `pending_transactions`, dan penyimpanan hanya terjadi setelah pengguna
menekan Simpan.

Pending disimpan di **PostgreSQL, bukan FSM memori**. Kalau proses bot restart saat
seseorang menunggu konfirmasi, tombolnya tetap bekerja.

**Proteksi klik ganda bersifat atomik di tingkat database:**

```sql
UPDATE pending_transactions SET status = 'confirmed'
 WHERE id = :id AND telegram_user_id = :uid
   AND status = 'waiting' AND expires_at > now()
RETURNING id;
```

Pemeriksaan dan perubahan status terjadi dalam satu pernyataan, bukan "cek dulu lalu
tulis". Dua klik bersamaan tidak mungkin keduanya menang. Diuji di
`tests/test_pending.py`: dua kali Simpan menghasilkan **satu** transaksi.

**Deteksi duplikat** memperingatkan ketika (jenis, jumlah, kategori, tanggal,
pencatat) sama dalam 5 menit terakhir. Ini perlindungan terhadap kesalahan manusia,
bukan pengganti proteksi klik ganda. Dua anggota berbeda yang membayar hal sama
tidak dianggap duplikat.

**Pengguna tidak pernah diberi tahu "tersimpan" sebelum `COMMIT` berhasil.** Pesan
galat pun secara eksplisit menyatakan data **TIDAK** tersimpan — diuji di
`tests/test_middleware.py`.

---

## 7. Penanganan secret

- Tidak ada secret di dalam kode. Seluruh sapuan `grep` atas `app/` dan
  `migrations/` tidak menemukan nilai ter-hardcode.
- `.env` diabaikan Git (`.env`, `.env.*`, kecuali `.env.example`).
  `.env.example` hanya memuat placeholder.
- Di produksi memakai tab Variables di panel Lunafy, yang menyimpan nilainya
  terpisah dari kode.
- `app/utils/sanitizer.py` menyamarkan token bot Telegram, kunci API berawalan
  `sk-`/`AIza`/`ghp_`, kredensial di URL database, dan deret panjang generik.
  Setiap *exception* dan setiap potongan respons API dilewatkan ke sini sebelum
  dicatat.
- Panjang topeng dibatasi, sehingga panjang secret aslinya tidak ikut bocor.
- `echo=False` pada engine SQLAlchemy — `echo=True` akan mencetak seluruh SQL
  beserta parameternya, artinya semua data keuangan masuk ke log.
- Log `httpx` diturunkan ke WARNING: pada beberapa provider, URL permintaan memuat
  kunci API. Gemini dipanggil dengan kunci di **header**, bukan query string,
  justru karena URL mudah ikut tercatat.
- Kunci API tidak pernah diminta lewat pesan Telegram.

---

## 8. Masukan dan query

- Seluruh query lewat SQLAlchemy ORM atau `text()` dengan parameter bernama.
  Tidak ada SQL yang dibangun dari f-string — diperiksa dengan sapuan `grep`.
- Teks pengguna dilewatkan `bersihkan_teks`: escape HTML (karena pesan dikirim
  dengan `parse_mode=HTML`, sehingga `<b>` dari pengguna bisa merusak format),
  pembuangan karakter kontrol, dan pemotongan panjang.
- Jumlah divalidasi: harus > 0, ≤ batas, dan `CHECK` constraint di database
  menegakkannya lagi di lapisan penyimpanan.
- Tanggal di masa depan ditolak untuk catatan keuangan.
- Kategori dari `callback_data` diverifikasi harus sejenis dengan transaksinya —
  `callback_data` tidak dipercaya.
- Tidak ada `eval`, `exec`, `os.system`, `shell=True`, atau `pickle` di seluruh
  basis kode.
- Pembatas laju 20 permintaan/menit per pengguna, berbasis memori. Tujuannya bukan
  menahan serangan (middleware auth sudah menolak orang luar) melainkan mencegah
  satu anggota menghabiskan kuota AI gratis.

---

## 9. Apa yang TIDAK dilindungi

Daftar ini jujur dan disengaja. Jangan menganggap sesuatu terlindungi hanya karena
tidak disebut di bagian sebelumnya.

| Tidak dilindungi | Penjelasan |
|---|---|
| **Admin yang berniat buruk** | Admin bisa menghapus transaksi dan mengubah saldo awal. Yang ada hanyalah jejak audit, bukan pencegahan. Pilih admin dengan sadar. |
| **Perangkat Telegram yang disusupi** | Siapa pun yang memegang Telegram anggota adalah anggota itu, sejauh yang bisa diketahui bot. Tidak ada PIN kedua. |
| **Riwayat chat Telegram** | Saldo dan transaksi tampil sebagai pesan biasa dan tersimpan di server Telegram. Bot tidak bisa menghapusnya dari sana. |
| **Isi database bagi siapa pun yang punya `DATABASE_URL`** | Tidak ada enkripsi di tingkat kolom. Siapa pun dengan URL itu bisa membaca semuanya. |
| **File Excel setelah terkirim** | Setelah diunduh, filenya tidak terlindungi dan tidak diberi sandi. |
| **Artifact backup bagi siapa pun yang bisa mengakses repositori** | Dienkripsi AES256, jadi butuh `BACKUP_PASSPHRASE` untuk membukanya. Jaga passphrase itu di pengelola sandi, bukan di repositori. |
| **Sisi provider AI** | OpenRouter dan Google menerima teks transaksi. Mereka boleh menyimpannya sesuai kebijakan masing-masing. Yang bisa kita kendalikan hanya *apa* yang dikirim (bagian 3), bukan apa yang terjadi setelahnya. |
| **Pembatas laju saat restart** | Hitungannya di memori dan ter-reset. Untuk 2–3 pengguna yang saling mengenal, itu dapat diterima. |
| **Kehilangan data karena kelalaian berurutan** | Sebagian besar sudah ditutup: backup mingguan berjalan di GitHub Actions, di luar Lunafy, dan sentuhannya menjaga Supabase tidak dijeda walau bot mati. Yang tersisa: artifact GitHub hanya bertahan 90 hari, jadi unduh satu dump beberapa bulan sekali dan simpan sendiri. |
| **Perilaku restart otomatis Lunafy** | Tidak dinyatakan di dokumentasinya dan **belum diverifikasi**. Harus diuji sendiri. |
| **Database read-only tanpa peringatan dini** | Supabase paket Free menjadi read-only di atas 500 MB. Bot memperingatkan di 70% dan 90%, tapi peringatan itu hanya muncul saat seseorang menjalankan `/saldo` atau `/excel`. |

---

## 10. Daftar periksa keamanan rutin

Bulanan:

```bash
# Percobaan akses tak sah
# Konsol Lunafy, cari baris berisi "ditolak"
```

```sql
-- Jejak audit: siapa menghapus apa
SELECT created_at, telegram_id, action, transaction_id, details
  FROM audit_logs
 WHERE action IN ('transaction_delete', 'member_add', 'member_update',
                  'settings_update', 'unauthorized_access')
 ORDER BY id DESC LIMIT 50;
```

```sql
-- Anggota aktif: pastikan masih sesuai
SELECT telegram_id, full_name, role, is_active FROM users ORDER BY role;
```

Bila token bot pernah bocor: `/revoke` di @BotFather, lalu
perbarui `TELEGRAM_BOT_TOKEN` di tab Variables panel Lunafy, lalu restart.

Bila kunci OpenRouter atau Gemini bocor: hapus di dasbor masing-masing, buat baru,
perbarui lewat tab Variables. Tidak perlu mengubah kode.

---

## 11. Apa yang sudah diuji

| Jaminan | Test |
|---|---|
| Orang luar tidak mencapai handler | `test_middleware.py::test_pengguna_tak_terdaftar_ditolak` |
| Percobaan tak sah tercatat | `test_middleware.py::test_percobaan_tak_sah_tercatat_di_audit` |
| Anggota nonaktif ditolak | `test_middleware.py`, `test_members.py` |
| Member tidak bisa menghapus | `test_transactions.py::test_member_tidak_bisa_menghapus` |
| Member tidak bisa mengedit milik orang lain | `test_transactions.py`, `test_edit.py` |
| Daftar /edit member hanya memuat miliknya | `test_edit.py::test_member_hanya_melihat_miliknya` |
| Perubahan tersimpan mencatat nilai sebelum & sesudah | `test_edit.py::TestJejakAudit` |
| Perubahan yang ditolak tidak menulis audit | `test_edit.py::test_perubahan_yang_ditolak_tidak_menulis_audit` |
| Admin terakhir tidak bisa diturunkan | `test_members.py` |
| Klik ganda = satu transaksi | `test_pending.py::test_klik_ganda_hanya_menghasilkan_satu_transaksi` |
| Pending orang lain tidak bisa diklaim | `test_pending.py` |
| Model berbayar ditolak (2 lapis) | `test_config.py::TestPenjagaanZeroCost` |
| Pesan ber-PIN tidak pernah dikirim | `test_ai_router.py::test_pesan_berisi_pin_tidak_pernah_dikirim` |
| Secret tidak bocor ke pengguna | `test_middleware.py::test_detail_internal_tidak_dibocorkan_ke_pengguna` |
| Secret tidak bocor ke log | `test_scrub.py::TestSanitizerLog` |
| Soft delete menjaga catatan | `test_transactions.py::test_admin_hapus_adalah_soft_delete` |
| Uang tetap Decimal | `test_money.py`, `test_transactions.py` |
| Parameter libpq yang merusak asyncpg dibuang | `test_config.py::TestParameterLibpqYangTidakDikenalAsyncpg` |
| Transaction pooler dikenali lintas provider | `test_config.py::TestDeteksiPoolerAntarProvider` |
| Backup benar-benar bisa dipulihkan | `.github/workflows/backup.yml` — restore ke PostgreSQL kosong + bandingkan saldo |

Seluruhnya: **298 test, lulus di SQLite dan PostgreSQL 16.15.**
