# Sinyal XAUUSD & NASDAQ (v19.24 NEWS + FIB + SPREAD, dual-instrument)

Aplikasi web (Flask, jalan di Vercel) yang menampilkan sinyal BUY/SELL untuk XAUUSD dan NASDAQ,
radar berita ekonomi AS (CPI, PPI, NFP, FOMC, PCE), dan notifikasi lewat ntfy/Telegram.
Data harga bisa datang langsung dari MT5 lewat EA `SinyalMT5.mq5` (lihat `PANDUAN_MT5.txt`).

> Bukan saran investasi. Sinyal adalah kecenderungan dari data, bukan prediksi atau jaminan. Uji di akun demo dulu.


## Yang baru di v19.24: spread broker dibaca otomatis dari MT5

- EA versi baru **`SinyalMT5-spread.mq5`** mengirim selisih ask-bid tiap simbol. `SinyalMT5.mq5` yang lama **tidak diubah** dan tetap berfungsi; tanpa EA baru, spread tetap bisa diketik manual di kolom "Spread broker".
- Aplikasi memakai spread dari MT5 bila kolom manual kosong (tertulis "dibaca dari MT5"); ketikan manual selalu menang.
- Panel Manajemen risiko kini memasukkan spread ke jarak risiko (rugi bila SL = jarak SL + spread), sehingga lot yang disarankan sedikit lebih kecil.
- Peringatan sudah ada: bila spread lebih dari 20% jarak SL, kartu menyarankan tidak masuk.
- Cara pasang: salin `SinyalMT5-spread.mq5` ke MQL5/Experts, kompilasi (F7), ganti EA yang lama di chart dengan yang baru (input sama). **File EA ini belum dikompilasi di MetaEditor**; bila ada galat, laporkan apa adanya.
- Spread yang tampil adalah spread saat EA terakhir mengirim data. Saat berita besar spread bisa melebar tiba-tiba.

## Yang baru di v19.23: notifikasi setelah harga berbalik dari titik balik

- Rencana BUY/SELL LIMIT sekarang dikirim **setelah harga berbalik dari titik balik (0.03) dan menuju zona entry**: posisi harga di Fib sudah >= `FIB_NOTIFY_AFTER` (bawaan 0.3) dan candle tertutup terakhir bergerak ke arah zona. Sebelumnya dikirim begitu setup muncul.
- `FIB_NOTIFY_AFTER=0` mengembalikan perilaku lama (langsung saat setup muncul); naikkan (mis. 0.4) agar lebih lambat tapi lebih dekat ke zona. Notifikasi masuk zona dan BATAL tidak berubah.
- Bukan saran investasi; belum ada backtest.

## Sebelumnya di v19.22: kartu Fib hijau saat terbentuk + perbaikan Order Block

- **Latar hijau:** kartu Fib berwarna hijau saat setup aktif (MENUNGGU PULLBACK atau DI ZONA ENTRY); saat DI ZONA ENTRY borderan lebih tebal. Setup BATAL/SUDAH LEWAT tetap dilipat dan netral; LEWAT ENTRY tetap kuning.
- **Perbaikan OB:** candle yang hanya menyentuh tepi zona (irisan < 30% dari yang lebih kecil antara tinggi candle dan zona) tidak lagi dianggap OB, begitu juga candle lebih tinggi dari `FIB_OB_MAX_ATR` (2.0) x ATR (itu impuls, bukan OB). SL OB minimal `FIB_OB_MIN_RISK_ATR` (0.3) x ATR dari entry, tetapi tidak lebih lebar dari SL Fib 0.99. Sebelumnya bisa muncul SL 1.5 poin dengan RR 1:30+.
- Level Fib (zona 0.63-0.78, SL 0.99, TP -0.33/-0.66/-0.99) tidak berubah. Bukan saran investasi; belum ada backtest.

## Sebelumnya di v19.21: pelajaran dari tiga video Fibonacci

