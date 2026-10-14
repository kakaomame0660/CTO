//+------------------------------------------------------------------+
//|                                            MAMA_SelfCross_EA.mq5 |
//|      MAMA（MAのMA）自己相関クロス ＆ 相互監視 — 検証用 EA          |
//+------------------------------------------------------------------+
//  TradingView のストラテジー（MAMA_SelfCross_Strategy.pine）と同じ売買ルールの EA。
//  MT5 のストラテジーテスターで「リアルティック」を使い、実際のスプレッドで検証するためのもの。
//
//  ・足が確定したら判定し、次の足の始値（新しい足の最初のティック）で成行注文
//  ・損切りはポジションの SL として置き、トレーリング・建値ストップは足が確定するごとに更新
//  ・手法    : 相互監視（自己相関クロス） / パターンB（短期MAMA × 長期MA） / パターンC（短期MA × 長期MA）
//  ・安全のため、初期設定ではストラテジーテスターとデモ口座でしか発注しない
//    （本番口座・口座の種類が確認できないときは、起動しない／注文を出さない）
//  ・チャートに付けると、その口座で実際に注文を出す。バックテストはストラテジーテスターで行う
//  ・最適化の基準「カスタム最大」は「純利益 ÷ 最大ドローダウン（有効証拠金）」
//  ※ MAMA = 「MA の MA」。Ehlers の MESA Adaptive Moving Average とは別物
//+------------------------------------------------------------------+
#property copyright   "MAMA SelfCross"
#property version     "1.01"
#property description "MAMA（MAのMA）自己相関クロス ＆ 相互監視 — 検証用 EA"
#property description "初期設定ではストラテジーテスターとデモ口座でしか発注しません"
#property description "バックテストはチャートに付けず、ストラテジーテスターで行ってください"

#include <Trade/Trade.mqh>

//+------------------------------------------------------------------+
//| 列挙型                                                            |
//+------------------------------------------------------------------+
enum ENUM_MAMA_METHOD
  {
   METHOD_MUTUAL = 0, // 相互監視（自己相関クロス）
   METHOD_B      = 1, // パターンB（短期MAMA × 長期MA）
   METHOD_C      = 2  // パターンC（短期MA × 長期MA）
  };

enum ENUM_MAMA_DIRECTION
  {
   DIR_BOTH  = 0, // 両方
   DIR_LONG  = 1, // 買いのみ
   DIR_SHORT = 2  // 売りのみ
  };

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

enum ENUM_SL_MODE
  {
   SL_NONE  = 0, // なし（逆クロスのみ）
   SL_SWING = 1, // 直近の安値・高値
   SL_ATR   = 2  // ATR 倍
  };

enum ENUM_TRAIL_MODE
  {
   TRAIL_NONE  = 0, // なし
   TRAIL_ATR   = 1, // ATR（最高値から ATR × n）
   TRAIL_SWING = 2, // 直近 N 本の安値・高値
   TRAIL_MA    = 3, // 移動平均線
   TRAIL_PRICE = 4  // 値幅（最高値から一定の値幅）
  };

enum ENUM_TRAIL_LINE
  {
   LINE_FAST     = 0, // 短期MA
   LINE_FASTMAMA = 1, // 短期MAMA
   LINE_SLOW     = 2, // 長期MA
   LINE_SLOWMAMA = 3  // 長期MAMA
  };

//+------------------------------------------------------------------+
//| 入力                                                              |
//+------------------------------------------------------------------+
input group "■ 基本"
input ENUM_TIMEFRAMES     InpTF            = PERIOD_CURRENT; // 時間足（PERIOD_CURRENT = チャートの時間足）
input double              InpLots          = 0.01;           // ロット数
input long                InpMagic         = 20261014;       // マジックナンバー
input int                 InpDeviation     = 30;             // 許容スリッページ（ポイント）
input int                 InpMaxSpread     = 0;              // 最大スプレッド（ポイント、0 = 制限なし）。超えていたら新規エントリーしない
input bool                InpAllowReal     = false;          // 本番口座での発注を許可（危険。バックテスト・デモ口座では false のまま）

