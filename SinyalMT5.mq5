//+------------------------------------------------------------------+
//| SinyalMT5.mq5                                                     |
//| Mengirim candle XAUUSD dan NAS100 dari broker kamu ke aplikasi    |
//| sinyal (sinyal-xauusd.vercel.app) setiap kali candle M1 tutup.    |
//|                                                                   |
//| EA ini TIDAK membuka, menutup, atau mengubah order apa pun.       |
//| Ia hanya membaca harga dan mengirimnya lewat internet.            |
//+------------------------------------------------------------------+
#property copyright "Aplikasi sinyal pribadi"
#property version   "1.00"
#property description "Kirim candle broker (M1-H1) ke aplikasi sinyal tiap menit. Tidak melakukan trading."

input string AppUrl    = "https://sinyal-xauusd.vercel.app"; // Alamat aplikasi (tanpa / di akhir)
input string Kunci     = "";       // Kunci: isi dengan CRON_SECRET dari Vercel
input string SimbolXAU = "XAUUSD"; // Nama simbol emas di Market Watch (kosongkan bila tidak dipakai)
input string SimbolNAS = "NAS100"; // Nama simbol NAS100 di Market Watch (kosongkan bila tidak dipakai)
input int    JumlahBar = 300;      // Jumlah candle per timeframe (minimal 150)

string          KEYS[2] = {"XAUUSD", "NASDAQ"};    // nama instrumen di aplikasi
string          SYMS[2];                           // nama simbol di broker
ENUM_TIMEFRAMES TFS[4]  = {PERIOD_M5, PERIOD_M15, PERIOD_M30, PERIOD_H1};
string          TFN[4]  = {"M5", "M15", "M30", "H1"};
datetime        sentClosed[2][4];                  // candle tertutup terakhir yang sudah terkirim
datetime        lastMinute = 0;
datetime        lastTry    = 0;
int             okCount    = 0;
string          lastStatus = "menunggu candle M1 berikutnya";
string          baseUrl;

//+------------------------------------------------------------------+
int OnInit()
  {
   SYMS[0] = SimbolXAU;
   SYMS[1] = SimbolNAS;
   baseUrl = AppUrl;
   while(StringLen(baseUrl) > 0 && StringSubstr(baseUrl, StringLen(baseUrl) - 1) == "/")
      baseUrl = StringSubstr(baseUrl, 0, StringLen(baseUrl) - 1);

   if(StringLen(Kunci) == 0)
     {
      Alert("SinyalMT5: isi input 'Kunci' dengan CRON_SECRET dari Vercel.");
      return(INIT_PARAMETERS_INCORRECT);
     }
   for(int s = 0; s < 2; s++)
     {
      if(SYMS[s] == "")
         continue;
      if(!SymbolSelect(SYMS[s], true))
        {
         Alert("SinyalMT5: simbol '" + SYMS[s] + "' tidak ditemukan. Salin nama persis dari Market Watch.");
         return(INIT_PARAMETERS_INCORRECT);
        }
     }
   for(int s = 0; s < 2; s++)
      for(int k = 0; k < 4; k++)
         sentClosed[s][k] = 0;
   EventSetTimer(5);
   Show();
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
   Comment("");
  }

//+------------------------------------------------------------------+
void OnTick() { }

//+------------------------------------------------------------------+
//| Selisih jam server broker terhadap UTC (detik), dibulatkan 15 mnt |
//+------------------------------------------------------------------+
int ServerOffset()
  {
   double d = (double)(TimeTradeServer() - TimeGMT());
   return((int)(MathRound(d / 900.0) * 900.0));
  }

//+------------------------------------------------------------------+
//| Tambahkan candle ke JSON. Kembalikan jumlah candle.               |
//+------------------------------------------------------------------+
int AppendRates(string &js, const string sym, const ENUM_TIMEFRAMES tf, const int count, const int off)
  {
   MqlRates r[];
   ArraySetAsSeries(r, false);                    // urut dari lama ke baru
   int n = CopyRates(sym, tf, 0, count, r);       // termasuk candle yang sedang berjalan
   if(n <= 0)
     {
      js += "[]";
      return(0);
     }
   int dg = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   js += "[";
   for(int i = 0; i < n; i++)
     {
      if(i > 0)
         js += ",";
      js += "[" + IntegerToString((long)r[i].time - off) + "," +
            DoubleToString(r[i].open, dg) + "," + DoubleToString(r[i].high, dg) + "," +
            DoubleToString(r[i].low, dg) + "," + DoubleToString(r[i].close, dg) + "]";
     }
   js += "]";
   return(n);
  }