- **Struktur (BOS):** kaki Fib yang baik lahir dari break of structure. BUY valid bila high kaki = **HH** (menembus high sebelumnya); SELL valid bila low kaki = **LL**. Selain itu kartu menandai "struktur lemah". Hanya penanda, tidak memblokir order.
- **Divergensi RSI** sebagai konfirmasi tambahan (bukan syarat entry): hidden bullish (harga higher low, RSI lower low) atau regular bullish untuk BUY; kebalikannya untuk SELL. Dihitung dari dua swing terakhir, swing kedua harus sesudah ujung kaki. Matikan dengan `FIB_DIV=0`.
- **Tampilan:** setup Fib yang BATAL atau SUDAH LEWAT dilipat jadi satu baris (ketuk untuk detail) dan diurutkan di bawah setup yang masih aktif. Notifikasi memuat satu baris "Kualitas".
- Tidak berubah: zona entry 0.63-0.78, SL, dan TP -0.33 / -0.66 / -0.99 (sudah sejalan dengan video: tarik wick ke wick, SL di luar 1.0, TP dari ekstensi). Bukan saran investasi; belum ada backtest.

## Sebelumnya di v19.20: Order Block + BUY/SELL LIMIT siap pasang (Fib tanpa menunggu konfirmasi)

- **Order Block (OB) di dalam zona 0.63-0.78.** BUY = demand OB: candle turun terakhir sebelum harga naik menembus high-nya. SELL = supply OB: candle naik terakhir sebelum harga turun menembus low-nya. Syarat: menyentuh zona, ada displacement (close menembus ekstrem candle dalam 3 candle), belum ditutup menembus sisi jauhnya, dan bukan candle kecil (>= 0.15 ATR). Dipilih yang terbaru.
- **Rencana order limit:** entry di tepi OB (dijepit ke dalam zona), SL di luar OB + buffer `FIB_OB_BUFFER_ATR` (0.1 ATR), dipakai yang lebih dekat antara itu dan SL Fib 0.99. TP tetap -0.33 / -0.66 / -0.99. Bila tidak ada OB: entry di level 0.78 dan SL 0.99. Bila harga sudah di dalam OB, entry dipindah ke titik tengah OB; bila tetap tidak bisa, kartu memberi peringatan.
- **Notifikasi langsung:** rencana BUY/SELL LIMIT + SL + TP + OB dikirim begitu setup searah kaki terakhir muncul dan harga belum di zona (sekali per pasangan titik dan arah), lalu saat harga masuk zona, lalu kabar BATAL bila sebelumnya sudah diberitahukan. Matikan yang awal dengan `FIB_NOTIFY_EARLY=0`; matikan OB dengan `FIB_OB=0`. Gambar sebaliknya (alt) hanya diberitahukan saat masuk zona.
- Tidak ada konfirmasi M1 untuk Fib. Limit tidak terisi bila harga tidak kembali; limit terisi bisa langsung kena SL. Bukan saran investasi; belum ada backtest.

## Sebelumnya di v19.19: titik jangkar diberi label struktur (LL / LH / HL / HH)

- Kaki Fib kini ditampilkan seperti cara Anda menarik: **LL → LH** (BUY) atau **LH → LL** (SELL), di judul kartu, tabel per timeframe, dan notifikasi.
- Label dihitung dari pivot: high yang lebih rendah dari high sebelumnya = LH, low yang lebih rendah dari low sebelumnya = LL (dan sebaliknya HH/HL). Bila belum ada pembanding, tampil Low/High.
- Dua gambar dari pasangan titik yang sama tetap muncul (`fib` dan `fib.alt`). Bukan saran investasi; belum ada backtest.

## Sebelumnya di v19.18: Fib timeframe besar (M15-H4)

- Fib juga dihitung di **H4** (digabung dari candle H1/M30/M15, batas jam UTC, candle H4 yang belum lengkap dibuang). Pivot H4 lebih rapat (3 candle kiri/kanan) karena candle-nya besar.
- Kartu Fib punya lipatan **Fib tiap timeframe (M15-H4)**: arah, status, kaki (awal -> ujung), area entry, dan SL per timeframe, untuk dibandingkan dengan garis yang Anda tarik di TradingView.
- API `/api/signal` menambah `fib_tfs`; tiap sinyal M15/M30/H1 memuat `fib_h4`.
- Aplikasi tidak bisa membaca gambar di TradingView; kaki dipilih otomatis dari pivot terbaru. Bukan saran investasi; belum ada backtest.

## Sebelumnya di v19.17: peran level Fib dikoreksi

- **0.03 = titik balik** (ujung kaki, area pullback/balik arah), bukan TP.
- **TP1/TP2/TP3 = -0.33 / -0.66 / -0.99** (sebelumnya 0.03 / -0.33 / -0.66).
- **Entry berupa area 0.63-0.78** (bukan satu level). Kartu dan notifikasi menampilkan area itu, dan RR berupa rentang (tepi 0.63 - tepi 0.78).
- Status SUDAH LEWAT kini dipicu saat harga melewati 0.03 tanpa pullback. Env baru `FIB_TURN` (0.03); `FIB_TP` bawaan kini -0.33,-0.66,-0.99.
- Bukan saran investasi; belum ada backtest.

