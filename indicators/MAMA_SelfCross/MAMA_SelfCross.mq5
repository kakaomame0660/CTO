//+------------------------------------------------------------------+
//|                                               MAMA_SelfCross.mq5 |
//|              MAMA（MAのMA）自己相関クロス ＆ 相互監視インジケーター |
//+------------------------------------------------------------------+
//  MAMA       : 「MA の MA」。MA に同じ期間の MA をもう一度かけた線（自己移動平均線）
//               ※ Ehlers の MESA Adaptive Moving Average（MAMA）とは別物
//  自己相関クロス : 同じ期間の MA と MAMA のクロス
//               小矢印 = 短期（既定 5）  大矢印 = 長期（既定 20）
//  相互監視   : 2 つの自己相関クロスの向きが揃ったらその方向へ。
//               エントリー後、逆向きのクロスが出たら終了。
//               ・小→大 : 小矢印のあと大矢印を待つ → 大きく取る
//               ・大→小 : 大矢印のあと小矢印を待つ → 細かく取る
//  パターンB  : 短期MAMA と 長期MA のクロス（逆クロスで終了）
//  トレンドMA : 200MA などで「トレンドに逆らわない」ためのフィルター
//+------------------------------------------------------------------+
#property copyright   "MAMA SelfCross"
#property version     "1.00"
#property description "MAMA（MAのMA）自己相関クロス ＆ 相互監視"
#property description "⇧⇩ 小矢印 = 短期の自己相関クロス / 太矢印 = 長期の自己相関クロス"
#property description "● = エントリー（2つのクロスの向きが一致） / ✕ = 決済 / ○ = パターンB"
#property indicator_chart_window
#property indicator_buffers 21
#property indicator_plots   14

//--- ライン
#property indicator_label1  "短期MA"
#property indicator_type1   DRAW_LINE
#property indicator_color1  clrMagenta
#property indicator_width1  1

#property indicator_label2  "短期MAMA"
#property indicator_type2   DRAW_LINE
#property indicator_color2  clrAqua
#property indicator_width2  1

#property indicator_label3  "長期MA"
#property indicator_type3   DRAW_LINE
#property indicator_color3  clrLimeGreen
#property indicator_width3  1

#property indicator_label4  "長期MAMA"
#property indicator_type4   DRAW_LINE
#property indicator_color4  clrYellow
#property indicator_width4  1

#property indicator_label5  "トレンドMA"
#property indicator_type5   DRAW_LINE
#property indicator_color5  clrOrange
#property indicator_width5  2

//--- 自己相関クロスの矢印
#property indicator_label6  "小矢印↑"
#property indicator_type6   DRAW_ARROW
#property indicator_color6  clrAqua
#property indicator_width6  1

#property indicator_label7  "小矢印↓"
#property indicator_type7   DRAW_ARROW
#property indicator_color7  clrRed
#property indicator_width7  1

#property indicator_label8  "大矢印↑"
#property indicator_type8   DRAW_ARROW
#property indicator_color8  clrAqua
#property indicator_width8  2

#property indicator_label9  "大矢印↓"
#property indicator_type9   DRAW_ARROW
#property indicator_color9  clrRed
#property indicator_width9  2

//--- 相互監視のエントリー／決済
#property indicator_label10 "買いエントリー"
#property indicator_type10  DRAW_ARROW
#property indicator_color10 clrDodgerBlue
#property indicator_width10 2

#property indicator_label11 "売りエントリー"
#property indicator_type11  DRAW_ARROW
#property indicator_color11 clrOrangeRed
#property indicator_width11 2

#property indicator_label12 "決済"
#property indicator_type12  DRAW_ARROW
#property indicator_color12 clrSilver
#property indicator_width12 1

//--- パターンB
#property indicator_label13 "パターンB↑"
#property indicator_type13  DRAW_ARROW
#property indicator_color13 clrAqua
#property indicator_width13 1

#property indicator_label14 "パターンB↓"
#property indicator_type14  DRAW_ARROW
#property indicator_color14 clrRed
#property indicator_width14 1

