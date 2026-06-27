# zCounter UI モック（デザイン検討用）

静的 HTML。ブラウザで開いて UI を試し、OK なら `zcounter/ui/assets/index.html` に反映する。

## 現行 UI ベース（日付版）

| ファイル | 内容 |
|----------|------|
| [zcounter-mock-20260612_1.html](./zcounter-mock-20260612_1.html) | 本番 UI 写し（codex ×2 / cursor / claude、fixture データ） |
| [zcounter-mock-20260612_2.html](./zcounter-mock-20260612_2.html) | 20260612_1 + フッターに最終更新時刻と次回更新までの秒カウントダウン |
| [zcounter-mock-20260613_1.html](./zcounter-mock-20260613_1.html) | 20260612_2 + Cursor は Pace のみ色分け（&lt;3%/d warning、&lt;1%/d critical）。Total / Auto の % は常に safe |
| [zcounter-mock-20260613_2.html](./zcounter-mock-20260613_2.html) | 20260613_1 + Cursor API 表示の見た目比較（案A〜D）。**案D** を本番 `index.html` に反映済み |
| [zcounter-mock-20260627_1.html](./zcounter-mock-20260627_1.html) | 本番 `index.html` 写し + Codex 蓄積リセット残数の UI 比較（案A〜C）。**案A** を本番 `index.html` に反映済み |
| [zcounter-mock-20260627_2.html](./zcounter-mock-20260627_2.html) | 20260627_1 + 日付は年なし（`6/27`）、Expires は曜日＋時刻（JST）。**本番反映済み** |

```bash
xdg-open docs/mockups/zcounter-mock-20260627_2.html   # Linux（最新）
open docs/mockups/zcounter-mock-20260627_2.html       # macOS（最新）
```

**運用**: CSS / カード HTML を mock で編集 → 問題なければ本番 `index.html` へコピー。データ形を変えるときだけ `viewmodel.py` も更新。

新しい案を試すときは `zcounter-mock-YYYYMMDD_N.html` で追加する。

## 初期デザイン案（2025）

Mac メニューバーポップオーバー風の見た目比較用。Claude 行なし。

| ファイル | 方向性 |
|----------|--------|
| [zcounter-mock-01.html](./zcounter-mock-01.html) | 案1 — Stacked Cards（本命寄り） |
| [zcounter-mock-02.html](./zcounter-mock-02.html) | 案2 — Provider Sections |
| [zcounter-mock-03.html](./zcounter-mock-03.html) | 案3 — Status Emphasis |
| [zcounter-mock-04.html](./zcounter-mock-04.html) | 案4 — Compact |

## 見方

ブラウザで各 HTML を直接開いてください。

```bash
xdg-open docs/mockups/zcounter-mock-01.html   # Linux
open docs/mockups/zcounter-mock-01.html       # macOS
```

## 4案の違い（要約）

### 案1 — Stacked Cards
- **レイアウト**: 3 アカウントを独立した縦積みカード。1 カード 1 アカウント。
- **情報の見せ方**: 大きな残量 % と横並びバー。Safe / Warning / Critical のピル表示。
- **向き**: 参考画像1に最も近い。初見でも読みやすさ最優先。

### 案2 — Provider Sections
- **レイアウト**: Codex / Cursor をセクション見出しでグループ化。Codex 内で 2 アカウントを連続表示。
- **情報の見せ方**: バー＋% をコンパクトにグリッド配置。provider 比較がしやすい。
- **向き**: 参考画像2の「サービス単位のまとまり」を取り入れた中間案。

### 案3 — Status Emphasis
- **レイアウト**: 上部にアラートバナーと Safe/Warning/Critical の件数チップ。各項目は左ボーダー＋バッジで状態強調。
- **情報の見せ方**: 危険なメトリク（Weekly 2%）をハイライト枠で目立たせる。「今どれが危ないか」が最優先。
- **向き**: 複数アカウント運用で、異常検知を素早くしたいとき向け。

### 案4 — Compact
- **レイアウト**: 幅 300px 前後の表形式。1 行 1 アカウント、列で Primary / Secondary / Reset。
- **情報の見せ方**: ミニバー＋数値のみ。ヘッダに更新間隔（60s）表示。
- **向き**: 毎日のチラ見・メニューバー常駐向け。密度高めだが一覧性は維持。

## 共通仕様

- 対象: Codex / zurgxx、Codex / rock、Cursor / rock（Claude なし。20260612_1 以降は Claude あり）
- テーマ: ライト、角丸、余白多め（案4のみややタイト）
- 色: safe=緑、warning=オレンジ、critical=赤（残量 % に応じて表示）
- フッター: Settings / Refresh（案4 は Quit 追加）

## おすすめ

**本命は案1**。シンプルさ・数字の見やすさ・Mac ポップオーバー感のバランスがよい。  
provider 整理を少し足すなら **案2**、異常時の視認性を上げるなら **案3 の要素を案1 に部分取り込み** が現実的。  
常時表示の密度重視なら **案4** をサブビュー（コンパクトモード）として検討。
