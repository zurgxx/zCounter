# zCounter Codex 5h / Week 使用率表示 — 調査結果レポート

調査日: 2026-07-13  
調査種別: コード追跡 + 実 API 呼び出し（秘密情報マスク済み）  
制約: ファイル変更・コミット・push なし（調査のみ）

---

## 1. 結論

### 5h が表示される直接原因

**確認済み:** OpenAI `wham/usage` API は `rate_limit.primary_window` に **週次枠（`limit_window_seconds: 604800`）** のデータを返しているが、zCounter は `primary_window` を常に **5 時間枠（`five_hour`）** として扱い、表示ラベルを **ハードコード `"5H"`** しているため、実際には週次データが「5H」として表示されている。

根拠:
- 実 API レスポンス（2 アカウント・Plus）: `primary_window.limit_window_seconds = 604800`, `secondary_window = null`
- `normalize_usage_response()` は `primary_window` → `five_hour` に無条件マッピング（`usage_api.py:138-139`）
- `provider.py` は `primary_label="5H"` を固定設定（`provider.py:74-75`）
- 正規化後の `window_minutes` は `10080`（= 7 日）だが、ラベル生成に使われていない

### Week が表示されない直接原因

**確認済み:** API が `rate_limit.secondary_window` を **`null`** で返している。zCounter は `secondary_window` のみを `weekly` にマッピングし、`weekly` が `None` のとき UI / CLI は副枠メトリクスを生成しない。

根拠:
- 実 API: `secondary_window_raw: null`
- `normalize_usage_response()` → `weekly = None`
- `viewmodel._metric_payload()` は `window is None` で `None` を返し metrics 配列に含めない（`viewmodel.py:203-204`）
- `additional_rate_limits` も `null` で、別経路の Week データは存在しない

### OpenAI 側の一時変更との関係

| 項目 | 状態 |
|------|------|
| 5h 枠が API から消えた | **確認済み**（`secondary_window=null`、`primary_window` の期間が 604800 秒） |
| 5h 撤廃が一時的か恒久か | **未確認**（OpenAI 公式ドキュメント・一次情報なし。README も `wham/usage` は非公開 API と明記） |
| 公式 UI が別 API を参照している | **未確認** |
| アカウント単位の段階的ロールアウト | **可能性あり**（今回 2/2 アカウントで同一形状。他プラン・他地域は未検証） |
| 公式 UI では無効化されているが API 上は 5h データが残る | **今回の環境では該当せず**。5h 相当 window（18000 秒）は API に存在しない |

**推測（未確認）:** OpenAI が 5h 制限を一時撤廃し、週次枠を `primary_window` スロットへ移動（または 5h を返さなく）した。zCounter はスロット名（primary=5h, secondary=week）という **旧 API 形状の固定前提** のままのため、表示が乖離している。

### 推奨対応

**案 B（API に存在する window を動的表示 + `limit_window_seconds` によるラベル推定）を推奨。**

スロット名（primary / secondary）ではなく **期間秒数** で枠種別を判定し、存在する window のみ表示する。5h 復活時も `limit_window_seconds: 18000` が返れば自動的に 5H 表示に戻る。

---

## 2. 現在のデータフロー