input group "■ 手法"
input ENUM_MAMA_METHOD    InpMethod        = METHOD_MUTUAL;  // 手法
input ENUM_MAMA_DIRECTION InpDirection     = DIR_BOTH;       // 売買方向
input ENUM_ENTRY_MODE     InpEntryMode     = ENTRY_BOTH;     // エントリー方式（相互監視）
input ENUM_EXIT_MODE      InpExitMode      = EXIT_AUTO;      // 決済条件（相互監視）
input ENUM_TREND_FILTER   InpTrendFilter   = TREND_OFF;      // トレンドフィルター
input int                 InpTrendPeriod   = 200;            // トレンドMA の期間

input group "■ 移動平均"
input int                 InpFastPeriod    = 5;              // 短期の期間（小矢印）
input int                 InpSlowPeriod    = 20;             // 長期の期間（大矢印）
input ENUM_MA_METHOD      InpMAMethod      = MODE_SMA;       // MA の種類
input ENUM_MA_METHOD      InpMAMAMethod    = MODE_SMA;       // MAMA（MAのMA）の種類
input ENUM_APPLIED_PRICE  InpPrice         = PRICE_CLOSE;    // 適用価格

input group "■ 損切り・利確"
input ENUM_SL_MODE        InpSLMode        = SL_SWING;       // 損切り
input int                 InpSwingBars     = 10;             // 直近 何本の安値・高値
input double              InpSLBuffer      = 0.0;            // 損切りの余裕（価格。金なら 0.3 = 0.3 ドル）
input double              InpSLAtr         = 2.0;            // 損切り（ATR 倍）※ATR 倍のとき
input double              InpTPAtr         = 0.0;            // 利確（ATR 倍、0 = なし）
input int                 InpAtrPeriod     = 14;             // ATR の期間

input group "■ トレーリングストップ・建値ストップ"
input ENUM_TRAIL_MODE     InpTrailMode     = TRAIL_NONE;     // トレーリング方式
input double              InpTrailStart    = 1.0;            // 開始：含み益が ATR × いくつで（0 = すぐ）
input double              InpTrailAtr      = 2.0;            // ATR 方式の幅（ATR × n）
input int                 InpTrailBars     = 5;              // 直近安値・高値方式の本数
input ENUM_TRAIL_LINE     InpTrailLine     = LINE_SLOW;      // 移動平均線方式で使う線
input double              InpTrailPrice    = 5.0;            // 値幅方式の幅（価格。金なら 5 = 5 ドル）
input bool                InpIgnoreCross   = false;          // トレーリング開始後は逆クロスで決済しない
input double              InpBETrigger     = 0.0;            // 建値ストップ：含み益が ATR × いくつで（0 = 使わない）
input double              InpBEOffset      = 0.0;            // 建値ストップの上乗せ（価格）

input group "■ 最適化"
input int                 InpMinTrades     = 30;             // 最適化で評価する最低取引回数（これ未満は 0 点）

//+------------------------------------------------------------------+
//| 定数・グローバル変数                                                |
//+------------------------------------------------------------------+
#define LOOKBACK 60   // 向きを判定するために読む本数

struct Signals
  {
   bool   fUp;
   bool   fDn;
   bool   sUp;
   bool   sDn;
   bool   xUp;
   bool   xDn;
   int    fd;
   int    sd;
   double close1;
   double high1;
   double low1;
   double atr;
   double trend1;
   double trend2;
   double fma1;
   double fmm1;
   double sma1;
   double smm1;
   double swLo;
   double swHi;
   double trLo;
   double trHi;
  };