//+------------------------------------------------------------------+
//| 列挙型                                                            |
//+------------------------------------------------------------------+
enum ENUM_ENTRY_MODE
  {
   ENTRY_BOTH = 0, // 両方
   ENTRY_BIG  = 1, // 小→大（大矢印で入る＝大きく取る）
   ENTRY_FINE = 2  // 大→小（小矢印で入る＝細かく取る）
  };

enum ENUM_EXIT_MODE
  {
   EXIT_ANY  = 0, // どちらかの逆クロス（原典ルール）
   EXIT_SLOW = 1, // 長期（大）の逆クロスのみ
   EXIT_FAST = 2, // 短期（小）の逆クロスのみ
   EXIT_AUTO = 3  // 自動（大矢印で入ったら長期／小矢印ならどちらか）
  };

enum ENUM_TREND_FILTER
  {
   TREND_OFF   = 0, // OFF
   TREND_PRICE = 1, // 価格がトレンドMAの上なら買いのみ／下なら売りのみ
   TREND_SLOPE = 2  // トレンドMAの傾きの方向のみ
  };

//+------------------------------------------------------------------+
//| 入力                                                              |
//+------------------------------------------------------------------+
input group "■ 移動平均"
input int                InpFastPeriod     = 5;                  // 短期 期間（小矢印）
input int                InpSlowPeriod     = 20;                 // 長期 期間（大矢印）
input ENUM_MA_METHOD     InpMAMethod       = MODE_SMA;           // MA の種類
input ENUM_MA_METHOD     InpMAMAMethod     = MODE_SMA;           // MAMA（MAのMA）の種類
input ENUM_APPLIED_PRICE InpPrice          = PRICE_CLOSE;        // 適用価格
input int                InpTrendPeriod    = 200;                // トレンドMA 期間（0 = 使わない）

input group "■ シグナル（相互監視）"
input ENUM_ENTRY_MODE    InpEntryMode      = ENTRY_BOTH;         // エントリー方式
input ENUM_EXIT_MODE     InpExitMode       = EXIT_AUTO;           // 決済条件
input ENUM_TREND_FILTER  InpTrendFilter    = TREND_OFF;          // トレンドフィルター
input bool               InpConfirmed      = true;               // 確定足で判定（リペイントしない）

input group "■ パターンB（短期MAMA × 長期MA）"
input bool               InpShowB          = false;              // パターンB のクロスを表示

input group "■ 表示"
input bool               InpShowFastArrow  = true;               // 小矢印（短期の自己相関クロス）
input bool               InpShowSlowArrow  = true;               // 大矢印（長期の自己相関クロス）
input bool               InpShowEntry      = true;               // エントリー●／決済✕
input double             InpMarkGap        = 0.6;                // マークの間隔（ATR 倍）
input bool               InpHideCandles    = false;              // ローソク足を隠す（MA だけのすっきり表示）
input bool               InpShowPanel      = true;               // 状態パネル
input ENUM_BASE_CORNER   InpPanelCorner    = CORNER_RIGHT_UPPER; // パネル位置
input int                InpPanelFontSize  = 9;                  // パネル文字サイズ
input string             InpPanelFont      = "MS Gothic";        // パネルフォント

input group "■ アラート（確定足で 1 回）"
input bool               InpAlertEntry     = true;               // エントリー／決済で通知
input bool               InpAlertSelfCross = false;              // 自己相関クロス（矢印）でも通知
input bool               InpAlertB         = false;              // パターンB でも通知
input bool               InpAlertPopup     = true;               // ポップアップ
input bool               InpAlertSound     = false;              // サウンド
input bool               InpAlertPush      = false;              // プッシュ通知（スマホ）
input bool               InpAlertMail      = false;              // メール

//+------------------------------------------------------------------+
//| 定数・バッファ                                                      |
//+------------------------------------------------------------------+
#define PANEL_PREFIX  "MAMASC_PANEL_"
#define PANEL_LINES   6
#define ATR_PERIOD    14