## Sebelumnya di v19.16: panel yang jarang dipakai diperkecil

Tiga panel di tab XAUUSD/NASDAQ kini berupa lipatan yang tertutup bawaan, tinggal ketuk judulnya untuk membuka: **Samakan dengan broker / TradingView**, **Hitung dari harga masuk Anda**, dan **Manajemen risiko**. Isi dan perhitungannya tidak berubah, hanya tampilannya.

## Yang baru di v19.14-19.15: setup Fib Retracement (sesuai pengaturan TradingView Anda)

Blok `fib` baru di setiap hasil analisis (`fib_setup.py`) dan kartu **Setup Fib Retracement** di tab XAUUSD/NASDAQ. Level persis seperti layar pengaturan Anda: **-0.99, -0.66, -0.33, 0.03, 0.63, 0.78, 0.99** (0.786 dan 2.618 tidak dicentang, jadi tidak dipakai).

- **Cara menggambar** sama dengan TradingView: level 0 di ujung kaki ayunan, level 1 di awal kaki, level negatif = perpanjangan. Diperiksa terhadap angka di screenshot Anda (0.63 = 3878.96, 0.78 = 3868.48, -0.99 = 3992.14).
- **Dua gambar dari pasangan titik yang sama (LL/LH), seperti cara Anda menarik garis:** low -> high = setup BUY, high -> low = setup SELL (`fib` dan `fib.alt`, keduanya tampil di dasbor). Area entry 0.63-0.78, SL di 0.99, TP1/TP2/TP3 di -0.33 / -0.66 / -0.99 (0.03 = titik balik; lihat v19.17).
- **Status:** MENUNGGU PULLBACK, DI ZONA ENTRY, LEWAT ENTRY (dekat SL), SETUP BATAL (lewat 0.99), SUDAH LEWAT (jangan kejar), BELUM ADA KAKI FIB.
- **Tidak mengubah sinyal utama.** Bila arah Fib berlawanan dengan sinyal 3-keluarga strategi, muncul peringatan; bila searah dan harga di zona, ditambah satu alasan di daftar alasan.
- **Env (semua opsional):** `FIB_ENABLED`, `FIB_ZONE` (0.63,0.78), `FIB_ENTRY` (0.78), `FIB_SL` (0.99), `FIB_SL_BUFFER_ATR` (0), `FIB_TP` (-0.33,-0.66,-0.99), `FIB_TURN` (0.03), `FIB_PIVOT` (10 candle kiri/kanan, supaya yang dipilih struktur besar seperti LL/LH, bukan riak kecil), `FIB_MIN_ATR` (kaki minimal 3x ATR), `FIB_MAX_AGE_BARS` (80).
- **Asumsi yang perlu Anda cek:** pemetaan level sudah dikonfirmasi Anda (v19.17); kaki ayunan dipilih otomatis lewat pivot, jadi bisa berbeda dari kaki yang Anda gambar manual. Belum ada backtest bahwa setup ini menguntungkan. Uji: `tests/test_fib.py`.

### Notifikasi Fib (EA MT5 tidak diubah)

- **Notifikasi:** pesan "FIB BUY/SELL DI ZONA ENTRY" (zona, entry limit, SL, TP, RR) sekali per pasangan titik jangkar dan arah, dan "FIB ... BATAL" bila harga melewati 0.99 setelah zona sempat diberitahukan. Hanya dari data segar dan pasar buka. Env: `FIB_NOTIFY` (1/off), `FIB_NOTIFY_TFS` (M15,M30,H1).

## Yang baru di v19.13: Retail Sales jadi berita penuh (dengan sinyal Entry/SL/TP)

Retail Sales AS (Advance Monthly Retail Trade, U.S. Census Bureau, 08:30 ET) kini berdiri sejajar dengan CPI, PPI, NFP, PCE, dan FOMC di radar NEWS: jadwal resmi, riwayat reaksi emas, pembacaan kejutan angka (Core Retail Sales dulu, lalu Retail Sales), analisis lengkap, sinyal pra-rilis (1 jam sebelum) dan pasca-rilis dengan Entry/SL/TP, Riwayat sinyal news, dan notifikasi.