CTrade          g_trade;
ENUM_TIMEFRAMES g_tf;
int             g_hFast     = INVALID_HANDLE;
int             g_hFastMama = INVALID_HANDLE;
int             g_hSlow     = INVALID_HANDLE;
int             g_hSlowMama = INVALID_HANDLE;
int             g_hTrend    = INVALID_HANDLE;
datetime        g_lastBar   = 0;

//--- 保有中のポジションの状態（0.0 = 未設定）
bool   g_state    = false;
int    g_kind     = 0;      // 1 = 大矢印で建てた、2 = 小矢印で建てた（決済条件「自動」用）
double g_initStop = 0.0;    // 最初の損切り
double g_entryAtr = 0.0;    // エントリー時の ATR
double g_peak     = 0.0;    // 建玉後の最高値（売りは最安値）
double g_trail    = 0.0;    // トレール価格
bool   g_trailOn  = false;
bool   g_beOn     = false;

//+------------------------------------------------------------------+
//| 初期化                                                             |
//+------------------------------------------------------------------+
int OnInit()
  {
   if(InpFastPeriod < 1 || InpSlowPeriod < 1 || InpTrendPeriod < 1 || InpSwingBars < 1 || InpTrailBars < 1 || InpAtrPeriod < 1 || InpLots <= 0)
     {
      Print("MAMA SelfCross EA: 設定値が不正です");
      return(INIT_PARAMETERS_INCORRECT);
     }

   if(!TradingPermitted())
     {
      Alert("MAMA SelfCross EA: 本番口座（またはデモ口座と確認できない口座）なので停止しました。" +
            "バックテストはチャートに付けず、ストラテジーテスター（Ctrl+R）で行ってください。");
      return(INIT_FAILED);
     }

   g_tf = (InpTF == PERIOD_CURRENT) ? (ENUM_TIMEFRAMES)_Period : InpTF;

   //--- MAMA は「MA を元にした MA」。iMA の適用価格に元の MA のハンドルを渡す
   g_hFast     = iMA(_Symbol, g_tf, InpFastPeriod, 0, InpMAMethod, InpPrice);
   g_hSlow     = iMA(_Symbol, g_tf, InpSlowPeriod, 0, InpMAMethod, InpPrice);
   g_hTrend    = iMA(_Symbol, g_tf, InpTrendPeriod, 0, InpMAMethod, InpPrice);
   if(g_hFast == INVALID_HANDLE || g_hSlow == INVALID_HANDLE || g_hTrend == INVALID_HANDLE)
     {
      Print("MAMA SelfCross EA: 移動平均を作れませんでした");
      return(INIT_FAILED);
     }
   g_hFastMama = iMA(_Symbol, g_tf, InpFastPeriod, 0, InpMAMAMethod, (ENUM_APPLIED_PRICE)g_hFast);
   g_hSlowMama = iMA(_Symbol, g_tf, InpSlowPeriod, 0, InpMAMAMethod, (ENUM_APPLIED_PRICE)g_hSlow);
   if(g_hFastMama == INVALID_HANDLE || g_hSlowMama == INVALID_HANDLE)
     {
      Print("MAMA SelfCross EA: MAMA を作れませんでした");
      return(INIT_FAILED);
     }

   g_trade.SetExpertMagicNumber((ulong)InpMagic);
   g_trade.SetDeviationInPoints((ulong)InpDeviation);
   g_trade.SetTypeFillingBySymbol(_Symbol);

   //--- 起動した足では判定しない（足の途中から入らないように）
   g_lastBar = iTime(_Symbol, g_tf, 0);
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   if(g_hFast != INVALID_HANDLE)     IndicatorRelease(g_hFast);
   if(g_hFastMama != INVALID_HANDLE) IndicatorRelease(g_hFastMama);
   if(g_hSlow != INVALID_HANDLE)     IndicatorRelease(g_hSlow);
   if(g_hSlowMama != INVALID_HANDLE) IndicatorRelease(g_hSlowMama);
   if(g_hTrend != INVALID_HANDLE)    IndicatorRelease(g_hTrend);
  }

