-- ZOI FINANCE AI — skema awal untuk Supabase PostgreSQL
--
-- Dihasilkan dari migrasi Alembic 001, 002 dan 003 dengan:
--     alembic upgrade head --sql
--
-- CARA PAKAI (jalur termudah dari HP):
--   1. Ganti __ADMIN_TELEGRAM_ID__ di bagian bawah file dengan Telegram ID
--      numerik Anda, tanpa tanda kutip dan tanpa @. Contoh: 123456789
--      Cari ID-nya dengan mengirim pesan ke @userinfobot di Telegram.
--   2. Buka dashboard Supabase → SQL Editor → New query.
--   3. Tempel seluruh isi file ini, lalu Run.
--
-- Isinya:
--   • 001 — 4 tipe enum, 6 tabel, seluruh indeks dan CHECK constraint
--   • 002 — 19 kategori bahasa Indonesia + baris account_settings tunggal
--   • 003 — administrator pertama
--   • tabel alembic_version diisi '003', sehingga migrasi berikutnya cukup
--     dijalankan dengan `alembic upgrade head` tanpa mengulangi yang ini
--
-- Dipakai pada database kosong. Setiap INSERT memakai ON CONFLICT, tetapi
-- CREATE TABLE tidak — jadi menjalankannya ulang pada database yang sudah
-- berisi skema ini akan menghasilkan error "already exists". Untuk
-- memperbarui database yang sudah ada, pakai `alembic upgrade head`.
--
-- Diverifikasi dengan menjalankan file ini pada PostgreSQL 16.15 kosong:
-- 7 tabel, 4 tipe enum, 22 indeks, 3 CHECK constraint, 19 kategori,
-- 1 baris pengaturan, 1 administrator, alembic_version = 003.

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 001

CREATE TABLE account_settings (
    id SERIAL NOT NULL, 
    initial_balance NUMERIC(18, 2) DEFAULT '0' NOT NULL, 
    currency VARCHAR(3) DEFAULT 'IDR' NOT NULL, 
    timezone VARCHAR(64) DEFAULT 'Asia/Jakarta' NOT NULL, 
    member_can_export BOOLEAN DEFAULT 'true' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_account_settings_singleton CHECK (id = 1)
);

CREATE TABLE audit_logs (
    id BIGSERIAL NOT NULL, 
    user_id INTEGER, 
    telegram_id BIGINT, 
    action VARCHAR(50) NOT NULL, 
    transaction_id BIGINT, 
    details JSONB, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
    PRIMARY KEY (id)
);

CREATE INDEX ix_audit_action ON audit_logs (action);

CREATE INDEX ix_audit_created_at ON audit_logs (created_at);

CREATE INDEX ix_audit_transaction ON audit_logs (transaction_id);

CREATE TYPE transaction_type AS ENUM ('income', 'expense');

CREATE TABLE categories (
    id SERIAL NOT NULL, 
    name VARCHAR(100) NOT NULL, 
    transaction_type transaction_type NOT NULL, 
    is_active BOOLEAN DEFAULT 'true' NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT uq_category_name_type UNIQUE (name, transaction_type)
);

CREATE INDEX ix_categories_type_active ON categories (transaction_type, is_active);

CREATE TYPE user_role AS ENUM ('admin', 'member');

CREATE TABLE users (
    id SERIAL NOT NULL, 
    telegram_id BIGINT NOT NULL, 
    full_name VARCHAR(255) NOT NULL, 
    username VARCHAR(255), 
    role user_role NOT NULL, 
    is_active BOOLEAN DEFAULT 'true' NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
    PRIMARY KEY (id)
);

CREATE INDEX ix_users_is_active ON users (is_active);

CREATE UNIQUE INDEX ix_users_telegram_id ON users (telegram_id);

CREATE TYPE transaction_status AS ENUM ('active', 'deleted');

CREATE TABLE transactions (
    id BIGSERIAL NOT NULL, 
    transaction_type transaction_type NOT NULL, 
    amount NUMERIC(18, 2) NOT NULL, 
    category_id INTEGER NOT NULL, 
    description TEXT, 
    location VARCHAR(255), 
    transaction_date DATE NOT NULL, 
    created_by INTEGER NOT NULL, 
    updated_by INTEGER, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
    status transaction_status DEFAULT 'active' NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT ck_transactions_amount_max CHECK (amount <= 999999999999.99), 
    CONSTRAINT ck_transactions_amount_positive CHECK (amount > 0), 
    FOREIGN KEY(category_id) REFERENCES categories (id) ON DELETE RESTRICT, 
    FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE RESTRICT, 
    FOREIGN KEY(updated_by) REFERENCES users (id) ON DELETE RESTRICT
);

CREATE INDEX ix_transactions_created_by ON transactions (created_by);

CREATE INDEX ix_transactions_date ON transactions (transaction_date);

CREATE INDEX ix_transactions_date_status ON transactions (transaction_date, status);

CREATE INDEX ix_transactions_dup_check ON transactions (created_by, created_at);