- **Jadwal 2026 dari rilis resmi Census.** Jadwal sempat bergeser akibat penutupan pemerintah akhir 2025, jadi tanggal yang dipakai adalah tanggal rilis SEBENARNYA: 14 Jan, 10 Feb, 6 Mar, 1 Apr, 21 Apr, 14 Mei, 17 Jun, 16 Jul, 14 Ags, 16 Sep, 15 Okt. Mendatang: 17 Nov, 16 Des 2026; 15 Jan, 17 Feb, 16 Mar, 16 Apr, 14 Mei, 16 Jun, 16 Jul 2027. Census baru menerbitkan sampai Jul 2027: Agu-Des 2027 tambahkan di `news.py` (`SCHEDULE["RETAIL"]`) atau lewat `EXTRA_EVENTS` setelah terbit.
- **Riwayat reaksi:** 11 rilis 2026 yang sudah lewat dipelajari (di atas minimum 6). Sampel kecil: bukti statistik tetap lemah, dan hanya 2026 yang ada di jadwal (FRED tidak dipakai untuk Retail Sales).
- **Kejutan angka:** unit 0,3 poin persen (aturan praktis, bisa diubah di `SURPRISE_CFG`). Angka di atas perkiraan = dolar kuat = emas cenderung turun. NASDAQ diperlakukan ambigu (MIXED), seperti NFP.
- **Kalender high-impact:** baris Retail Sales dan Core Retail Sales dari Forex Factory tidak lagi diulang di kartu kalender karena sudah ada di radar.
- Uji: `tests/test_retail.py`. Sama seperti berita lain, sinyal ini kecenderungan dari data, bukan prediksi atau jaminan; belum ada bukti dari data pasar nyata bahwa sinyal Retail Sales menguntungkan.

## Yang baru di v19.12: kalender hanya berita high-impact USD (berdampak ke XAUUSD)

Sama dengan v19.11, ditambah filter mata uang: bawaan hanya USD (`NEWS_CAL_CURRENCIES`), hanya label High, dan label versi dinaikkan ke 19.12 agar mudah dibedakan.

### Rincian kalender high-impact (`news_calendar.py`, sejak v19.11)

Radar bawaan (FOMC, NFP, CPI AS, PPI, PCE) tidak diubah. Di tab NEWS ada kartu baru **"Kalender high-impact"** untuk berita berdampak tinggi (label High) yang berdampak ke XAUUSD: Retail Sales, ISM, GDP, klaim pengangguran, pidato/notulen Fed, dan seterusnya. **Bawaan: hanya mata uang USD**, karena emas dihargai dalam dolar AS; berita mata uang lain (mis. CPI Kanada) berdampak tidak langsung. Tambahkan lewat `NEWS_CAL_CURRENCIES` (mis. `USD,EUR,CNY` atau `ALL`).