//+------------------------------------------------------------------+
bool Push()
  {
   int off  = ServerOffset();
   int bars = (int)MathMax(JumlahBar, 150);
   datetime closedNow[2][4];
   int      gotBars[2][4];
   for(int s = 0; s < 2; s++)
      for(int k = 0; k < 4; k++)
        {
         closedNow[s][k] = 0;
         gotBars[s][k]   = 0;
        }

   string js = "{\"key\":\"" + Kunci + "\",\"sent\":" + IntegerToString((long)TimeGMT()) +
               ",\"server_offset\":" + IntegerToString(off) + ",\"symbols\":{";
   int ns = 0;
   for(int s = 0; s < 2; s++)
     {
      if(SYMS[s] == "")
         continue;
      if(ns > 0)
         js += ",";
      ns++;
      js += "\"" + KEYS[s] + "\":{\"broker\":\"" + SYMS[s] + "\",\"tf\":{\"M1\":";
      AppendRates(js, SYMS[s], PERIOD_M1, 150, off);
      for(int k = 0; k < 4; k++)
        {
         closedNow[s][k] = iTime(SYMS[s], TFS[k], 1);          // candle tertutup terakhir
         if(closedNow[s][k] != 0 && closedNow[s][k] != sentClosed[s][k])
           {
            js += ",\"" + TFN[k] + "\":";
            gotBars[s][k] = AppendRates(js, SYMS[s], TFS[k], bars, off);
           }
        }
      js += "}}";
     }
   js += "}}";

   char body[], res[];
   string resHeaders;
   int len = StringToCharArray(js, body, 0, WHOLE_ARRAY, CP_UTF8);
   if(len > 0)
      ArrayResize(body, len - 1);                              // buang karakter nol di akhir
   ResetLastError();
   int code = WebRequest("POST", baseUrl + "/api/mt5", "Content-Type: application/json\r\n",
                         20000, body, res, resHeaders);
   string txt = CharArrayToString(res, 0, WHOLE_ARRAY, CP_UTF8);

   if(code == -1)
     {
      int err = GetLastError();
      if(err == 4014)
         lastStatus = "DITOLAK MT5. Buka Tools > Options > Expert Advisors, centang 'Allow WebRequest', tambahkan " + baseUrl;
      else
         lastStatus = "gagal kirim (error " + IntegerToString(err) + "), dicoba lagi otomatis";
      Print("SinyalMT5: ", lastStatus);
      return(false);
     }
   if(code != 200)
     {
      lastStatus = "server menjawab HTTP " + IntegerToString(code) + ": " + StringSubstr(txt, 0, 160);
      Print("SinyalMT5: ", lastStatus);
      return(false);
     }
   for(int s = 0; s < 2; s++)
      for(int k = 0; k < 4; k++)
         if(gotBars[s][k] >= 130)                               // riwayat cukup: tandai terkirim
            sentClosed[s][k] = closedNow[s][k];
   okCount++;
   lastStatus = "OK " + TimeToString(TimeLocal(), TIME_MINUTES) + " (" + IntegerToString(okCount) + " kiriman) " +
                StringSubstr(txt, 0, 160);
   return(true);
  }

//+------------------------------------------------------------------+
void OnTimer()
  {
   datetime m = 0;
   for(int s = 0; s < 2; s++)
      if(SYMS[s] != "")
        {
         datetime t = iTime(SYMS[s], PERIOD_M1, 0);
         if(t > m)
            m = t;
        }
   if(m == 0 || m == lastMinute)
      return;                                                   // belum ada candle M1 baru
   if(TimeLocal() - lastTry < 20)
      return;                                                   // jeda setelah gagal
   lastTry = TimeLocal();
   if(Push())
      lastMinute = m;
   Show();
  }

//+------------------------------------------------------------------+
void Show()
  {
   int off = ServerOffset();
   Comment("SinyalMT5 -> " + baseUrl +
           "\nSimbol: " + (SYMS[0] == "" ? "-" : SYMS[0]) + " | " + (SYMS[1] == "" ? "-" : SYMS[1]) +
           "\nJam server broker: UTC" + (off >= 0 ? "+" : "") + DoubleToString(off / 3600.0, 1) +
           "\nStatus: " + lastStatus);
  }
//+------------------------------------------------------------------+