//+------------------------------------------------------------------+
//| ティックごと：新しい足ができたときだけ判定する                          |
//+------------------------------------------------------------------+
void OnTick()
  {
   datetime t = iTime(_Symbol, g_tf, 0);
   if(t == 0 || t == g_lastBar)
      return;
   if(g_lastBar == 0)
     {
      g_lastBar = t;     // 起動して最初に見た足では判定しない（足の途中から入らないように）
      return;
     }
   if(!ProcessBar())
      return;            // データがまだ揃っていなければ次のティックでやり直す
   g_lastBar = t;
  }

//+------------------------------------------------------------------+
//| 直前の確定足で判定して注文する                                        |
//+------------------------------------------------------------------+
bool ProcessBar()
  {
   Signals s;
   if(!ReadSignals(s))
      return(false);

   int    pos = 0;
   double avg = 0.0, curSL = 0.0, curTP = 0.0;
   ulong  ticket = 0;
   GetPosition(pos, avg, curSL, curTP, ticket);

   if(pos == 0)
      g_state = false;
   else if(!g_state)
      RecoverState(curSL, s);

   //--- 1) 保有中：最高値（売りは最安値）を更新し、建値ストップとトレーリングを判定
   if(pos != 0)
      UpdateTrail(pos, avg, s);

   //--- 2) シグナル
   bool isX = (InpMethod != METHOD_MUTUAL);
   bool uS  = (InpEntryMode != ENTRY_FINE);
   bool uF  = (InpEntryMode != ENTRY_BIG);
   bool lbs = s.sUp && s.fd == 1;     // 小→大（大矢印で入る）
   bool lbf = s.fUp && s.sd == 1;     // 大→小（小矢印で入る）
   bool sbs = s.sDn && s.fd == -1;
   bool sbf = s.fDn && s.sd == -1;

   bool trendUp = true, trendDn = true;
   if(InpTrendFilter == TREND_PRICE)
     {
      trendUp = s.close1 > s.trend1;
      trendDn = s.close1 < s.trend1;
     }
   else if(InpTrendFilter == TREND_SLOPE)
     {
      trendUp = s.trend1 > s.trend2;
      trendDn = s.trend1 < s.trend2;
     }

   bool longTrig  = (isX ? s.xUp : ((uS && lbs) || (uF && lbf))) && trendUp;
   bool shortTrig = (isX ? s.xDn : ((uS && sbs) || (uF && sbf))) && trendDn;
   bool exitL     = isX ? s.xDn : ExitHit(s.fDn, s.sDn);
   bool exitS     = isX ? s.xUp : ExitHit(s.fUp, s.sUp);

   bool doLong  = InpDirection != DIR_SHORT && longTrig && pos != 1;
   bool doShort = InpDirection != DIR_LONG && shortTrig && pos != -1;
   bool doExitL = pos == 1 && exitL && !(InpIgnoreCross && g_trailOn);
   bool doExitS = pos == -1 && exitS && !(InpIgnoreCross && g_trailOn);

   //--- 3) 決済 → 新規（反対方向のサインはドテン）
   if((doExitL && !doShort) || (doExitS && !doLong))
     {
      ClosePosition(ticket);
      pos = 0;
     }
   if(doLong || doShort)
     {
      if(pos != 0)
        {
         ClosePosition(ticket);
         pos = 0;
        }
      int  dir    = doLong ? 1 : -1;
      bool bySlow = !isX && uS && (doLong ? lbs : sbs);
      if(SpreadOk())
         OpenPosition(dir, bySlow, s);
      else
         Print("MAMA SelfCross EA: スプレッドが広いのでエントリーを見送りました");
      return(true);
     }

   //--- 4) 保有を続けるなら損切りを更新
   if(pos != 0)
      ManageStop(pos, avg, curSL, curTP, ticket);
   return(true);
  }