- **Sumber:** kalender Forex Factory (feed publik yang sudah dipakai radar), pekan ini + pekan depan, jam WIB. Tidak ada tanggal karangan; bila feed gagal, yang tampil radar bawaan + catatan manual + `CAL_EXTRA`.
- **Malam ini (Senin 16 Nov 2026, 20:30 WIB = 13:30 UTC):** dengan bawaan USD saja, hanya NY Empire State yang tampil. CPI Kanada (CAD) tampil bila `NEWS_CAL_CURRENCIES=USD,CAD`. Catatan dari kalender HP Anda: 6 data CPI Kanada dan NY Empire State Manufacturing dari kalender HP Anda ada di `MANUAL_EVENTS` (dipakai hanya bila feed tidak punya berita untuk mata uang dan jam yang sama). Jadwal CPI Kanada dikonfirmasi Statistics Canada.
- **Per berita:** hitung mundur, Perkiraan / Sebelumnya / Actual. Bila Actual belum terbaca dari feed (feed gratis sering belum memuatnya), **ketik di kolom Actual lalu Enter** untuk pembacaan kejutan.
- **Pembacaan kejutan:** untuk berita USD, arah emas (angka lebih kuat dari perkiraan = dolar kuat = emas cenderung turun; pengangguran/klaim kebalikannya). Untuk mata uang lain hanya ditulis arah mata uang itu sendiri; dampak ke XAUUSD/NASDAQ tidak langsung, jadi tidak ada arah untuk emas. Ukuran kejutan memakai aturan praktis per jenis berita (bukan hasil riset).
- **Tidak ada sinyal Entry/SL/TP dari lapisan ini.** Sinyal arah di radar bawaan bergantung pada riwayat reaksi harga per jenis berita; untuk berita baru ini riwayat itu tidak ada, jadi tidak dikarang.
- **Peringatan "hindari entry baru"** (banner di tab XAUUSD/NASDAQ dan baris ⚠ di notifikasi ENTRY SIAP) mulai 30 menit sebelum sampai 15 menit sesudah berita high-impact USD (radar bawaan ikut dihitung). `NEWS_GUARD_BLOCK=1` menahan notifikasi ENTRY SIAP di jendela itu (bawaan: hanya peringatan).
- **Notifikasi:** satu pesan per jam rilis (bukan satu per berita). USD: 60 dan 5 menit sebelum rilis; mata uang lain: 60 menit sebelum; pesan "angka keluar" hanya bila feed memuat Actual.
- **Env baru:** `NEWS_CAL_CURRENCIES` (bawaan `USD`), `NEWS_CAL_IMPACT` (bawaan `high`; `high,medium` untuk menyertakan yang sedang), `NEWS_GUARD` (off), `NEWS_GUARD_BEFORE` (30), `NEWS_GUARD_AFTER` (15), `NEWS_GUARD_CURRENCIES` (bawaan `USD`; `ALL` atau daftar), `NEWS_GUARD_BLOCK`, `NEWS_CAL_NOTIFY` (bawaan `ALL`; `off` atau daftar mata uang), `NEWS_CAL_NEXTWEEK=off`, `CAL_EXTRA` (JSON berita tambahan). Uji: `tests/test_news_calendar.py`.

Batasan jujur: lapisan ini hanya selengkap kalender Forex Factory (bukan seluruh dunia); pekan depan baru tersedia bila feed-nya terbit; judul berita tampil bahasa Inggris dari feed; aturan arah dicocokkan lewat kata kunci judul, jadi judul yang tidak dikenal hanya diberi angka tanpa arah. Belum diuji dengan feed asli dari server saya (jaringan terbatas): uji memakai baris sintetis bergaya Forex Factory, jadi pantau hari pertama.

## Yang baru di v19.10: sinyal arah pra-news menyala, 1 jam sebelum rilis

- **Sinyal arah (BUY/SELL dengan Entry, SL, TP) keluar mulai 1 jam sebelum rilis.** Sebelum itu kartu hanya TUNGGU. Ini membalik keputusan v19.5 (arah pra-news dimatikan) atas permintaan pengguna. Atur dengan `NEWS_PRE_SIGNAL_HOURS` (bawaan 1); matikan dengan `NEWS_PRE_DIRECTION=off`.
- **Gerbang analisis lengkap berlaku juga untuk sinyal pra-news:** ditahan bila kurang dari 3 aspek terkumpul atau analisis berlawanan arah dengan keyakinan >=55%; bila searah keyakinan +10. Lewati dengan `NEWS_REQUIRE_ANALYSIS=off`.
- **Notifikasi pra-news** dikirim 60 menit sebelum rilis (`NEWS_PRE_MIN`, bawaan 60; dulu 30) dan masih ada pengingat 5 menit sebelum rilis. Riwayat harga yang belum lengkap tidak lagi menunda notifikasi bila sudah ada minimal 3 kejadian.
- **Penilaian sinyal pra-news:** dinilai dari saat terbit sampai 60 menit SETELAH rilis (benar bila TP1 tersentuh lebih dulu, salah bila SL lebih dulu), tampil terpisah di kartu "Riwayat sinyal news".
- Cron memakai `history_sync` yang sama dengan halaman NEWS, jadi kuota data tidak terpakai dua kali dan hasil ukur tersimpan permanen.
- Peringatan: arah sebelum angka keluar sering berbalik oleh angka berita; riwayat benar/salah di aplikasi adalah ukuran yang jujur untuk menilai apakah fitur ini layak dipercaya.

## Yang baru di v19.9: riwayat news panjang (opsional, sejak 2007)

