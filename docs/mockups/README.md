# zCounter UI モック（デザイン検討用）

静的 HTML の 4 案。実装用ではなく、Mac メニューバーポップオーバー風の見た目比較が目的です。

## ファイル

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

- 対象: Codex / zurgxx、Codex / rock、Cursor / rock（Claude なし）
- テーマ: ライト、角丸、余白多め（案4のみややタイト）
- 色: safe=緑、warning=オレンジ、critical=赤（残量 % に応じて表示）
- フッター: Settings / Refresh（案4 は Quit 追加）

## おすすめ

**本命は案1**。シンプルさ・数字の見やすさ・Mac ポップオーバー感のバランスがよい。  
provider 整理を少し足すなら **案2**、異常時の視認性を上げるなら **案3 の要素を案1 に部分取り込み** が現実的。  
常時表示の密度重視なら **案4** をサブビュー（コンパクトモード）として検討。