```
API: GET https://chatgpt.com/backend-api/wham/usage
     Headers: Authorization: Bearer <token>, ChatGPT-Account-Id: <account_id>
     実装: zcounter/providers/codex/usage_api.py:33-66 (fetch_usage)
           zcounter/providers/codex/provider.py:58 (呼び出し)
↓
生 JSON (dict)
     期待フィールド: data["rate_limit"]["primary_window"], data["rate_limit"]["secondary_window"]
     各 window: used_percent, limit_window_seconds, reset_at, reset_after_seconds
     実装: usage_api.py:134-142 (normalize_usage_response)
↓
パーサー: normalize_usage_response / _parse_window / _parse_window_lenient
     実装: usage_api.py:134-180
     primary_window → five_hour (RateWindow | None)  ※期間に関係なく
     secondary_window → weekly (RateWindow | None)
     RateWindow: used_percent, remaining_percent, reset_at, window_minutes
     実装: models.py:44-54
↓
内部モデル: QuotaSnapshot
     実装: provider.py:62-78 (_fetch_account_quota)
     five_hour=five_hour, weekly=weekly
     primary=five_hour, secondary=weekly  ※固定エイリアス
     primary_label="5H", secondary_label="WEEK"  ※固定ラベル
     codex_reset_credits: 別 API (rate-limit-reset-credits)
     実装: provider.py:102-107, usage_api.py:69-131
↓
集約: fetch_all_quotas()
     実装: aggregate.py:9-15
↓
UI キャッシュ / 一貫性ガード
     preserve_unreset_codex_windows: consistency.py:15-61
       条件: used_percent が 1% 以下かつ 20pt 以上急落、reset 境界なし
     merge_with_cache: display.py:34-67
       エラー時のみ cached の five_hour/weekly をフォールバック
     SnapshotStore.merge: viewmodel.py:37-53
↓
CLI 表示
     fetch_all_quotas → snapshot.to_json() or print_table
     実装: cli.py:17-22, 51-67
     primary_label + remaining_percent を表示。window=None なら "-"
↓
UI 表示
     WebviewAPI.refresh → SnapshotStore.merge → build_payload
     実装: webview_api.py:16-26, viewmodel.py:67-118
     display_primary / display_secondary → _metric_payload
     実装: display.py:247-252, viewmodel.py:88-100, 196-212
     index.html: account.metrics.map(metricHtml) — metrics が空要素は描画されない
     実装: index.html:162-172, 214-216
```

### 5h / Week 識別条件（現行）

| 段階 | 識別方法 | 問題点 |
|------|----------|--------|
| API パース | `primary_window` → five_hour、`secondary_window` → weekly | 期間 (`limit_window_seconds`) を見ない |
| ラベル | 常に `"5H"` / `"WEEK"` | `window_minutes` を無視 |
| 表示 | `display_primary()` / `display_secondary()` が non-None なら表示 | weekly=None なら Week 非表示 |
| 期間判定 | `_window_minutes()` で `window_minutes` に格納するのみ | 表示ロジック未使用 |

---

## 3. API レスポンス確認結果

### 実レスポンス確認

**実施済み** — zCounter と同一経路（`fetch_usage` + `normalize_usage_response`）で 2026-07-13 09:29 JST 頃に 2 アカウント（Plus）を確認。

### 返却 window 一覧

| スロット | 存在 | limit_window_seconds | used_percent | reset_at | 備考 |
|----------|------|---------------------|--------------|----------|------|
| `rate_limit.primary_window` | あり | **604800** (7日) | 0 | 2026-07-20 頃 UTC | 旧来の Week 相当の期間 |
| `rate_limit.secondary_window` | **null** | — | — | — | 欠落 |
| `additional_rate_limits` | null | — | — | — | |
| `code_review_rate_limit` | null | — | — | — | |

`rate_limit` オブジェクトのキー: `allowed`, `limit_reached`, `primary_window`, `secondary_window`

### 5h 相当値

**API 上に存在しない**（18000 秒 window なし）。

### Week 相当値

**`primary_window` に存在**（604800 秒）。ただし zCounter は `secondary_window` のみを `weekly` にマップするため **内部モデル上 `weekly=null`**。

### reset 情報

- `reset_at`: Unix timestamp（例: 1784506462 → 2026-07-20T00:14:22Z）
- `reset_after_seconds`: 整数（マスク済み確認）
- `allowed: true`, `limit_reached: false`

### 欠落・null・0 の扱い

| 値 | zCounter の扱い |
|----|----------------|
| `secondary_window: null` | `weekly=None` → 非表示 |
| `used_percent: 0` | 有効値として受理（テストあり: `test_codex_usage_api.py:18-25`） |
| 両 window null | `UsageShapeError` でエラースナップショット |
| invalid primary + valid secondary | primary 破棄、secondary 保持（lenient parse） |

### マスク済みレスポンス例

```json
{
  "plan_type": "plus",
  "rate_limit": {
    "allowed": true,
    "limit_reached": false,
    "primary_window": {
      "used_percent": 0,
      "limit_window_seconds": 604800,
      "reset_after_seconds": 603888,
      "reset_at": 1784506462
    },
    "secondary_window": null
  },
  "additional_rate_limits": null,
  "code_review_rate_limit": null,
  "rate_limit_reached_type": null,
  "rate_limit_reset_credits": {
    "available_count": 4
  }
}
```