- `news_dates.py`: tanggal rilis resmi CPI, PPI, NFP, PCE sejak tahun yang Anda pilih, dari FRED (St. Louis Fed). Isi env `FRED_API_KEY` (gratis: fred.stlouisfed.org -> My Account -> API Keys) dan `NEWS_HISTORY_FROM=2007`. FOMC tidak tersedia dari FRED, jadi FOMC tetap memakai jadwal bawaan.
- `news_store.py`: hasil ukur reaksi harga tiap kejadian disimpan permanen di Redis, jadi tiap kejadian hanya diambil SEKALI dari OANDA/Twelve Data (sebelumnya diambil ulang tiap instance baru menyala). Tanggal yang tidak ada datanya di penyedia ditandai dan dilewati 14 hari, tidak lagi menghalangi tanggal lain.
- Jumlah kejadian yang dipelajari diatur `NEWS_HISTORY_N` (bawaan 12, maksimal 300). Untuk riwayat sejak 2007 set mis. `NEWS_HISTORY_N=300`. Pengambilan data berjalan bertahap (sesuai `NEWS_CALLS_PER_MIN`), jadi butuh waktu dan kuota; progres tampil di kartu riwayat.
- Tanpa env di atas, perilaku sama seperti sebelumnya (hanya jadwal 2026-2027).
- Batasan: data candle M5 emas sejak 2007 belum tentu tersedia di penyedia Anda (tanggal tanpa data dilewati); semua kejadian dihitung sama bobotnya, padahal pasar 2007-2015 berbeda dari sekarang. Karena itu `NEWS_HISTORY_N` bawaan tetap 12 (kejadian terbaru).

## Yang baru di v19.8: analisis lengkap sebelum sinyal news (`news_context.py`)

Sebelum sinyal entry news keluar, aplikasi mengumpulkan enam aspek lalu menggabungkannya:
1. **Riwayat reaksi emas** pada kejadian lalu (bawaan 12 kejadian, env `NEWS_HISTORY_N`, maksimal 40; makin banyak makin banyak kuota Twelve Data/OANDA).
2. **Harga dan tren H1** saat ini.
3. **Angka rilis** (Forecast, Previous, Actual) dari kalender Forex Factory.
4. **Berita terkini**: judul 3 hari terakhir dari RSS Google News (tanpa kunci), tentang jenis berita dan harga emas.
5. **Sentimen judul**: kamus frasa sederhana dari sudut pandang emas (tanpa penanganan negasi, jadi hanya satu aspek).
6. **Analisis AI** (opsional): isi env `ANTHROPIC_API_KEY` (dan `NEWS_AI_MODEL`, bawaan `claude-sonnet-5-5`; `NEWS_AI_TIMEOUT` detik, bawaan 6). Judul berita dikirim sebagai data, bukan instruksi, keyakinan AI dibatasi 70%, hasil di-cache 15 menit. Tanpa kunci, aspek ini dilewati.

Aturan penggabungan:
- Bias gabungan baru ada bila minimal **3 aspek** terkumpul dan **2 searah**; keyakinan dikali kelengkapan data dan dibatasi 65%.
- **Gerbang sinyal entry setelah rilis:** ditahan (TUNGGU) bila analisis lengkap baru <3 aspek (`NEWS_MIN_ASPECTS`) atau berlawanan arah dengan keyakinan >=55%; bila searah, keyakinan +10 (maksimal 80). Matikan gerbang dengan `NEWS_REQUIRE_ANALYSIS=off`.
- Analisis dihitung untuk berita yang tinggal <=24 jam (`NEWS_ANALYSIS_HOURS`) atau sudah rilis. Matikan semua dengan `NEWS_CONTEXT=off`.
- **Bias pra-news dicatat dan dinilai**: benar bila 30 menit sejak rilis harga searah bias. Hasilnya tampil terpisah dari sinyal entry di kartu "Riwayat sinyal news". Tidak ada notifikasi SALAH untuk bias, hanya untuk sinyal entry.
- Sinyal pra-news tetap tanpa arah entry (lihat v19.5).

Batasan jujur: judul RSS bukan isi artikel, kamus sentimen kasar, AI bisa keliru dan menambah biaya/latensi, dan Forecast/Actual masa lalu tidak tersedia dari kalender, jadi "tahun lampau" hanya berupa reaksi harga emas pada kejadian lalu. Tanggal berita sebelum 2026 belum ada di jadwal.

## Yang baru di v19.7: kartu risiko mendukung akun cent

