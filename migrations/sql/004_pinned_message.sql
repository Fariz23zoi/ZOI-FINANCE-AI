-- ZOI FINANCE AI — migrasi 004: nomor pesan papan saldo tersemat
--
-- Jalankan di Supabase → SQL Editor, SEBELUM menjalankan ulang bot.
-- Bot versi baru membaca kolom ini saat start; tanpa kolomnya, setiap
-- pembacaan anggota gagal dan bot menolak semua orang.
--
-- Aman dijalankan berulang: IF NOT EXISTS membuat perintah keduanya
-- tidak melakukan apa-apa, bukan menimbulkan error.

ALTER TABLE users ADD COLUMN IF NOT EXISTS pinned_message_id BIGINT;

UPDATE alembic_version SET version_num = '004' WHERE version_num = '003';

-- Pemeriksaan: harus mengembalikan satu baris berisi 004 dan t.
SELECT
    (SELECT version_num FROM alembic_version) AS versi,
    EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'pinned_message_id'
    ) AS kolom_ada;