CREATE INDEX ix_transactions_status ON transactions (status);

CREATE INDEX ix_transactions_type_status ON transactions (transaction_type, status);

CREATE TYPE pending_status AS ENUM ('waiting', 'confirmed', 'cancelled', 'expired');

CREATE TABLE pending_transactions (
    id BIGSERIAL NOT NULL, 
    telegram_user_id BIGINT NOT NULL, 
    parsed_data JSONB NOT NULL, 
    source_text TEXT NOT NULL, 
    status pending_status DEFAULT 'waiting' NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    transaction_id BIGINT, 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(transaction_id) REFERENCES transactions (id) ON DELETE SET NULL
);

CREATE INDEX ix_pending_status_expires ON pending_transactions (status, expires_at);

CREATE INDEX ix_pending_user_status ON pending_transactions (telegram_user_id, status);

INSERT INTO alembic_version (version_num) VALUES ('001') RETURNING alembic_version.version_num;

-- Running upgrade 001 -> 002

INSERT INTO categories (name, transaction_type, is_active) VALUES ('Makanan & Minuman', 'expense', true) ON CONFLICT (name, transaction_type) DO NOTHING;

INSERT INTO categories (name, transaction_type, is_active) VALUES ('Transportasi', 'expense', true) ON CONFLICT (name, transaction_type) DO NOTHING;

INSERT INTO categories (name, transaction_type, is_active) VALUES ('Belanja Harian', 'expense', true) ON CONFLICT (name, transaction_type) DO NOTHING;

INSERT INTO categories (name, transaction_type, is_active) VALUES ('Tagihan & Utilitas', 'expense', true) ON CONFLICT (name, transaction_type) DO NOTHING;

INSERT INTO categories (name, transaction_type, is_active) VALUES ('Kesehatan', 'expense', true) ON CONFLICT (name, transaction_type) DO NOTHING;

INSERT INTO categories (name, transaction_type, is_active) VALUES ('Pendidikan', 'expense', true) ON CONFLICT (name, transaction_type) DO NOTHING;

INSERT INTO categories (name, transaction_type, is_active) VALUES ('Rumah Tangga', 'expense', true) ON CONFLICT (name, transaction_type) DO NOTHING;

INSERT INTO categories (name, transaction_type, is_active) VALUES ('Komunikasi & Pulsa', 'expense', true) ON CONFLICT (name, transaction_type) DO NOTHING;

INSERT INTO categories (name, transaction_type, is_active) VALUES ('Hiburan', 'expense', true) ON CONFLICT (name, transaction_type) DO NOTHING;

INSERT INTO categories (name, transaction_type, is_active) VALUES ('Sosial & Keluarga', 'expense', true) ON CONFLICT (name, transaction_type) DO NOTHING;

INSERT INTO categories (name, transaction_type, is_active) VALUES ('Pekerjaan', 'expense', true) ON CONFLICT (name, transaction_type) DO NOTHING;

INSERT INTO categories (name, transaction_type, is_active) VALUES ('Lain-lain', 'expense', true) ON CONFLICT (name, transaction_type) DO NOTHING;

INSERT INTO categories (name, transaction_type, is_active) VALUES ('Gaji', 'income', true) ON CONFLICT (name, transaction_type) DO NOTHING;

INSERT INTO categories (name, transaction_type, is_active) VALUES ('Usaha', 'income', true) ON CONFLICT (name, transaction_type) DO NOTHING;

INSERT INTO categories (name, transaction_type, is_active) VALUES ('Penjualan', 'income', true) ON CONFLICT (name, transaction_type) DO NOTHING;

INSERT INTO categories (name, transaction_type, is_active) VALUES ('Bonus', 'income', true) ON CONFLICT (name, transaction_type) DO NOTHING;

INSERT INTO categories (name, transaction_type, is_active) VALUES ('Hadiah', 'income', true) ON CONFLICT (name, transaction_type) DO NOTHING;

INSERT INTO categories (name, transaction_type, is_active) VALUES ('Pinjaman Masuk', 'income', true) ON CONFLICT (name, transaction_type) DO NOTHING;

INSERT INTO categories (name, transaction_type, is_active) VALUES ('Lain-lain', 'income', true) ON CONFLICT (name, transaction_type) DO NOTHING;

INSERT INTO account_settings (id, initial_balance, currency, timezone, member_can_export) VALUES (1, 0, 'IDR', 'Asia/Jakarta', true) ON CONFLICT (id) DO NOTHING;

UPDATE alembic_version SET version_num='002' WHERE alembic_version.version_num = '001';

-- Running upgrade 002 -> 003

INSERT INTO users (telegram_id, full_name, role, is_active) VALUES (__ADMIN_TELEGRAM_ID__, 'Administrator', 'admin', true) ON CONFLICT (telegram_id) DO UPDATE SET role = 'admin', is_active = true;

UPDATE alembic_version SET version_num='003' WHERE alembic_version.version_num = '002';