- Kartu "Manajemen risiko" punya kotak **Akun cent**: saldo dan hasil dalam USC (nilai per poin per lot tetap diisi dalam USD).
- Kartu selalu menampilkan **rugi bila SL di lot minimum 0,01** (nilai dan persen saldo). Bila angka itu melebihi batas risiko Anda, muncul peringatan merah "Setup ini tidak muat di saldo Anda" dan lot tidak dibulatkan ke atas.
- Contoh NASDAQ (nilai 1 USD per poin per lot, jarak SL 142,7 poin): lot 0,01 merugi 142,7 USC; pada saldo 1000 USC itu 14,3%.
- Jarak SL bisa dipersempit lewat env (`SL_MIN_ATR_NASDAQ`, `SL_MAX_ATR_NASDAQ`, `ATR_MULT_NASDAQ`), tetapi SL yang lebih dekat dari kebisingan normal harga lebih sering kena.

## Yang baru di v19.6: jadwal news 2027

- Jadwal NFP, CPI, PPI (BLS), keputusan FOMC (Federal Reserve), dan sebagian PCE (BEA) untuk 2027 sudah ditambahkan dan diperiksa terhadap kalender resmi pada 14 Nov 2026.
- Rapat FOMC 26-27 Okt 2027 khusus diskusi strategi tanpa voting suku bunga, jadi tidak dimasukkan.
- PCE 2027: BEA baru menerbitkan sebagian tanggal (Mar, Mei, Agu, Sep, Okt, Nov, Des). Januari, Februari, April, Juni, dan Juli belum ada; tambahkan di `news.py` (`SCHEDULE["PCE"]`) setelah BEA menerbitkannya.
- PCE 25 Nov dan 23 Des 2026 sekarang berstatus terkonfirmasi (tanpa tanda ≈).

## Yang baru di v19.5: sinyal NEWS lebih jujur, ada riwayat benar/salah

- **Tidak ada prediksi arah sebelum rilis.** Kartu dan notifikasi pra-news hanya memuat zona breakout (rencana bersyarat). Bisa dinyalakan lagi dengan `NEWS_PRE_DIRECTION=on` (tidak disarankan).
- **Sinyal sesudah rilis lebih ketat:** tanpa angka Actual, arah dari harga saja baru dikeluarkan setelah menit ke-10 dan kekuatan buktinya maksimal 50%; bila angka dan harga bertentangan hasilnya TUNGGU; kekuatan bukti tidak pernah 100% (maksimal 80%).
- **Riwayat sinyal news** (kartu di tab NEWS, file `news_log.py`): setiap sinyal BUY/SELL news yang diterbitkan dicatat, lalu dinilai dari candle M5. BENAR = TP1 lebih dulu, SALAH = SL lebih dulu (SL dan TP1 satu candle dihitung SALAH), NETRAL = 60 menit tanpa keduanya. Sinyal yang SALAH juga dikirim sebagai notifikasi. Disimpan di Redis bila tersedia.
- **Pembacaan kalender lebih andal:** sekitar jam rilis (3 menit sebelum sampai 45 menit sesudah) kalender dibaca tiap 90 detik agar Actual cepat terbaca; saat server membatasi (429) atau gagal, data terakhir yang berhasil tetap dipakai dan permintaan ditunda.

## Yang baru di v19.4: kembali ke RSI 14 + Divergence, perapian kecil

- Mesin sinyal sama dengan v19.2: detector **RSI Divergence** (RSI periode 14) di keluarga Reversal. Percobaan v19.3 (RSI 8 Close) tidak dipakai: dalam uji sintetis detector itu tidak pernah ikut menghasilkan sinyal akhir karena bertabrakan dengan filter VWAP, dan perubahan periode RSI global ikut mengubah Trend Pullback, peringatan 75/25, dan konfirmasi M1.
- Dokumentasi: RR default NASDAQ di tabel v18 disamakan dengan kode dan `.env.example` (1 / 1,5 / 2).
- Tes baru (`tests/test_v194.py`): periode RSI bawaan 14, detector divergence menyala pada kasus buatan dan tidak melihat masa depan, serta RR NASDAQ konsisten dengan `.env.example`.
- Catatan jujur: perbandingan v19.2 vs v19.3 memakai data sintetis, bukan data pasar nyata, sehingga tidak membuktikan profitabilitas. Lakukan backtest data MT5 asli dan forward-test di akun demo.

## Yang baru di v19.0: Advanced Strategy Engine (mesin utama)

v19 menggantikan konsensus tiga strategi v18 sebagai mesin sinyal teknikal utama untuk XAUUSD dan NASDAQ. Tujuh detector dikelompokkan menjadi tiga keluarga agar setup yang berkorelasi tidak dihitung sebagai suara terpisah:

