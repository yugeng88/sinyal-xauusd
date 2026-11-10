# Sinyal XAUUSD & NASDAQ (v18, dual-instrument)

Aplikasi web (Flask, jalan di Vercel) yang menampilkan sinyal BUY/SELL untuk XAUUSD dan NASDAQ,
radar berita ekonomi AS (CPI, NFP, FOMC, PCE), dan notifikasi lewat ntfy/Telegram.
Data harga bisa datang langsung dari MT5 lewat EA `SinyalMT5.mq5` (lihat `PANDUAN_MT5.txt`).

> Bukan saran investasi. Sinyal adalah kecenderungan dari data, bukan prediksi atau jaminan. Uji di akun demo dulu.


## Yang baru di v18: dua instrumen, konfirmasi M1 wajib, anti entry terlambat

Tampilan dasbor, tab NEWS, alur data, notifikasi KELUAR/MELEMAH, dan EA MT5 tetap sama dengan v17. Yang berubah:

| Fitur | v17 | v18 |
|---|---|---|
| Consensus 3 strategi | XAUUSD saja (patch: NASDAQ) | XAUUSD **dan** NASDAQ |
| Konfirmasi M1 | tampil sebagai info, notifikasi "sinyal baru" terkirim sebelum M1 | **wajib**: notifikasi entry hanya setelah M1 `ENTRY SIAP`; dasbor menulis jelas kapan jangan entry |
| Entry terlambat | hanya cek zona di M1 | status `TERLAMBAT` bila harga sudah mengejar lebih dari `ZONE_R` x jarak SL, atau batas waktu `ENTRY_MAX_BARS` candle TF lewat; `SETUP BATAL` bila SL tersentuh |
| SL/TP | ATR x 1,5, RR tetap | **dinamis**: SL = ekstrem struktur 8 candle + buffer, dibatasi `SL_MIN_ATR`..`SL_MAX_ATR` x ATR; TP = RR instrumen x jarak SL nyata; saat `ENTRY SIAP`, Entry/TP dihitung ulang dari harga M1 sekarang dengan SL sinyal yang sama |
| Risiko | satu set angka | **profil terpisah** XAUUSD dan NASDAQ (env `NAMA_XAUUSD` / `NAMA_NASDAQ`), kartu "Manajemen risiko" + kalkulator lot di dasbor, endpoint `/api/risk` |

Status konfirmasi di dasbor: `ENTRY SIAP` (semua syarat M1 terpenuhi), `MENUNGGU KONFIRMASI M1`, `TERLAMBAT` (mengejar atau batas waktu), `SETUP BATAL` (SL tersentuh).

Default bawaan (semuanya bisa diubah lewat env, lihat `.env.example`):

| Pengaturan | XAUUSD | NASDAQ |
|---|---|---|
| SL cadangan (ATR x) | 1,5 | 1,8 |
| Batas SL dinamis (ATR x) | 1,0 sampai 2,5 | 1,2 sampai 3,0 |
| RR TP1/TP2/TP3 | 2 / 3 / 4 | 2 / 3 / 4 |
| Batas mengejar (x jarak SL) | 0,5 | 0,4 |
| Batas waktu entry | 2 candle TF | 2 candle TF |
| Risiko awal kalkulator lot | 1,0% | 0,5% |
| Nilai per 1,00 poin per 1 lot | 100 USD | 1 USD (cek broker Anda) |

**Penting:** angka di tabel adalah titik awal yang masuk akal, bukan hasil optimasi atau backtest. Perbedaan NASDAQ (SL lebih lebar, batas mengejar lebih ketat) adalah asumsi bahwa indeks lebih berisik dan sering gap. Amati di akun demo lalu sesuaikan. Nilai per poin per lot berbeda antar broker; selalu cek spesifikasi kontrak simbol Anda. Statistik "Riwayat sinyal" dihitung dari candle TF dan belum menyaring dengan konfirmasi M1 (data M1 historis tidak disimpan), jadi hasil nyata dengan gerbang M1 bisa berbeda.

Variabel baru: `REQUIRE_M1` (default 1; 0 mengembalikan notifikasi "sinyal baru" v17), `SETUP_ALERT` (1 = tetap kirim peringatan setup sebelum M1), `INTERNAL_CRON` (khusus VPS), serta pengaturan risiko per instrumen. Panduan VPS: `DEPLOY.md`. Uji v18: `python -m unittest tests.test_v18 -v`.