### 正規化後（zCounter 内部）

```json
{
  "five_hour": {
    "used_percent": 0.0,
    "remaining_percent": 100.0,
    "reset_at": "2026-07-20T00:14:22Z",
    "window_minutes": 10080
  },
  "weekly": null,
  "primary_label": "5H",
  "secondary_label": "WEEK"
}
```

→ **`window_minutes: 10080`（7日）なのに `primary_label: "5H"`** — ラベルと実データの不一致が確認できる。

---

## 4. 原因分析

| 現象 | 直接原因 | 根拠 | 確度 |
|------|----------|------|------|
| 5h が表示される | `primary_window` が存在し、固定ラベル `"5H"` で描画される。実データは 604800 秒（週次） | 実 API レスポンス + `provider.py:74-75` + `viewmodel.py:91-93` | **確認済み** |
| Week が表示されない | `secondary_window` が `null` → `weekly=None` → metrics に含めない | 実 API + `usage_api.py:139` + `viewmodel.py:203-204` | **確認済み** |
| 公式 UI と不一致 | zCounter がスロット名固定マッピング、API 形状変更に未追従 | 実 API 形状 + コード | **確認済み** |
| 古いキャッシュ表示 | 今回の主因ではない（fresh fetch でも同形状） | 実 API 直接取得結果 | **確認済み** |
| 直前値保持で 5h 残存 | 一貫性ガードは「急落 near-zero」時のみ。今回 API は 0% だが初回 or 非急落なら該当せず | `consistency.py:81-96` | **可能性が高い**（副次要因） |
| 5h 期間判定誤り | 期間判定自体は `window_minutes=10080` と正しく格納。誤りはラベル側 | `usage_api.py:162-171` | **確認済み** |
| 別 window を 5h と誤分類 | `primary_window` を無条件で five_hour 扱い = 実質週次を 5h スロットへ誤分類 | `usage_api.py:138` | **確認済み** |
| 欠落時デフォルト 5h 生成 | 該当コードなし | コード確認 | **確認済み（該当なし）** |
| 公式 UI が別 API | 未調査 | — | **未確認** |
| 段階的ロールアウト | 2 アカウント同一形状。他は未検証 | 実 API 2件 | **未確認** |

### 5h が表示される理由 — 個別確認

| 可能性 | 結果 |
|--------|------|
| API が 5h window を返している | **否** — 18000 秒 window なし。604800 秒が primary |
| 古いキャッシュ | **否** — 直接 API で再現 |
| 直前値保持 | **副次要因のみ** — 初回表示でも 5H ラベルは出る |
| 5h 期間判定誤り | **ラベル未使用が本質** |
| 別 window の誤分類 | **是** — primary=週次データ |
| 欠落時デフォルト 5h 生成 | **否** |
| 公式 UI 無効化・API 残存 | **今回環境では 5h データ自体なし** |
| 別 API | **未確認** |
| ロールアウト | **未確認** |

### Week が表示されない理由 — 個別確認

| 可能性 | 結果 |
|--------|------|
| Week window が API に存在しない | **半否** — 604800 秒 window は primary に存在。secondary には不在 |
| フィールド名・階層変更 | **可能性が高い** — Week が primary へ移動 |
| 期間判定失敗 | **否** — `window_minutes=10080` 正常 |
| reset パース失敗 | **否** — reset_at 正常 |
| 型定義に Week なし | **否** — `weekly` フィールドはある |
| details 保存・UI 未渡し | **否** — details 未使用 |
| CLI / UI 別モデル | **否** — 同一 QuotaSnapshot |
| null 非表示 | **是** — `weekly=None` |
| 配列先頭のみ | **該当なし** — 配列ではない |
| 5h と上書き | **否** |
| ゼロ値・欠損対策が Week 消去 | **否** — secondary null をそのまま None に |

---

## 5. 修正候補

### 案 A: 5h を一時的に非表示