//--- 描画バッファ
double BufFastMA[];
double BufFastMAMA[];
double BufSlowMA[];
double BufSlowMAMA[];
double BufTrendMA[];
double BufFastUp[];
double BufFastDn[];
double BufSlowUp[];
double BufSlowDn[];
double BufLong[];
double BufShort[];
double BufExit[];
double BufBUp[];
double BufBDn[];
//--- 計算用バッファ
double BufPrice[];
double BufATR[];
double BufFastDir[];   // 1 = 短期MA が 短期MAMA の上、-1 = 下
double BufSlowDir[];   // 1 = 長期MA が 長期MAMA の上、-1 = 下
double BufBDir[];      // 1 = 短期MAMA が 長期MA の上、-1 = 下
double BufPos[];       // 1 = 買い保有、-1 = 売り保有、0 = なし
double BufPosKind[];   // 1 = 大矢印で建てた、2 = 小矢印で建てた

datetime g_lastBarTime = 0;
long     g_savedColors[5];
bool     g_colorsSaved = false;

//+------------------------------------------------------------------+
//| 初期化                                                             |
//+------------------------------------------------------------------+
int OnInit()
  {
   if(InpFastPeriod < 1 || InpSlowPeriod < 1 || InpTrendPeriod < 0)
     {
      Print("MAMA SelfCross: 期間の設定が不正です");
      return(INIT_PARAMETERS_INCORRECT);
     }

   SetIndexBuffer(0,  BufFastMA,   INDICATOR_DATA);
   SetIndexBuffer(1,  BufFastMAMA, INDICATOR_DATA);
   SetIndexBuffer(2,  BufSlowMA,   INDICATOR_DATA);
   SetIndexBuffer(3,  BufSlowMAMA, INDICATOR_DATA);
   SetIndexBuffer(4,  BufTrendMA,  INDICATOR_DATA);
   SetIndexBuffer(5,  BufFastUp,   INDICATOR_DATA);
   SetIndexBuffer(6,  BufFastDn,   INDICATOR_DATA);
   SetIndexBuffer(7,  BufSlowUp,   INDICATOR_DATA);
   SetIndexBuffer(8,  BufSlowDn,   INDICATOR_DATA);
   SetIndexBuffer(9,  BufLong,     INDICATOR_DATA);
   SetIndexBuffer(10, BufShort,    INDICATOR_DATA);
   SetIndexBuffer(11, BufExit,     INDICATOR_DATA);
   SetIndexBuffer(12, BufBUp,      INDICATOR_DATA);
   SetIndexBuffer(13, BufBDn,      INDICATOR_DATA);
   SetIndexBuffer(14, BufPrice,    INDICATOR_CALCULATIONS);
   SetIndexBuffer(15, BufATR,      INDICATOR_CALCULATIONS);
   SetIndexBuffer(16, BufFastDir,  INDICATOR_CALCULATIONS);
   SetIndexBuffer(17, BufSlowDir,  INDICATOR_CALCULATIONS);
   SetIndexBuffer(18, BufBDir,     INDICATOR_CALCULATIONS);
   SetIndexBuffer(19, BufPos,      INDICATOR_CALCULATIONS);
   SetIndexBuffer(20, BufPosKind,  INDICATOR_CALCULATIONS);

   for(int p = 0; p < 14; p++)
      PlotIndexSetDouble(p, PLOT_EMPTY_VALUE, EMPTY_VALUE);

   //--- Wingdings の記号
   PlotIndexSetInteger(5,  PLOT_ARROW, 241);   // ⇧ 小矢印↑
   PlotIndexSetInteger(6,  PLOT_ARROW, 242);   // ⇩ 小矢印↓
   PlotIndexSetInteger(7,  PLOT_ARROW, 233);   // 太矢印↑
   PlotIndexSetInteger(8,  PLOT_ARROW, 234);   // 太矢印↓
   PlotIndexSetInteger(9,  PLOT_ARROW, 108);   // ● 買い
   PlotIndexSetInteger(10, PLOT_ARROW, 108);   // ● 売り
   PlotIndexSetInteger(11, PLOT_ARROW, 251);   // ✕ 決済
   PlotIndexSetInteger(12, PLOT_ARROW, 161);   // ○ パターンB↑
   PlotIndexSetInteger(13, PLOT_ARROW, 161);   // ○ パターンB↓

   PlotIndexSetInteger(0, PLOT_DRAW_BEGIN, InpFastPeriod - 1);
   PlotIndexSetInteger(1, PLOT_DRAW_BEGIN, 2 * InpFastPeriod - 2);
   PlotIndexSetInteger(2, PLOT_DRAW_BEGIN, InpSlowPeriod - 1);
   PlotIndexSetInteger(3, PLOT_DRAW_BEGIN, 2 * InpSlowPeriod - 2);
   PlotIndexSetInteger(4, PLOT_DRAW_BEGIN, InpTrendPeriod > 0 ? InpTrendPeriod - 1 : 0);

   IndicatorSetString(INDICATOR_SHORTNAME, StringFormat("MAMA SelfCross (%d/%d)", InpFastPeriod, InpSlowPeriod));
   IndicatorSetInteger(INDICATOR_DIGITS, _Digits);

   g_lastBarTime = 0;
   if(InpHideCandles)
      HideCandles();

   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
//| 終了処理                                                           |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   RestoreCandles();
   ObjectsDeleteAll(0, PANEL_PREFIX);
   ChartRedraw();
  }