//+------------------------------------------------------------------+
//| 確定足（1 本前）の値を読む                                           |
//+------------------------------------------------------------------+
bool ReadSignals(Signals &s)
  {
   double fma[], fmm[], sma[], smm[], tma[];
   ArraySetAsSeries(fma, true);
   ArraySetAsSeries(fmm, true);
   ArraySetAsSeries(sma, true);
   ArraySetAsSeries(smm, true);
   ArraySetAsSeries(tma, true);
   if(CopyBuffer(g_hFast, 0, 1, LOOKBACK, fma) != LOOKBACK)     return(false);
   if(CopyBuffer(g_hFastMama, 0, 1, LOOKBACK, fmm) != LOOKBACK) return(false);
   if(CopyBuffer(g_hSlow, 0, 1, LOOKBACK, sma) != LOOKBACK)     return(false);
   if(CopyBuffer(g_hSlowMama, 0, 1, LOOKBACK, smm) != LOOKBACK) return(false);
   if(CopyBuffer(g_hTrend, 0, 1, 2, tma) != 2)                  return(false);

   int fd0, fd1, sd0, sd1, x0, x1;
   Dirs(fma, fmm, fd0, fd1);
   Dirs(sma, smm, sd0, sd1);
   if(InpMethod == METHOD_B)
      Dirs(fmm, sma, x0, x1);
   else
      Dirs(fma, sma, x0, x1);

   s.fd  = fd0;
   s.sd  = sd0;
   s.fUp = (fd0 == 1 && fd1 == -1);
   s.fDn = (fd0 == -1 && fd1 == 1);
   s.sUp = (sd0 == 1 && sd1 == -1);
   s.sDn = (sd0 == -1 && sd1 == 1);
   s.xUp = (x0 == 1 && x1 == -1);
   s.xDn = (x0 == -1 && x1 == 1);

   MqlRates r[];
   ArraySetAsSeries(r, true);
   if(CopyRates(_Symbol, g_tf, 1, 1, r) != 1)
      return(false);
   s.close1 = r[0].close;
   s.high1  = r[0].high;
   s.low1   = r[0].low;

   s.atr = AtrRma(InpAtrPeriod);
   if(s.atr <= 0.0)
      return(false);

   s.trend1 = tma[0];
   s.trend2 = tma[1];
   s.fma1   = fma[0];
   s.fmm1   = fmm[0];
   s.sma1   = sma[0];
   s.smm1   = smm[0];

   int iLo = iLowest(_Symbol, g_tf, MODE_LOW, InpSwingBars, 1);
   int iHi = iHighest(_Symbol, g_tf, MODE_HIGH, InpSwingBars, 1);
   int tLo = iLowest(_Symbol, g_tf, MODE_LOW, InpTrailBars, 1);
   int tHi = iHighest(_Symbol, g_tf, MODE_HIGH, InpTrailBars, 1);
   if(iLo < 0 || iHi < 0 || tLo < 0 || tHi < 0)
      return(false);
   s.swLo = iLow(_Symbol, g_tf, iLo);
   s.swHi = iHigh(_Symbol, g_tf, iHi);
   s.trLo = iLow(_Symbol, g_tf, tLo);
   s.trHi = iHigh(_Symbol, g_tf, tHi);
   return(true);
  }

//+------------------------------------------------------------------+
//| a と b の上下関係を古い足から順にたどる（同値なら直前の向きを引き継ぐ） |
//| d0 = 1 本前の足の向き、d1 = 2 本前の足の向き                          |
//+------------------------------------------------------------------+
void Dirs(const double &a[], const double &b[], int &d0, int &d1)
  {
   int prev = 0;
   d0 = 0;
   d1 = 0;
   for(int i = LOOKBACK - 1; i >= 0; i--)
     {
      int d = prev;
      if(a[i] != EMPTY_VALUE && b[i] != EMPTY_VALUE)
        {
         if(a[i] > b[i])
            d = 1;
         else if(a[i] < b[i])
            d = -1;
        }
      if(i == 1)
         d1 = d;
      if(i == 0)
         d0 = d;
      prev = d;
     }
  }