- **Reversal:** Liquidity Sweep, S/R Rejection, RSI Divergence.
- **Continuation:** Trend Pullback, Fair Value Gap (FVG), Order Block.
- **Breakout:** Momentum Breakout.

Maksimal satu suara per keluarga; sinyal BUY/SELL memerlukan sedikitnya dua dari tiga keluarga searah. VWAP, ADX, dan ekspansi ATR menjadi filter konteks, bukan suara tambahan. Confidence 70/90 adalah skor keselarasan keluarga, bukan probabilitas menang. Hasil strategi ini dipakai oleh analisis sinyal dan pelacakan riwayat, bukan endpoint Shadow. Konfirmasi M1 wajib, proteksi entry terlambat, SL/TP dinamis, profil risiko, NEWS, notifikasi, API, serta EA MT5 v18 dipertahankan. EA hanya mengirim candle ke aplikasi; aplikasi tidak mengirim order otomatis.

**Batas implementasi yang perlu diketahui:** penyelarasan multi-timeframe (MTF) lintas candle HTF belum diaktifkan pada paket ini karena alur feed MT5 saat ini memproses timeframe secara terpisah dan belum mengikat candle HTF tertutup ke sinyal timeframe aktif. Jangan menganggap filter MTF sudah berjalan. Filter VWAP memakai rolling 24 candle (proxy VWAP bila volume tidak tersedia), sehingga bukan VWAP sesi bursa resmi. Aturan ini perlu backtest dan forward-test demo; tidak ada klaim profitabilitas.

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
| RR TP1/TP2/TP3 | 2 / 3 / 4 | 1 / 1,5 / 2 |
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
- Besar kejutan memakai satuan praktis di `news.py` (`SURPRISE_CFG`): CPI/PPI/PCE 0,1 poin persen, NFP 50 ribu, suku bunga 0,25. Ubah sesuai pengalamanmu.

**Sumber angka:** Forecast dan Previous dibaca otomatis dari feed kalender Forex Factory
(`https://nfs.faireconomy.media/ff_calendar_thisweek.json`, hanya memuat pekan berjalan). Feed gratis ini **tidak memuat Actual**,
jadi Actual diketik manual tepat setelah rilis di kartu "Angka berita". Bila feed gagal terbaca, isi semuanya manual. Aplikasi tetap jalan.

## Yang baru di v19.2 NEWS: dampak berita lintas instrumen (NEWS-only)

Pembaruan ini hanya menambah konteks analisis pada tab NEWS. Mesin sinyal teknikal di `signals.py`, profil risiko, konfirmasi M1, notifikasi sinyal teknikal, dan alur EA MT5 tidak diubah.

- Modul baru `news_intelligence.py` menggabungkan kejutan Actual (bila tersedia) dengan tren H1 NASDAQ dan XAUUSD.
- Panel NEWS menampilkan bias makro, tren H1, dan hasil konfirmasi untuk kedua instrumen.
- Untuk CPI/PPI/PCE/FOMC, bias makro hanya ditampilkan sebagai kecenderungan; BUY/SELL lintas instrumen hanya muncul jika Actual tersedia dan tren H1 searah. Selain itu hasilnya WAIT.
- NFP untuk NASDAQ ditandai MIXED/WAIT karena dampaknya dapat mendukung pertumbuhan tetapi juga menaikkan yield.
- Panel ini adalah mesin aturan transparan, bukan AI/LLM dan bukan probabilitas menang. Tidak ada order MT5 yang dikirim.
- Sinyal NEWS XAUUSD yang lama dipertahankan. Studi reaksi historis yang lama tetap XAUUSD; pembaruan ini belum mengklaim historical backtest NASDAQ atau sentiment artikel berita.

Uji logika tambahan: `python -m unittest discover -s tests -p 'test_news_intelligence.py' -v`.

## Struktur file

| File | Fungsi |
|---|---|
| `app.py` | server Flask, rute API, cron notifikasi |
| `news.py` | jadwal berita, studi reaksi harga XAUUSD, pembaca angka berita, sinyal news lama |
| `news_intelligence.py` | analisis bias makro NEWS untuk NASDAQ dan XAUUSD |
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
   - `NEWS_PRE_SIGNAL_HOURS` (bawaan 24): sinyal arah sebelum news baru terbit sejak sekian jam sebelum rilis; lebih jauh dari itu kartu hanya menampilkan TUNGGU dan riwayat reaksi.
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
