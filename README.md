# CTO

## The Agency（専門サブエージェント集）

[msitarzewski/agency-agents](https://github.com/msitarzewski/agency-agents) の 282 体の専門エージェントを
`.claude/agents/` に導入済みです。このリポジトリで Claude Code を開けば（ローカル・Web・クラウドどこでも）
追加の設定なしで使えます。

### 使い方

普通に頼むだけで、Claude がタスクに合うエージェントを選んで呼び出します。名前を指定することもできます。

```
Frontend Developer エージェントで React のログイン画面を作って
Code Reviewer に今の差分をレビューさせて
Reality Checker でこの機能が本番に出せる状態か確認して
Software Architect と Security Engineer にこの設計を見てもらって
```

### 収録部門

| 部門 | 数 | 部門 | 数 |
|------|---:|------|---:|
| engineering | 65 | specialized | 59 |
| marketing | 37 | game-development | 21 |
| gis | 13 | security | 12 |
| design | 10 | sales | 9 |
| testing | 9 | paid-media | 7 |
| project-management | 7 | academic | 6 |
| product | 6 | spatial-computing | 6 |
| support | 6 | finance | 5 |
| healthcare | 3 | research | 1 |

一覧と各エージェントの説明は [upstream の README](https://github.com/msitarzewski/agency-agents#-the-agency-roster) を参照してください。

### 更新・絞り込み

```bash
./scripts/update-agency-agents.sh                                  # 最新版に更新（全エージェント）
./scripts/update-agency-agents.sh --division engineering,security  # 部門を絞る
./scripts/update-agency-agents.sh --agent frontend-developer,code-reviewer
./scripts/update-agency-agents.sh --global                         # ~/.claude/agents に入れて全プロジェクトで使う（ローカル PC 向け）
```

- 取り込んだ upstream のコミットは `.claude/agency-agents/UPSTREAM`、ライセンス（MIT）は同じ場所の `LICENSE` にあります。
- スクリプトは前回自分が入れたファイル（`MANIFEST`）だけを入れ替えるので、`.claude/agents/` に自作のエージェントを置いても消えません。
- 全エージェントの説明文はセッションごとに約 2 万トークン分コンテキストに載ります。重く感じたら `--division` で必要な部門だけに絞ってください。