//+------------------------------------------------------------------+
//| メイン計算                                                         |
//+------------------------------------------------------------------+
int OnCalculate(const int rates_total,
                const int prev_calculated,
                const datetime &time[],
                const double &open[],
                const double &high[],
                const double &low[],
                const double &close[],
                const long &tick_volume[],
                const long &volume[],
                const int &spread[])
  {
   if(rates_total < 2)
      return(0);

   int start = (prev_calculated <= 0 || prev_calculated > rates_total) ? 0 : prev_calculated - 1;

   for(int i = start; i < rates_total; i++)
     {
      //--- 価格と ATR（ATR はマークの位置決め用）
      BufPrice[i] = AppliedPrice(InpPrice, open[i], high[i], low[i], close[i]);
      if(i == 0)
         BufATR[i] = high[i] - low[i];
      else
        {
         double tr = MathMax(high[i], close[i - 1]) - MathMin(low[i], close[i - 1]);
         BufATR[i] = BufATR[i - 1] + (tr - BufATR[i - 1]) / ATR_PERIOD;
        }

      //--- MA と MAMA（MA の MA）
      BufFastMA[i]   = CalcMA(BufPrice,  BufFastMA,   i, InpFastPeriod, InpMAMethod,   0);
      BufFastMAMA[i] = CalcMA(BufFastMA, BufFastMAMA, i, InpFastPeriod, InpMAMAMethod, InpFastPeriod - 1);
      BufSlowMA[i]   = CalcMA(BufPrice,  BufSlowMA,   i, InpSlowPeriod, InpMAMethod,   0);
      BufSlowMAMA[i] = CalcMA(BufSlowMA, BufSlowMAMA, i, InpSlowPeriod, InpMAMAMethod, InpSlowPeriod - 1);
      BufTrendMA[i]  = (InpTrendPeriod > 0) ? CalcMA(BufPrice, BufTrendMA, i, InpTrendPeriod, InpMAMethod, 0) : EMPTY_VALUE;

      //--- 自己相関クロスの向き
      BufFastDir[i] = Dir(BufFastMA[i],   BufFastMAMA[i], i > 0 ? (int)BufFastDir[i - 1] : 0);
      BufSlowDir[i] = Dir(BufSlowMA[i],   BufSlowMAMA[i], i > 0 ? (int)BufSlowDir[i - 1] : 0);
      BufBDir[i]    = Dir(BufFastMAMA[i], BufSlowMA[i],   i > 0 ? (int)BufBDir[i - 1]    : 0);

      //--- マークをクリアしてポジション状態を引き継ぐ
      BufFastUp[i] = EMPTY_VALUE;
      BufFastDn[i] = EMPTY_VALUE;
      BufSlowUp[i] = EMPTY_VALUE;
      BufSlowDn[i] = EMPTY_VALUE;
      BufLong[i]   = EMPTY_VALUE;
      BufShort[i]  = EMPTY_VALUE;
      BufExit[i]   = EMPTY_VALUE;
      BufBUp[i]    = EMPTY_VALUE;
      BufBDn[i]    = EMPTY_VALUE;

      int pos  = (i > 0) ? (int)BufPos[i - 1]     : 0;
      int kind = (i > 0) ? (int)BufPosKind[i - 1] : 0;
      BufPos[i]     = pos;
      BufPosKind[i] = kind;

      if(i == 0)
         continue;
      //--- 確定足モードでは形成中の足でシグナルを出さない
      if(InpConfirmed && i == rates_total - 1)
         continue;

      int fd = (int)BufFastDir[i], fdPrev = (int)BufFastDir[i - 1];
      int sd = (int)BufSlowDir[i], sdPrev = (int)BufSlowDir[i - 1];
      int bd = (int)BufBDir[i],    bdPrev = (int)BufBDir[i - 1];

      bool fastUp = (fd == 1  && fdPrev == -1);
      bool fastDn = (fd == -1 && fdPrev == 1);
      bool slowUp = (sd == 1  && sdPrev == -1);
      bool slowDn = (sd == -1 && sdPrev == 1);
      bool bUp    = (bd == 1  && bdPrev == -1);
      bool bDn    = (bd == -1 && bdPrev == 1);

      //--- トレンドフィルター
      bool trendUpOk = true, trendDnOk = true;
      if(InpTrendFilter != TREND_OFF && InpTrendPeriod > 0)
        {
         double t0 = BufTrendMA[i], t1 = BufTrendMA[i - 1];
         if(t0 == EMPTY_VALUE || t1 == EMPTY_VALUE)
           {
            trendUpOk = false;
            trendDnOk = false;
           }
         else if(InpTrendFilter == TREND_PRICE)
           {
            trendUpOk = close[i] > t0;
            trendDnOk = close[i] < t0;
           }
         else
           {
            trendUpOk = t0 > t1;
            trendDnOk = t0 < t1;
           }
        }

      //--- 相互監視：もう片方がすでに同じ向きのときにクロスしたら「向きが揃った」
      bool longBySlow  = slowUp && fd == 1;    // 小→大（大矢印で入る）
      bool longByFast  = fastUp && sd == 1;    // 大→小（小矢印で入る）
      bool shortBySlow = slowDn && fd == -1;
      bool shortByFast = fastDn && sd == -1;

      bool useSlowTrig = (InpEntryMode != ENTRY_FINE);
      bool useFastTrig = (InpEntryMode != ENTRY_BIG);
      bool longTrig    = ((useSlowTrig && longBySlow)  || (useFastTrig && longByFast))  && trendUpOk;
      bool shortTrig   = ((useSlowTrig && shortBySlow) || (useFastTrig && shortByFast)) && trendDnOk;

      //--- 決済 → エントリーの順に判定
      bool exitLong = false, exitShort = false;
      if(pos == 1 && ExitHit(kind, fastDn, slowDn))
        {
         exitLong = true;
         pos  = 0;
         kind = 0;
        }
      else if(pos == -1 && ExitHit(kind, fastUp, slowUp))
        {
         exitShort = true;
         pos  = 0;
         kind = 0;
        }

      bool goLong  = longTrig  && pos != 1;
      bool goShort = shortTrig && pos != -1;
      if(goLong)
        {
         if(pos == -1)
            exitShort = true;
         pos  = 1;
         kind = (useSlowTrig && longBySlow) ? 1 : 2;
        }
      if(goShort)
        {
         if(pos == 1)
            exitLong = true;
         pos  = -1;
         kind = (useSlowTrig && shortBySlow) ? 1 : 2;
        }
      BufPos[i]     = pos;
      BufPosKind[i] = kind;

      //--- マーク（同じ足に複数出るときは外側へ積む）
      double step  = BufATR[i] * InpMarkGap;
      double yLow  = low[i];
      double yHigh = high[i];

      if(InpShowFastArrow)
        {
         if(fastUp) { yLow  -= step; BufFastUp[i] = yLow;  }
         if(fastDn) { yHigh += step; BufFastDn[i] = yHigh; }
        }
      if(InpShowSlowArrow)
        {
         if(slowUp) { yLow  -= step; BufSlowUp[i] = yLow;  }
         if(slowDn) { yHigh += step; BufSlowDn[i] = yHigh; }
        }
      if(InpShowEntry)
        {
         if(goLong)  { yLow  -= step * 1.2; BufLong[i]  = yLow;  }
         if(goShort) { yHigh += step * 1.2; BufShort[i] = yHigh; }
         if(exitLong || exitShort)
            BufExit[i] = close[i];
        }
      if(InpShowB)
        {
         if(bUp) BufBUp[i] = (BufFastMAMA[i] + BufSlowMA[i]) / 2.0;
         if(bDn) BufBDn[i] = (BufFastMAMA[i] + BufSlowMA[i]) / 2.0;
        }
     }

   //--- 新しい足ができたら、直前の確定足でアラート判定（初回ロード時は鳴らさない）
   datetime curBar = time[rates_total - 1];
   if(prev_calculated <= 0 || g_lastBarTime == 0)
      g_lastBarTime = curBar;
   else if(curBar != g_lastBarTime)
     {
      g_lastBarTime = curBar;
      CheckAlerts(rates_total - 2);
     }

   if(InpShowPanel)
      UpdatePanel(rates_total - 1, close);

   return(rates_total);
  }