| 項目 | 内容 |
|------|------|
| 修正概要 | Codex カードから 5H メトリクスを非表示にする（ハードコード） |
| 変更対象 | `provider.py`, `viewmodel.py`, モック |
| 既存仕様への影響 | 5h 復活時に再修正が必要 |
| リスク | 一時対応向け。OpenAI ロールバックで再発 |
| テスト | 5h 非表示 snapshot テスト |

**利点:** 最小 diff、即座に誤表示解消  
**欠点:** Week も依然非表示のまま（本質未解決）、5h 復活で再作業  
**5h 復活時:** 再び非表示のまま or 再修正  
**アカウント差異:** 5h が残るアカウントで非表示にすると情報欠落

### 案 B: API に存在する window だけ動的表示（推奨）

| 項目 | 内容 |
|------|------|
| 修正概要 | `primary_window` / `secondary_window`（将来 `additional_rate_limits`）を収集し、`limit_window_seconds` でラベル推定。存在する枠のみ `primary`/`secondary` に並べ、動的 `primary_label`/`secondary_label` を設定 |
| 変更対象 | `usage_api.py`, `provider.py`, `display.py`（ラベル helper）, `consistency.py`（警告文言）, tests, README |
| 既存仕様への影響 | JSON の `five_hour`/`weekly` は期間ベース再マップ（18000→five_hour, 604800→weekly）推奨 |
| リスク | 未知の `limit_window_seconds` のラベル表現 |
| テスト | 旧形状（5h+week）、新形状（week only）、5h only、両方 null |

**利点:** API 形状変更に強い、5h 復活自動対応、Week 表示復旧  
**欠点:** 実装範囲が案 A より広い  
**現行モデル:** `primary`/`secondary` 汎用化と整合  
**UI レイアウト:** metrics 1 列 or 2 列可変（既存 CSS は flex で対応可）

### 案 C: 固定枠 + active 判定

| 項目 | 内容 |
|------|------|
| 修正概要 | 5H/WEEK スロットを維持し、API の `allowed` 等で active 判定 |
| 変更対象 | `usage_api.py`, `provider.py`, `models.py` |
| 既存仕様への影響 | active 情報が window 単位にない |
| リスク | `allowed=true` でも 5h 不在の現状を判定できない |
| テスト | active / inactive fixture |

**利点:** 概念モデル維持  
**欠点:** **per-window active フィールドが API に存在しない**（`allowed` は rate_limit 全体）  
**API に active なしの場合:** 結局 `limit_window_seconds` または null 判定が必要 → 案 B と実質統合

### 案 D: 公式 UI 同等の別 API

| 項目 | 内容 |
|------|------|
| 修正概要 | Codex Desktop / Web UI が使う別エンドポイントを調査・利用 |
| 変更対象 | 新 provider モジュール |
| 既存仕様への影響 | 大 |
| リスク | 非公開 API 依存増、認証方式差異、破壊的変更 |

**実現可能性:** **未確認**（DevTools 等での公式 UI 通信調査は今回未実施）  
**認証・安定性:** 現行 `wham/usage` と同等以上の不確実性  
**リスク:** README も非公開 API 警告あり。二重依存は避けたい

---

## 6. 推奨修正方針

### 採用案

**案 B（動的 window 表示 + 期間ベースラベル）**

### 採用理由

1. 実 API 確認で、問題は「5h 撤廃」より **スロット意味の変更**（week → primary, secondary null）
2. `limit_window_seconds` は既にパース済みだが未活用 — 低コストで正確化可能
3. 5h 復活・将来の新 window 追加にハードコード不要
4. 案 C は per-window active がなく、結局期間/null 判定が必要
5. 案 D は調査コスト・リスク大

### 表示仕様（提案）

1. window 収集: `primary_window`, `secondary_window`（+ 将来 `additional_rate_limits[]`）
2. ラベル推定（`limit_window_seconds`）:
   - `18000` → `"5H"`
   - `604800` → `"WEEK"`
   - その他: `"${hours}H"` または `"${days}D"`（86400 倍数）
3. 表示順: 期間の短い順（5H → WEEK → その他）
4. 最大 2 枠を `primary`/`secondary` に割当（現 UI 2 メトリクス前提）
5. JSON 後方互換: `five_hour` = 18000 秒 window、`weekly` = 604800 秒 window（存在する場合のみ）

### 一時欠損時の扱い