## Yang baru di v17: 3-strategy consensus untuk sinyal teknikal

Mesin sinyal teknikal XAUUSD di `signals.py` kini memakai tiga setup tambahan dan menerbitkan BUY/SELL hanya jika minimal dua strategi memberi arah yang sama:

1. **Liquidity Sweep Reversal** — candle menembus swing 12 candle sebelumnya lalu ditutup kembali di dalam range dengan rejection wick.
2. **Trend Pullback** — tren EMA20/EMA50, pullback di sekitar EMA20 (toleransi 0,35 ATR), candle konfirmasi, dan RSI di sisi 50.
3. **Momentum Breakout** — close menembus high/low 20 candle sebelumnya dengan body minimal 0,5 ATR.

Dashboard menampilkan hasil tiap strategi, jumlah suara, dan status konsensus. Sinyal historis yang dipakai fitur tracking juga menggunakan aturan konsensus baru. Strategi lama EMA/RSI/perubahan 24 jam tetap dihitung dan ditampilkan sebagai pembanding (`legacy_direction`), bukan dihapus. Mesin konsensus ini berlaku untuk XAUUSD dan NASDAQ (sejak v17.1/v18).

**Penting:** aturan ini adalah versi awal berbasis OHLC dan belum terbukti menghasilkan profit. Angka confidence 70/90 adalah skor jumlah strategi yang setuju, bukan probabilitas menang. Target drawdown di bawah 10% belum dapat diklaim tanpa backtest tick data, spread, komisi, slippage, dan validasi out-of-sample. Gunakan akun demo terlebih dahulu.

Uji mesin strategi: `python -m unittest tests.test_strategies -v`.

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
| `signals.py` | sinyal teknikal, profil risiko per instrumen, SL/TP dinamis, konfirmasi M1 + anti entry terlambat |
| `data.py` | pengambilan harga (MT5/OANDA/Twelve Data/Yahoo) |
| `notify.py` | notifikasi ntfy/Telegram |
| `index.html` | tampilan dasbor (sumber) |
| `page.py` | **dibuat otomatis dari `index.html`** (`python build_page.py`), wajib ikut di-upload |
| `build_page.py` | pembuat `page.py` |
| `wsgi.py`, `requirements-vps.txt`, `deploy/`, `DEPLOY.md` | deploy VPS (gunicorn, systemd, nginx) |
| `.env.example` | daftar semua variabel lingkungan |
| `SinyalMT5.mq5` | EA MT5 pengirim harga broker |
| `tests/` | uji otomatis (data uji sintetis) |

## Deploy di Vercel

1. Upload semua file ke repositori GitHub (lihat bawah), Vercel otomatis membangun ulang.
2. Variabel lingkungan yang sudah ada tetap dipakai. Yang baru dan **opsional**:
   - `NEWS_FEED=off` untuk mematikan pembacaan kalender Forex Factory (angka diisi manual saja).
   - `NEWS_FEED_URL` untuk mengganti alamat feed.
   - Lainnya seperti sebelumnya: `TWELVEDATA_API_KEY`, `CRON_SECRET`, `NTFY_TOPIC`, `NEWS_CALLS_PER_MIN`, `NEWS_PRE_MIN`, `EXTRA_EVENTS`, dst.
3. Tunggu status **Ready**. Di bawah dasbor tertulis "Versi 18". Cek juga `/healthz` (harus memuat `"version": "18"`).

## Upload ke GitHub dari iPhone (tanpa PC)

1. Buka zip di aplikasi **Files** (ketuk file zip, otomatis terekstrak jadi folder).
2. Buka repositori `sinyal-xauusd` di Safari (github.com) → **Add file** → **Upload files**.
3. Pilih file dari folder hasil ekstrak. Untuk pembaruan dari v17 ke v18 upload: **signals.py, app.py, notify.py, index.html, page.py, README.md, tests/test_strategies.py, tests/test_v18.py**. Paket ini lengkap, jadi menimpa semua file juga aman. File untuk VPS (`wsgi.py`, `deploy/`, dst.) tidak dipakai Vercel dan boleh dilewati.
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