//+------------------------------------------------------------------+
//| 適用価格                                                           |
//+------------------------------------------------------------------+
double AppliedPrice(const ENUM_APPLIED_PRICE type, const double o, const double h, const double l, const double c)
  {
   switch(type)
     {
      case PRICE_OPEN:     return(o);
      case PRICE_HIGH:     return(h);
      case PRICE_LOW:      return(l);
      case PRICE_MEDIAN:   return((h + l) / 2.0);
      case PRICE_TYPICAL:  return((h + l + c) / 3.0);
      case PRICE_WEIGHTED: return((h + l + 2.0 * c) / 4.0);
      default:             return(c);
     }
  }

//+------------------------------------------------------------------+
//| 単純移動平均                                                        |
//+------------------------------------------------------------------+
double SMA(const double &src[], const int i, const int period)
  {
   double sum = 0.0;
   for(int k = 0; k < period; k++)
      sum += src[i - k];
   return(sum / period);
  }

//+------------------------------------------------------------------+
//| src[] の i 本目の移動平均。begin = src[] で値が入り始める位置           |
//| dst[] は自分自身の出力（EMA / SMMA の前回値として使う）                 |
//+------------------------------------------------------------------+
double CalcMA(const double &src[], const double &dst[], const int i, const int period,
              const ENUM_MA_METHOD method, const int begin)
  {
   int first = begin + period - 1;
   if(i < first)
      return(EMPTY_VALUE);

   switch(method)
     {
      case MODE_EMA:
        {
         if(i == first || dst[i - 1] == EMPTY_VALUE)
            return(SMA(src, i, period));
         double a = 2.0 / (period + 1.0);
         return(src[i] * a + dst[i - 1] * (1.0 - a));
        }
      case MODE_SMMA:
        {
         if(i == first || dst[i - 1] == EMPTY_VALUE)
            return(SMA(src, i, period));
         return((dst[i - 1] * (period - 1) + src[i]) / period);
        }
      case MODE_LWMA:
        {
         double sum = 0.0, wsum = 0.0;
         for(int k = 0; k < period; k++)
           {
            double w = period - k;
            sum  += src[i - k] * w;
            wsum += w;
           }
         return(sum / wsum);
        }
      default:
         return(SMA(src, i, period));
     }
  }