- 既存 `preserve_unreset_codex_windows` を **期間キー**（または primary/secondary スロット）単位で維持
- エラー時 `merge_with_cache` は現行維持
- window 0 個かつ cached あり → stale 表示

### 5h 復活時の挙動

- API が再び `18000` 秒 window を返せば自動で `"5H"` 表示
- primary+secondary 両方返れば 2 枠表示に復帰

### Week が存在しないアカウントの挙動

- 存在する window のみ表示（1 枠 UI）
- ラベルは期間から推定（Week 固定表示はしない）

### 後方互換性

- CLI `--json` の `five_hour`/`weekly` フィールドは期間ベース再マップで維持
- `primary`/`secondary` + 動的 label が正規の表示ソース

---

## 7. 必要なテスト

### 既存テスト（関連）

| ファイル | 内容 |
|----------|------|
| `tests/test_codex_usage_api.py` | primary only 5h、secondary only week、invalid primary + valid secondary |
| `tests/test_codex_consistency.py` | near-zero 急落保持、missing window、store cache |
| `tests/test_ui_viewmodel.py` | Codex metrics reset、reset credits |
| `tests/test_ui_display.py` | format_codex_row 5H/WEEK 表示 |

### 不足しているテストケース

1. **新 API 形状:** primary=604800, secondary=null → Week のみ表示、5H 非表示
2. **旧 API 形状:** primary=18000, secondary=604800 → 5H + Week 両方
3. **5h only:** primary=18000, secondary=null
4. **week only（secondary）:** primary=null, secondary=604800（既存 `test_null_or_missing_window` 部分カバー）
5. **ラベル推定:** 未知の `limit_window_seconds`（例: 86400 → `1D` または `24H`）
6. **five_hour/weekly JSON 再マップ:** 新形状で `five_hour=null`, `weekly=非null`
7. **UI payload:** week only 時 metrics 長さ 1、label=`WEEK`
8. **consistency:** primary スロットが week に変わった後の near-zero 急落（誤保持しない）
9. **additional_rate_limits:** 将来配列追加時のパース（スタブ）
10. **両 window null:** UsageShapeError（既存）
11. **0% / 100% / reset 直後:** 新形状 fixture
12. **CLI table:** week only 行フォーマット

---

## 8. 実装プロンプト

以下を別セッションの実装担当 AI にそのまま渡してください。

---

