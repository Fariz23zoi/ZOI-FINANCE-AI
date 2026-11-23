#!/usr/bin/env bash
#
# Backup manual buku kas ZOI FINANCE AI.
#
# Backup utama berjalan otomatis di GitHub Actions setiap minggu
# (.github/workflows/backup.yml). Skrip ini untuk backup sewaktu-waktu:
# sebelum perubahan besar, sebelum mengubah saldo awal, atau kapan pun Anda
# ingin salinan di tangan sendiri.
#
# Bisa dijalankan dari Termux. Butuh pg_dump (pkg install postgresql).
#
# Pakai:
#   DATABASE_URL="postgresql://..." ./scripts/backup.sh
#   DATABASE_URL="postgresql://..." ./scripts/backup.sh ~/storage/shared/Download
#
set -euo pipefail

TUJUAN="${1:-.}"

if [ -z "${DATABASE_URL:-}" ]; then
  echo "DATABASE_URL belum diatur." >&2
  echo >&2
  echo "Ambil dari dashboard Supabase: Connect -> Session pooler, lalu:" >&2
  echo "  DATABASE_URL=\"postgresql://...\" $0" >&2
  exit 1
fi

if ! command -v pg_dump >/dev/null 2>&1; then
  echo "pg_dump tidak ditemukan. Di Termux: pkg install postgresql" >&2
  exit 1
fi

mkdir -p "$TUJUAN"
STEMPEL=$(date +%Y-%m-%d-%H%M)
BERKAS="$TUJUAN/zoi-$STEMPEL.dump"

echo "Membaca jumlah baris..."
# Dibaca lebih dulu supaya ada angka untuk dibandingkan dengan isi dump.
psql "$DATABASE_URL" -At -F' = ' <<'SQL'
SELECT 'transaksi aktif', count(*) FROM transactions WHERE status='active'
UNION ALL SELECT 'transaksi terhapus', count(*) FROM transactions WHERE status='deleted'
UNION ALL SELECT 'anggota', count(*) FROM users
UNION ALL SELECT 'entri audit', count(*) FROM audit_logs;
SQL

SALDO=$(psql "$DATABASE_URL" -At -c "
  SELECT (SELECT initial_balance FROM account_settings WHERE id=1)
       + COALESCE(SUM(amount) FILTER (WHERE transaction_type='income'),0)
       - COALESCE(SUM(amount) FILTER (WHERE transaction_type='expense'),0)
  FROM transactions WHERE status='active';")

if [ -z "$SALDO" ]; then
  echo "Gagal membaca saldo — backup dibatalkan." >&2
  exit 1
fi
echo "saldo = $SALDO"

echo "Membuat dump..."
pg_dump "$DATABASE_URL" \
  --format=custom --schema=public --no-owner --no-privileges \
  --file="$BERKAS"

echo "Memeriksa isi dump..."
# Dump yang tidak diperiksa bukan backup. Minimal pastikan ketujuh tabel ada.
HILANG=""
for T in users categories transactions account_settings pending_transactions audit_logs alembic_version; do
  pg_restore --list "$BERKAS" | grep -q "TABLE public $T" || HILANG="$HILANG $T"
done
if [ -n "$HILANG" ]; then
  echo "Tabel berikut tidak ada di dalam dump:$HILANG" >&2
  echo "Backup TIDAK bisa diandalkan. Jangan hapus apa pun." >&2
  exit 1
fi

echo
echo "Selesai: $BERKAS ($(du -h "$BERKAS" | cut -f1))"
echo "Saldo saat backup: $SALDO"
echo
echo "Simpan file ini di luar Lunafy dan di luar Supabase."
echo "Memulihkan:"
echo "  pg_restore -d \"\$DATABASE_URL\" --clean --if-exists --exit-on-error \"$BERKAS\""