//+------------------------------------------------------------------+
//| a と b の上下関係。同値のときは直前の向きを引き継ぐ                       |
//+------------------------------------------------------------------+
int Dir(const double a, const double b, const int prev)
  {
   if(a == EMPTY_VALUE || b == EMPTY_VALUE)
      return(0);
   if(a > b)
      return(1);
   if(a < b)
      return(-1);
   return(prev);
  }

//+------------------------------------------------------------------+
//| 保有中のポジションを閉じるか                                          |
//| fastRev / slowRev = 保有方向と逆向きのクロスが出たか                    |
//+------------------------------------------------------------------+
bool ExitHit(const int kind, const bool fastRev, const bool slowRev)
  {
   switch(InpExitMode)
     {
      case EXIT_SLOW: return(slowRev);
      case EXIT_FAST: return(fastRev);
      case EXIT_AUTO: return(kind == 1 ? slowRev : (fastRev || slowRev));
      default:        return(fastRev || slowRev);
     }
  }

//+------------------------------------------------------------------+
//| アラート                                                           |
//+------------------------------------------------------------------+
void CheckAlerts(const int b)
  {
   if(b < 1)
      return;

   string msg = "";
   if(InpAlertSelfCross)
     {
      int fd = (int)BufFastDir[b], fdPrev = (int)BufFastDir[b - 1];
      int sd = (int)BufSlowDir[b], sdPrev = (int)BufSlowDir[b - 1];
      if(fd == 1  && fdPrev == -1) msg += "小矢印↑ ";
      if(fd == -1 && fdPrev == 1)  msg += "小矢印↓ ";
      if(sd == 1  && sdPrev == -1) msg += "大矢印↑ ";
      if(sd == -1 && sdPrev == 1)  msg += "大矢印↓ ";
     }
   if(InpAlertEntry)
     {
      int p = (int)BufPos[b], pPrev = (int)BufPos[b - 1];
      if(pPrev == 1  && p != 1)  msg += "買い決済 ";
      if(pPrev == -1 && p != -1) msg += "売り決済 ";
      if(p == 1  && pPrev != 1)  msg += "買いエントリー ";
      if(p == -1 && pPrev != -1) msg += "売りエントリー ";
     }
   if(InpAlertB)
     {
      int bd = (int)BufBDir[b], bdPrev = (int)BufBDir[b - 1];
      if(bd == 1  && bdPrev == -1) msg += "パターンB↑ ";
      if(bd == -1 && bdPrev == 1)  msg += "パターンB↓ ";
     }
   if(msg == "")
      return;

   string tf = EnumToString(_Period);
   StringReplace(tf, "PERIOD_", "");
   string text = StringFormat("%s %s MAMA相互監視: %s", _Symbol, tf, msg);

   if(InpAlertPopup) Alert(text);
   if(InpAlertSound) PlaySound("alert.wav");
   if(InpAlertPush)  SendNotification(text);
   if(InpAlertMail)  SendMail("MAMA SelfCross " + _Symbol, text);
  }