//+------------------------------------------------------------------+
//| ATR（TradingView と同じ RMA 方式）                                   |
//+------------------------------------------------------------------+
double AtrRma(const int period)
  {
   MqlRates r[];
   ArraySetAsSeries(r, false);             // 0 = 古い足
   int need = period * 10 + 1;
   int got  = CopyRates(_Symbol, g_tf, 1, need, r);
   if(got < period + 1)
      return(0.0);
   double atr = 0.0, sum = 0.0;
   int    cnt = 0;
   for(int i = 1; i < got; i++)
     {
      double tr = MathMax(r[i].high, r[i - 1].close) - MathMin(r[i].low, r[i - 1].close);
      if(cnt < period)
        {
         sum += tr;
         cnt++;
         if(cnt == period)
            atr = sum / period;
        }
      else
         atr = (atr * (period - 1) + tr) / period;
     }
   return(atr);
  }

//+------------------------------------------------------------------+
//| この EA のポジション                                                 |
//+------------------------------------------------------------------+
bool GetPosition(int &dir, double &openPrice, double &sl, double &tp, ulong &ticket)
  {
   dir = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong tk = PositionGetTicket(i);
      if(tk == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol)
         continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic)
         continue;
      dir       = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? 1 : -1;
      openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
      sl        = PositionGetDouble(POSITION_SL);
      tp        = PositionGetDouble(POSITION_TP);
      ticket    = tk;
      return(true);
     }
   return(false);
  }

//--- EA を再起動したときなど、状態がないポジションを引き継ぐ
void RecoverState(const double curSL, const Signals &s)
  {
   g_state    = true;
   g_kind     = 2;
   g_initStop = curSL;
   g_entryAtr = s.atr;
   g_peak     = 0.0;
   g_trail    = 0.0;
   g_trailOn  = false;
   g_beOn     = false;
  }

//+------------------------------------------------------------------+
//| 決済条件（相互監視）                                                 |
//| fastRev / slowRev = 保有方向と逆向きのクロスが出たか                    |
//+------------------------------------------------------------------+
bool ExitHit(const bool fastRev, const bool slowRev)
  {
   switch(InpExitMode)
     {
      case EXIT_SLOW: return(slowRev);
      case EXIT_FAST: return(fastRev);
      case EXIT_AUTO: return(g_kind == 1 ? slowRev : (fastRev || slowRev));
      default:        return(fastRev || slowRev);
     }
  }

//+------------------------------------------------------------------+
//| トレーリング・建値ストップの判定（足が確定するごと）                      |
//+------------------------------------------------------------------+
void UpdateTrail(const int pos, const double avg, const Signals &s)
  {
   double gain;
   if(pos == 1)
     {
      g_peak = (g_peak == 0.0) ? s.high1 : MathMax(g_peak, s.high1);
      gain   = g_peak - avg;
     }
   else
     {
      g_peak = (g_peak == 0.0) ? s.low1 : MathMin(g_peak, s.low1);
      gain   = avg - g_peak;
     }
   if(InpBETrigger > 0.0 && !g_beOn && gain >= InpBETrigger * g_entryAtr)
      g_beOn = true;
   if(InpTrailMode != TRAIL_NONE && !g_trailOn && (InpTrailStart == 0.0 || gain >= InpTrailStart * g_entryAtr))
      g_trailOn = true;
   if(!g_trailOn)
      return;

   double cand = 0.0;
   switch(InpTrailMode)
     {
      case TRAIL_ATR:   cand = (pos == 1) ? g_peak - InpTrailAtr * s.atr : g_peak + InpTrailAtr * s.atr; break;
      case TRAIL_SWING: cand = (pos == 1) ? s.trLo : s.trHi; break;
      case TRAIL_MA:    cand = TrailLineValue(s); break;
      case TRAIL_PRICE: cand = (pos == 1) ? g_peak - InpTrailPrice : g_peak + InpTrailPrice; break;
      default:          cand = 0.0;
     }
   if(cand <= 0.0 || cand == EMPTY_VALUE)
      return;
   if(g_trail == 0.0)
      g_trail = cand;
   else
      g_trail = (pos == 1) ? MathMax(g_trail, cand) : MathMin(g_trail, cand);
  }

