# CTO — レイテンシー非依存エッジの検証基盤

Binance USDT-M 無期限先物の公開データ（data.binance.vision）を使い、
「価格以外の情報」と「構造的フロー」由来のエッジを、遅延テスト込みで検証する。

## 使い方

```bash
pip install -r requirements.txt
python scripts/download_data.py      # data/parquet に保存（data.binance.vision への接続が必要）
python scripts/run_backtests.py      # results/summary.json, results/equity.csv
python -m pytest -q tests            # エンジンの単体テスト（合成データ）
```

## 事前登録した仮説（パラメータは結果を見る前に固定）

| ID | 仮説 | 時間軸 | 使うデータ |
|---|---|---|---|
| S1 | 8時間ごとに funding 上位を売り・下位を買い（市場中立）。混雑の巻き戻し＋funding受取 | 8h | funding |
| S2 | z(24h funding)+z(OI変化) が極端なら逆張り、48h保有 | 1h〜2日 | funding, OI |
| S3 | 1h で OI 急減＋価格急変＝清算連鎖の代理指標。逆張りで4h保有 | 5分〜4h | OI(5分), 価格 |
| S4 | 複数銘柄の時系列トレンド（20/60/120日）、逆ボラ加重。価格のみの対照群 | 日 | 価格（＋funding フィルター版） |
| S5 | 1分足の急変（5σ・出来高5倍）後に動きが継続するか（Toku氏の「期待値②」） | 1〜60分 | 1分足 |
| S6 | funding が高い間だけ現物買い・先物売りのデルタニュートラル・キャリー | 週 | 現物・先物・funding |

## 検証ルール

- 期間分割: IS 2022-01〜2024-12（設計・グリッド）／OOS 2025-01〜2026-09（一度だけ評価）
- 遅延テスト: 約定を 0/5分/15分/1h/4h 遅らせてシャープの残存率を見る
- コスト: taker 5bp + スリッページ（BTC/ETH 1bp、他 3bp）、現物 taker 10bp。2倍ストレスも実施
- funding は保有ポジションに精算時刻で反映（決済直後・建てた瞬間の精算は払わない）
- グリッドの全点を試行回数として数え、Deflated Sharpe Ratio を算出
- 既知のバイアス: 銘柄は「今も上場している大型銘柄」なので生存バイアスで有利側に偏る

## 構成

```
bt/data.py        ダウンロード（SHA256検証）とparquet化、ローダー
bt/engine.py      約定遅延・コスト・funding込みのベクトル化バックテスター
bt/events.py      イベントスタディ（マークアウト、日次クラスタ t 値）
bt/metrics.py     Sharpe, MaxDD, PSR, Deflated Sharpe
bt/config.py      ユニバース、期間、コスト
strategies/core.py 仮説 S1〜S6 と IS グリッド
scripts/          ダウンロードと一括実行
tests/            合成データでのエンジン検証（先読み検出など）
```