//+------------------------------------------------------------------+
//| 状態パネル                                                         |
//+------------------------------------------------------------------+
string DirText(const int d)
  {
   if(d == 1)  return("▲ 上");
   if(d == -1) return("▼ 下");
   return("―");
  }

color DirColor(const int d)
  {
   if(d == 1)  return(clrAqua);
   if(d == -1) return(clrRed);
   return(clrGray);
  }

void PanelLine(const int idx, const string text, const color clr)
  {
   string name = PANEL_PREFIX + IntegerToString(idx);
   if(ObjectFind(0, name) < 0)
     {
      ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
      ENUM_ANCHOR_POINT anchor = ANCHOR_LEFT_UPPER;
      if(InpPanelCorner == CORNER_RIGHT_UPPER) anchor = ANCHOR_RIGHT_UPPER;
      if(InpPanelCorner == CORNER_LEFT_LOWER)  anchor = ANCHOR_LEFT_LOWER;
      if(InpPanelCorner == CORNER_RIGHT_LOWER) anchor = ANCHOR_RIGHT_LOWER;
      bool lower = (InpPanelCorner == CORNER_LEFT_LOWER || InpPanelCorner == CORNER_RIGHT_LOWER);
      int  lineH = (int)MathRound(InpPanelFontSize * 1.9);
      int  row   = lower ? (PANEL_LINES - 1 - idx) : idx;

      ObjectSetInteger(0, name, OBJPROP_CORNER,     InpPanelCorner);
      ObjectSetInteger(0, name, OBJPROP_ANCHOR,     anchor);
      ObjectSetInteger(0, name, OBJPROP_XDISTANCE,  10);
      ObjectSetInteger(0, name, OBJPROP_YDISTANCE,  20 + row * lineH);
      ObjectSetInteger(0, name, OBJPROP_FONTSIZE,   InpPanelFontSize);
      ObjectSetString(0,  name, OBJPROP_FONT,       InpPanelFont);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN,     true);
      ObjectSetInteger(0, name, OBJPROP_BACK,       false);
     }
   ObjectSetString(0,  name, OBJPROP_TEXT,  text);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
  }