double TrailLineValue(const Signals &s)
  {
   switch(InpTrailLine)
     {
      case LINE_FAST:     return(s.fma1);
      case LINE_FASTMAMA: return(s.fmm1);
      case LINE_SLOWMAMA: return(s.smm1);
      default:            return(s.sma1);
     }
  }

//+------------------------------------------------------------------+
//| 新規エントリー                                                       |
//+------------------------------------------------------------------+
void OpenPosition(const int dir, const bool bySlow, const Signals &s)
  {
   double sl = 0.0, tp = 0.0;
   if(InpSLMode == SL_SWING)
      sl = (dir == 1) ? s.swLo - InpSLBuffer : s.swHi + InpSLBuffer;
   else if(InpSLMode == SL_ATR)
      sl = (dir == 1) ? s.close1 - InpSLAtr * s.atr : s.close1 + InpSLAtr * s.atr;
   if(InpTPAtr > 0.0)
      tp = (dir == 1) ? s.close1 + InpTPAtr * s.atr : s.close1 - InpTPAtr * s.atr;

   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick))
      return;
   double minDist = (double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point;

   if(dir == 1)
     {
      if(sl > 0.0 && sl >= tick.bid)
        {
         Print("MAMA SelfCross EA: 始値がすでに損切りを割っているので買いを見送りました");
         return;
        }
      if(sl > 0.0 && sl > tick.bid - minDist)
         sl = tick.bid - minDist;
      if(tp > 0.0 && tp < tick.ask + minDist)
         tp = 0.0;
     }
   else
     {
      if(sl > 0.0 && sl <= tick.ask)
        {
         Print("MAMA SelfCross EA: 始値がすでに損切りを超えているので売りを見送りました");
         return;
        }
      if(sl > 0.0 && sl < tick.ask + minDist)
         sl = tick.ask + minDist;
      if(tp > 0.0 && tp > tick.bid - minDist)
         tp = 0.0;
     }
   sl = (sl > 0.0) ? NormalizeDouble(sl, _Digits) : 0.0;
   tp = (tp > 0.0) ? NormalizeDouble(tp, _Digits) : 0.0;

   if(!TradingPermitted())
      return;
   double lots = NormalizeLots(InpLots);
   bool   ok   = (dir == 1) ? g_trade.Buy(lots, _Symbol, 0.0, sl, tp, "MAMA L")
                             : g_trade.Sell(lots, _Symbol, 0.0, sl, tp, "MAMA S");
   uint   rc   = g_trade.ResultRetcode();
   if(!ok || (rc != TRADE_RETCODE_DONE && rc != TRADE_RETCODE_PLACED))
     {
      Print("MAMA SelfCross EA: 注文できませんでした（", rc, " ", g_trade.ResultRetcodeDescription(), "）");
      return;
     }
   g_state    = true;
   g_kind     = bySlow ? 1 : 2;
   g_initStop = sl;
   g_entryAtr = s.atr;
   g_peak     = 0.0;
   g_trail    = 0.0;
   g_trailOn  = false;
   g_beOn     = false;
  }

