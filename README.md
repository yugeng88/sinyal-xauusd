# Sinyal XAUUSD & NASDAQ (v16)

Aplikasi web (Flask, jalan di Vercel) yang menampilkan sinyal BUY/SELL untuk XAUUSD dan NASDAQ,
radar berita ekonomi AS (CPI, NFP, FOMC, PCE), dan notifikasi lewat ntfy/Telegram.
Data harga bisa datang langsung dari MT5 lewat EA `SinyalMT5.mq5` (lihat `PANDUAN_MT5.txt`).

> Bukan saran investasi. Sinyal adalah kecenderungan dari data, bukan prediksi atau jaminan. Uji di akun demo dulu.

## Yang baru di v16: tab NEWS selalu memberi arah

**Masalah di v15.1:** tab NEWS menulis "TUNGGU" terus. Penyebabnya dua:
1. Riwayat harga dimuat bertahap karena kuota per menit penyedia data (misalnya "4 dari 6"), dan sinyal diblokir selama riwayat kurang dari 6 kejadian.
2. Meski riwayat sudah 6 kejadian, uji statistik lama (interval Wilson 95%) hanya lolos bila **semua 6 kejadian** bergerak ke arah yang sama. Hampir tidak pernah terjadi, jadi hasilnya selalu TUNGGU.

**Perbaikan:** sinyal kini berupa skor dari beberapa faktor. Arah selalu keluar bila ada data, dan **kekuatan bukti** ditampilkan jujur (sampel kecil = lemah).

| Saat | Faktor yang dipakai |
|---|---|
| Sebelum rilis | tren H1 (bobot 40%), kecenderungan riwayat reaksi (35%, ditahan bila sampel kecil), Forecast vs Previous (penyesuaian kecil) |
| 0 sampai 5 menit setelah rilis | tetap TUNGGU (spread lebar), tetapi menampilkan "arah awal" dari angka bila Actual diisi |
| Setelah 5 menit | reaksi harga (50%), kejutan angka Actual vs Forecast (40%), pola lanjutan riwayat (penyesuaian kecil) |

**Cara membaca angka berita** (dari video referensi dan praktik umum, ada juga di aplikasi pada kartu "Cara membaca"):
- Bandingkan **Actual dengan Forecast**, bukan dengan Previous.
- Actual di atas Forecast (inflasi, pekerjaan, atau suku bunga lebih tinggi) → dolar menguat → emas cenderung turun → **SELL**.
- Actual di bawah Forecast → dolar melemah → emas cenderung naik → **BUY**.
- Sama persis → ikuti reaksi harga. Bila angka dan harga bertentangan, **harga diutamakan**.
- Besar kejutan memakai satuan praktis di `news.py` (`SURPRISE_CFG`): CPI/PCE 0,1 poin persen, NFP 50 ribu, suku bunga 0,25. Ubah sesuai pengalamanmu.

**Sumber angka:** Forecast dan Previous dibaca otomatis dari feed kalender Forex Factory
(`https://nfs.faireconomy.media/ff_calendar_thisweek.json`, hanya memuat pekan berjalan). Feed gratis ini **tidak memuat Actual**,
jadi Actual diketik manual tepat setelah rilis di kartu "Angka berita". Bila feed gagal terbaca, isi semuanya manual. Aplikasi tetap jalan.

## Struktur file

| File | Fungsi |
|---|---|
| `app.py` | server Flask, rute API, cron notifikasi |
| `news.py` | jadwal berita, studi reaksi harga, pembaca angka berita, sinyal news |
| `signals.py` | sinyal teknikal XAUUSD/NASDAQ |
| `data.py` | pengambilan harga (MT5/OANDA/Twelve Data/Yahoo) |
| `notify.py` | notifikasi ntfy/Telegram |
| `index.html` | tampilan dasbor (sumber) |
| `page.py` | **dibuat otomatis dari `index.html`** (`python build_page.py`), wajib ikut di-upload |
| `build_page.py` | pembuat `page.py` |
| `SinyalMT5.mq5` | EA MT5 pengirim harga broker |
| `tests/` | uji otomatis (data uji sintetis) |

## Deploy di Vercel

1. Upload semua file ke repositori GitHub (lihat bawah), Vercel otomatis membangun ulang.
2. Variabel lingkungan yang sudah ada tetap dipakai. Yang baru dan **opsional**:
   - `NEWS_FEED=off` untuk mematikan pembacaan kalender Forex Factory (angka diisi manual saja).
   - `NEWS_FEED_URL` untuk mengganti alamat feed.
   - Lainnya seperti sebelumnya: `TWELVEDATA_API_KEY`, `CRON_SECRET`, `NTFY_TOPIC`, `NEWS_CALLS_PER_MIN`, `NEWS_PRE_MIN`, `EXTRA_EVENTS`, dst.
3. Tunggu status **Ready**. Di bawah dasbor tertulis "Versi 16".

## Upload ke GitHub dari iPhone (tanpa PC)

1. Buka zip di aplikasi **Files** (ketuk file zip, otomatis terekstrak jadi folder).
2. Buka repositori `sinyal-xauusd` di Safari (github.com) → **Add file** → **Upload files**.
3. Pilih file dari folder hasil ekstrak. Untuk pembaruan v16 cukup **news.py, app.py, notify.py, index.html, page.py** (tambahan baru: `README.md`, `build_page.py`, `.gitignore`, folder `tests` bila mau).
4. Tulis pesan commit, tekan **Commit changes**. Vercel membangun ulang otomatis.

## Menjalankan uji

```
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Uji memakai **harga dan riwayat sintetis buatan** untuk memeriksa logika kode. Itu bukan data pasar nyata dan bukan hasil backtest strategi.

## Batasan yang perlu diketahui

- Riwayat reaksi per jenis berita hanya 4 sampai 8 kejadian (jadwal resmi 2025 akhir sampai 2026). Sampel sekecil itu membuat bukti statistik lemah, dan aplikasi menampilkannya apa adanya.
- Aturan "Actual di atas Forecast = emas turun" adalah kecenderungan umum, bukan hukum. Pasar bisa bereaksi pada angka inti, revisi, atau nada pidato.
- Feed Forex Factory adalah feed publik tidak resmi. Bisa berubah atau dibatasi sewaktu-waktu.