void UpdatePanel(const int last, const double &close[])
  {
   if(last < 1)
      return;

   int fd  = (int)BufFastDir[last];
   int sd  = (int)BufSlowDir[last];
   int pos = (int)BufPos[last];
   int align = (fd == sd) ? fd : 0;

   string alignTxt = "不一致（待ち）";
   if(align == 1)  alignTxt = "買い方向で一致";
   if(align == -1) alignTxt = "売り方向で一致";

   int    trendDir = 0;
   string trendTxt = "―";
   double t0 = (InpTrendPeriod > 0) ? BufTrendMA[last] : EMPTY_VALUE;
   double t1 = (InpTrendPeriod > 0) ? BufTrendMA[last - 1] : EMPTY_VALUE;
   if(t0 != EMPTY_VALUE && t1 != EMPTY_VALUE)
     {
      if(InpTrendFilter == TREND_SLOPE)
        {
         trendDir = (t0 > t1) ? 1 : (t0 < t1) ? -1 : 0;
         trendTxt = (trendDir == 1) ? "MA 上向き" : (trendDir == -1) ? "MA 下向き" : "―";
        }
      else
        {
         trendDir = (close[last] > t0) ? 1 : (close[last] < t0) ? -1 : 0;
         trendTxt = (trendDir == 1) ? "価格 > MA" : (trendDir == -1) ? "価格 < MA" : "―";
        }
     }

   string posTxt = "ノーポジ";
   color  posClr = clrGray;
   if(pos == 1)  { posTxt = "買い保有中"; posClr = clrDodgerBlue; }
   if(pos == -1) { posTxt = "売り保有中"; posClr = clrOrangeRed;  }

   PanelLine(0, StringFormat("MAMA %d / %d", InpFastPeriod, InpSlowPeriod), clrWhite);
   PanelLine(1, StringFormat("小(%d)    : %s", InpFastPeriod, DirText(fd)), DirColor(fd));
   PanelLine(2, StringFormat("大(%d)    : %s", InpSlowPeriod, DirText(sd)), DirColor(sd));
   PanelLine(3, "相互監視 : " + alignTxt, DirColor(align));
   PanelLine(4, StringFormat("トレンド(%d): %s", InpTrendPeriod, trendTxt), DirColor(trendDir));
   PanelLine(5, "ポジション: " + posTxt, posClr);
  }

//+------------------------------------------------------------------+
//| ローソク足を背景色にして隠す／元に戻す                                  |
//+------------------------------------------------------------------+
ENUM_CHART_PROPERTY_INTEGER CandleColorProp(const int k)
  {
   switch(k)
     {
      case 0:  return(CHART_COLOR_CHART_UP);
      case 1:  return(CHART_COLOR_CHART_DOWN);
      case 2:  return(CHART_COLOR_CANDLE_BULL);
      case 3:  return(CHART_COLOR_CANDLE_BEAR);
      default: return(CHART_COLOR_CHART_LINE);
     }
  }

void HideCandles()
  {
   long bg = ChartGetInteger(0, CHART_COLOR_BACKGROUND);
   for(int k = 0; k < 5; k++)
     {
      g_savedColors[k] = ChartGetInteger(0, CandleColorProp(k));
      ChartSetInteger(0, CandleColorProp(k), bg);
     }
   g_colorsSaved = true;
   ChartRedraw();
  }

void RestoreCandles()
  {
   if(!g_colorsSaved)
      return;
   for(int k = 0; k < 5; k++)
      ChartSetInteger(0, CandleColorProp(k), g_savedColors[k]);
   g_colorsSaved = false;
  }
//+------------------------------------------------------------------+