//+------------------------------------------------------------------+
//| 損切りの更新：最初の損切り・建値ストップ・トレールのうち一番有利なもの     |
//+------------------------------------------------------------------+
void ManageStop(const int pos, const double avg, const double curSL, const double curTP, const ulong ticket)
  {
   double eff = g_initStop;
   if(g_beOn)
     {
      double be = avg + pos * InpBEOffset;
      eff = (eff == 0.0) ? be : ((pos == 1) ? MathMax(eff, be) : MathMin(eff, be));
     }
   if(g_trailOn && g_trail > 0.0)
      eff = (eff == 0.0) ? g_trail : ((pos == 1) ? MathMax(eff, g_trail) : MathMin(eff, g_trail));
   if(eff <= 0.0)
      return;
   eff = NormalizeDouble(eff, _Digits);

   //--- 不利な方向へは動かさない
   if(curSL > 0.0 && ((pos == 1 && eff <= curSL) || (pos == -1 && eff >= curSL)))
      return;

   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick))
      return;
   double minDist = (double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point;
   if(pos == 1)
     {
      if(eff >= tick.bid)          // すでに損切りラインを割っている → 今の価格で決済
        {
         ClosePosition(ticket);
         return;
        }
      if(eff > tick.bid - minDist)
         eff = NormalizeDouble(tick.bid - minDist, _Digits);
     }
   else
     {
      if(eff <= tick.ask)
        {
         ClosePosition(ticket);
         return;
        }
      if(eff < tick.ask + minDist)
         eff = NormalizeDouble(tick.ask + minDist, _Digits);
     }
   if(curSL > 0.0 && ((pos == 1 && eff <= curSL) || (pos == -1 && eff >= curSL)))
      return;
   if(!TradingPermitted())
      return;
   if(!g_trade.PositionModify(ticket, eff, curTP))
      Print("MAMA SelfCross EA: 損切りを更新できませんでした（", g_trade.ResultRetcode(), "）");
  }

//+------------------------------------------------------------------+
//| 補助                                                               |
//+------------------------------------------------------------------+
void ClosePosition(const ulong ticket)
  {
   if(ticket == 0 || !TradingPermitted())
      return;
   if(!g_trade.PositionClose(ticket, (ulong)InpDeviation))
      Print("MAMA SelfCross EA: 決済できませんでした（", g_trade.ResultRetcode(), "）");
   g_state = false;
  }

//--- 発注してよいか：ストラテジーテスター、デモ口座と確認できた口座、または本番を明示的に許可したとき
bool TradingPermitted()
  {
   if(MQLInfoInteger(MQL_TESTER) != 0 || MQLInfoInteger(MQL_OPTIMIZATION) != 0)
      return(true);
   if(InpAllowReal)
      return(true);
   if(AccountInfoInteger(ACCOUNT_LOGIN) <= 0)
      return(false);                                    // 口座に接続していない＝種類が分からない
   ResetLastError();
   long mode = AccountInfoInteger(ACCOUNT_TRADE_MODE);
   if(GetLastError() != 0)
      return(false);
   return(mode == ACCOUNT_TRADE_MODE_DEMO);
  }

bool SpreadOk()
  {
   if(InpMaxSpread <= 0)
      return(true);
   return(SymbolInfoInteger(_Symbol, SYMBOL_SPREAD) <= InpMaxSpread);
  }

double NormalizeLots(const double lots)
  {
   double minLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double stepLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double v = lots;
   if(stepLot > 0.0)
      v = MathFloor(v / stepLot + 1e-9) * stepLot;
   v = MathMax(minLot, MathMin(maxLot, v));
   return(NormalizeDouble(v, 2));
  }

//+------------------------------------------------------------------+
//| 最適化の基準（カスタム最大）：純利益 ÷ 最大ドローダウン                   |
//+------------------------------------------------------------------+
double OnTester()
  {
   double trades = TesterStatistics(STAT_TRADES);
   if(trades < InpMinTrades)
      return(0.0);
   double profit = TesterStatistics(STAT_PROFIT);
   double dd     = TesterStatistics(STAT_EQUITY_DD);
   if(dd <= 0.0)
      return(profit);
   return(profit / dd);
  }
//+------------------------------------------------------------------+