```
# zCounter Codex 5h / Week 表示修正 — 実装タスク

## 背景

OpenAI `wham/usage` API のレスポンス形状が変更された。
2026-07-13 時点の実レスポンス（Plus 2 アカウント確認済み）:

- `rate_limit.primary_window`: limit_window_seconds=604800 (7日), used_percent, reset_at あり
- `rate_limit.secondary_window`: null
- additional_rate_limits: null

zCounter は primary→five_hour(5H), secondary→weekly(WEEK) と固定マッピングしており、
週次データが「5H」ラベルで表示され、Week は secondary=null のため非表示になっている。

## 確認済み原因

1. usage_api.normalize_usage_response() がスロット名のみで five_hour/weekly を決定（期間未使用）
2. provider.py が primary_label="5H", secondary_label="WEEK" を固定
3. viewmodel._metric_payload() は window=None を metrics から除外
4. window_minutes は正しく 10080 だがラベルに未使用

## 修正仕様（案 B 採用）

1. **window 収集・正規化** (`zcounter/providers/codex/usage_api.py`)
   - primary_window, secondary_window から RateWindow リストを構築
   - 各 window に limit_window_seconds からラベルを推定する helper を追加:
     - 18000 → "5H"
     - 604800 → "WEEK"
     - その他: 86400 倍数なら "{n}D"、否则 "{hours}H" 等（既存 display 慣習に合わせる）
   - 期間の短い順にソート
   - 返却: (windows: list[tuple[label, RateWindow]], または primary/secondary + labels)
   - **後方互換:** five_hour = 18000秒 window, weekly = 604800秒 window（存在時のみ）
   - normalize_usage_response のシグネチャ変更時は provider 側を更新

2. **provider** (`zcounter/providers/codex/provider.py`)
   - 固定 primary_label="5H" を廃止し、正規化結果の動的ラベルを使用
   - primary/secondary/five_hour/weekly を期間ベースで設定
   - エラースナップショットの label も null または "-" に（誤解を招く 5H 固定を避ける）

3. **consistency** (`zcounter/providers/codex/consistency.py`)
   - 警告文言 "Codex 5H usage..." を汎用化（例: "Codex {label} usage..."）または primary/secondary スロット基準に
   - five_hour/weekly フィールド依存が残る場合は primary/secondary ベースに移行検討

4. **display / viewmodel**
   - 大きな変更不要（snapshot.primary_label / display_primary 経由で動作する想定）
   - format_window_label が 5 文字切 truncate する点に注意（"WEEK" は OK）

5. **README.md**
   - Codex の five_hour/weekly は「期間ベース再マップ」である旨を追記

6. **モック**（UI 変更がある場合）
   - AGENTS.md 手順に従い docs/mockups/ に week-only fixture のモックを作成
   - ユーザー OK 後 index.html 反映

## 対象ファイル（最低限）

- zcounter/providers/codex/usage_api.py
- zcounter/providers/codex/provider.py
- zcounter/providers/codex/consistency.py（警告文言）
- tests/test_codex_usage_api.py
- tests/test_codex_consistency.py
- tests/test_ui_viewmodel.py（必要なら）
- tests/test_ui_display.py（必要なら）
- README.md

## テスト要件

`.venv/bin/python -m unittest discover -s tests -v` を全 PASS。

追加必須:
- primary=604800, secondary=null → normalized weekly のみ、label WEEK、five_hour=null
- primary=18000, secondary=604800 → 両方、labels 5H/WEEK
- primary=18000, secondary=null → 5H のみ
- UI build_payload で week-only 時 metrics 長 1

## 変更禁止範囲

- Cursor / Claude provider のロジック
- Git config 変更
- 秘密情報のログ出力
- 今回不要な UI デザイン変更

## Git 運用

- ユーザー明示指示まで commit / push しない
- commit 時 author/committer email: 281981+zurgxx@users.noreply.github.com (AGENTS.md 参照)
- メッセージ例: `fix(codex): derive window labels from limit_window_seconds`

## 完了条件

1. 実 API 形状（primary=week, secondary=null）で Week が表示され、5H 誤表示がない
2. 旧形状 fixture（5h+week）も引き続き正しく表示
3. 全 unit test PASS
4. 変更ファイルの lint 問題なし

## 報告形式

- 変更概要
- 修正前後の表示イメージ（week-only / 5h+week）
- 追加・更新テスト一覧
- 未対応事項（additional_rate_limits 等）
```

---

## 付録 A: 主要コード参照

| 箇所 | ファイル:行 | 役割 |
|------|-------------|------|
| API URL | `usage_api.py:13` | `wham/usage` |
| fetch | `usage_api.py:33-66` | GET + Bearer |
| normalize | `usage_api.py:134-142` | primary→five_hour, secondary→weekly |
| parse window | `usage_api.py:152-172` | used_percent, window_minutes |
| provider 固定 label | `provider.py:74-75` | "5H", "WEEK" |
| 一貫性ガード | `consistency.py:15-61` | near-zero 急落保持 |
| cache merge | `display.py:34-67` | エラー時 stale |
| UI metrics | `viewmodel.py:88-100` | None 除外 |
| UI render | `index.html:214-216` | metrics 配列描画 |
| CLI row | `cli.py:51-67` | primary/secondary 表示 |

## 付録 B: 推測と確認済みの整理

### 確認済み

- API primary=604800秒, secondary=null
- zCounter が 5H 固定ラベルで primary を表示
- weekly=null で Week 非表示
- window_minutes は正しく 10080
- キャッシュが主因ではない（fresh API で再現）

### 推測（未確認）

- OpenAI による 5h 制限の一時撤廃
- 変更が全アカウント・全プランに適用済みか
- 公式 Codex UI が同一 API を参照しているか
- 5h 制限が将来復活するか

### 分からないこと

- OpenAI 公式の rate limit 仕様（公開ドキュメントなし）
- `additional_rate_limits` が将来使われるか
- 公式 UI が参照する正確な API エンドポイント

---

*調査実施: zCounter リポジトリ `<repo-root>`、実 API 2 アカウント、コード静的解析*
