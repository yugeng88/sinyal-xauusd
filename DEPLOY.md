# Deploy v19.0

## A. Vercel + GitHub (seperti sebelumnya)

1. Upload semua file zip ini ke repositori GitHub (timpa file lama). Vercel membangun ulang otomatis.
2. Variabel lingkungan lama tetap berlaku. Tidak ada yang wajib baru. Opsional: lihat `.env.example`.
3. Pastikan penjadwal luar (cron-job.org atau sejenisnya) memanggil `https://DOMAIN/api/cron?key=CRON_SECRET` **tiap menit**.
   Dengan v19.0 ini penting: notifikasi entry baru hanya dikirim setelah M1 terkonfirmasi, dan itu dicek oleh putaran cron
   (atau oleh EA MT5 bila dipakai).
4. Buka `https://DOMAIN/healthz`: harus menampilkan versi `19.0`. Buka `https://DOMAIN/api/risk` untuk melihat profil aktif.

## B. VPS (Ubuntu/Debian)

```bash
sudo useradd -r -m sinyal
sudo mkdir -p /opt/sinyal && sudo chown sinyal: /opt/sinyal
# salin isi zip ke /opt/sinyal (git clone atau scp), lalu:
cd /opt/sinyal
sudo -u sinyal python3 -m venv venv
sudo -u sinyal venv/bin/pip install -r requirements-vps.txt
sudo -u sinyal cp .env.example .env && sudo -u sinyal nano .env      # isi CRON_SECRET, NTFY_TOPIC, dst.
sudo cp deploy/sinyal.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now sinyal
curl http://127.0.0.1:8000/healthz
```

- `deploy/sinyal.service` sudah menyetel `INTERNAL_CRON=1`: aplikasi memeriksa notifikasi sendiri tiap menit, tanpa crontab.
  Jangan menjalankan cron luar bersamaan dengan `INTERNAL_CRON=1`.
- Gunakan **1 worker** gunicorn (cache, thread latar, dan penanda notifikasi disimpan di memori proses).
  Tanpa Redis, penanda "sudah dikirim" hilang saat restart, jadi satu notifikasi bisa terkirim ulang. Isi
  `UPSTASH_REDIS_REST_URL` dan `UPSTASH_REDIS_REST_TOKEN` (Upstash Redis, ada paket gratis) bila ingin penanda bertahan.
- HTTPS: `sudo cp deploy/nginx.conf /etc/nginx/sites-available/sinyal`, ganti `server_name`, aktifkan situsnya, lalu
  `sudo certbot --nginx`.
- MT5 di VPS: ikuti `PANDUAN_MT5.txt`; isi URL EA dengan domain VPS dan Kunci dengan `CRON_SECRET`.

## Pemeriksaan sesudah deploy

1. Tab XAUUSD dan NASDAQ sama-sama menampilkan "V19 Advanced Strategy Engine · x/3 keluarga" dan kartu "Manajemen risiko".
2. Saat ada sinyal aktif, kotak konfirmasi berstatus `MENUNGGU…`, `ENTRY SIAP`, atau `TERLAMBAT…`.
3. `https://DOMAIN/api/cron?key=CRON_SECRET&test=1` mengirim notifikasi tes ke ntfy/Telegram.
4. Jalankan akun demo dulu dan catat: berapa sinyal yang berakhir `TERLAMBAT`, dan apakah entry `ENTRY SIAP` benar-benar mendekati level.

Bukan saran investasi. Belum ada backtest tick data, spread, komisi, dan slippage.
