# 実装計画 006 — Fallout4 / Starfield 対応 + skip_records の toml 化（v0.6）

- 作成: 2026-06-29
- リスク分類: **normal**
- バージョン: v0.6（破壊的変更を含む・後方互換性の破れあり）
- 関連: [NG ガイド](../notes/xtranslator_translation_ng_guide.md) / [設計判断](../design.md) / [Plan 005](005-llm-config.md)

---

## 1. ゴール

`iroiro-translator` を Skyrim / Fallout4 / Starfield の 3 ゲーム対応に拡張する。
具体的には以下 3 点を実装する:

1. **`DEFAULT_SKIP_RECORDS` を `iroiro.toml` に完全移行（案 α 徹底版）**
   - コードから `DEFAULT_SKIP_RECORDS` 定数を **完全削除**
   - `iroiro.toml` の `[iroiro] skip_records` を **必須化**
2. **skip リストを NG ガイド（§3 / §9.1 Conservative Preset）に基づき拡充**
   - 現在 12 件 → 新 14 件（+ `FLST:FULL` / `KYWD:FULL`）
   - ※ `EDID` は「全レコード型のフィールド名」として現れるため `REC:FIELD` 形式の skip リストには不向き。ユーザー判断により **今回の拡充対象から除外**
3. **`[iroiro.rec_hints]` を NG ガイド §4「Usually Safe Translation Targets」に基づき拡充**
   - 既存 Skyrim 向け 17 件を 3 ゲーム共通表現に汎用化
   - Fallout4 / Starfield で出現するレコード（`AMMO:FULL` / `MISC:FULL` / `WRLD:FULL` / `INFO:NAM1` 等）を追加
   - skip リストと重複するレコード（`FACT:FULL` / `RACE:FULL` / `CLAS:FULL` / `MGEF:FULL`）は rec_hints から **除外**（skip されるためヒントが意味をなさない）

---

## 2. 背景・現状

### 2.1 現状のコード構造

- `iroiro/translator.py:103-116` — `DEFAULT_SKIP_RECORDS: frozenset[str]`（12 件）がモジュール定数
- `iroiro/translator.py:119-153` — `is_translation_needed(source, rec, skip_records=None)`。
  `skip_records=None` のとき `DEFAULT_SKIP_RECORDS` にフォールバック
- `iroiro/translator.py:156-171` — `_parse_skip_records(text)` CLI フラグ `--skip-records` 用
- `iroiro/config.py` — `load_config()` は `[iroiro]` セクションを dict で返す。
  `_VALIDATORS` dict で各キーの validator を管理。`skip_records` は **未登録**（toml から読まない）
- `iroiro/cli.py:175-184` — `--no-skip-default-records` / `--skip-records TEXT` フラグ
- `iroiro/cli.py:231-238` — skip_records 構築:
  ```python
  if no_skip_default_records:
      skip_records = _parse_skip_records(skip_records_text)
  else:
      skip_records = DEFAULT_SKIP_RECORDS | _parse_skip_records(skip_records_text)
  ```
  （現在は「DEFAULT + 追加」の「追加」セマンティクス）
- `iroiro/progress.py:58-67` — `compute_skip_records_fingerprint()`。空集合は `""` を返す特例（v0.1 形式 progress.json との互換性）
- `iroiro.toml.example:90-108` — `[iroiro.rec_hints]` 17 件（Skyrim 向け）
- v0.6 ロードマップ（`docs/development.md:186`）に「`skip_records` の `iroiro.toml` 化」が明記済み

### 2.2 NG ガイドとの整合

`docs/notes/xtranslator_translation_ng_guide.md` は 3 ゲーム対応のコーディングガイド（721 行）。
本計画は同ガイドの以下の節を直接の根拠とする:

- §3 Common Skip List（14 件・EDID 抜き）
- §4 Usually Safe Translation Targets（rec_hints 拡充の根拠）
- §9.1 Conservative Preset（新デフォルトの根拠）
- §6.2 / §6.3 Fallout4 / Starfield 固有の注意点（ドキュメント記述の根拠）

### 2.3 v0.5 との哲学的整合性

v0.5（Plan 005）は「LLM 挙動中核（`system_prompt` / `reject_phrases` / `[iroiro.rec_hints]`）の
コード内ハードコードを完全削除し toml 必須化（案 α 徹底版）」を採用。
本計画の「`DEFAULT_SKIP_RECORDS` も案 α で toml 必須化」は v0.5 の哲学を skip_records に拡張するもので、
プロジェクト全体の一貫性を高める。

---

## 3. スコープ / 非スコープ

### 3.1 スコープ

- `DEFAULT_SKIP_RECORDS` の toml 化（案 α・コード完全削除・toml 必須）
- skip リスト拡充（12 件 → 14 件）
- `[iroiro.rec_hints]` 拡充（NG ガイド §4 網羅・3 ゲーム共通化）
- CLI フラグ `--no-skip-default-records` の **廃止**（派生判断・§4.4 参照）
- CLI フラグ `--skip-records TEXT` の **完全置換セマンティクス化**（toml の値を上書き）
- `is_translation_needed` の `skip_records` 引数必須化（`None` フォールバック削除）
- `iroiro.toml.example` 更新（`skip_records` 追記・`rec_hints` 拡充）
- 全ドキュメント（`design.md` / `usage.md` / `development.md` / `README.md`）の 3 ゲーム対応記述
- `__version__` の `0.6` 更新

### 3.2 非スコープ（ユーザー承認済み）

- `--game skyrim|fallout4|starfield` のようなゲーム選択機能
- プリセット切り替え機能（Conservative / Translation-Friendly / Starfield-Friendly）
- `review-needed` 状態の導入（iroiro は `translate` / `skip` の 2 状態を維持）
- `system_prompt` の「Skyrim MOD の英文を…」の汎用化（別件・必要なら別タスク）
- NG ガイド §5「Review-Needed List」（`OMOD:FULL` / `COBJ:*` / `PERK:FULL` / `AVIF:FULL` /
  `GMST:*` / `LSCR:*` / `TERM:*` 等）のスキップリスト化（review-needed 状態が無いため今回は見送り）

---

## 4. 設計判断（確定済み + 派生判断）

### 4.1 確定済み判断（ユーザー合意済み）

| # | 判断 | 理由 |
|---|---|---|
| 1 | skip_records toml 化は **案 α（徹底版）** | v0.5 の哲学との一貫性。コードから `DEFAULT_SKIP_RECORDS` を完全削除し toml 必須化 |
| 2 | skip リストは **14 件**（現 12 + `FLST:FULL` + `KYWD:FULL`） | NG ガイド §9.1 Conservative Preset 準拠。`EDID` は全レコード型フィールド名のため除外 |
| 3 | rec_hints は **NG ガイド §4 網羅方針** | 3 ゲーム共通の translate 対象レコードのヒントを整備 |
| 4 | ゲーム選択・プリセット・review-needed は **スコープ外** | ユーザー要件に含まれない |

### 4.2 派生判断 1: `--no-skip-default-records` の廃止

案 α で `DEFAULT_SKIP_RECORDS` 定数がコードから消えるため、「default を無効化」の意味を成さない。
v0.5 の哲学（CLI フラグは toml を上書きのみ）に従い **廃止** する。

代替手段: ユーザーが「全件翻訳」したい場合は `iroiro.toml` で `skip_records = []` を指定するか、
CLI で `--skip-records ""` を指定する（`_parse_skip_records("")` は空 set を返す）。

### 4.3 派生判断 2: `--skip-records` を `str | None = None` パターンで完全置換（Codex review 採用）

現在は `DEFAULT_SKIP_RECORDS | _parse_skip_records(text)` で「追加」セマンティクス。
案 α で DEFAULT が無くなるため、v0.5 と同じ「CLI は toml を完全上書き」パターンに変更する。

**Typer signature を `skip_records_text: str | None = typer.Option(None, "--skip-records", ...)` に変更**し、
3 状態を明確に区別する（v0.5 の `retry_failed: bool | None = None` と同パターン・Codex review 採用案）:

| `--skip-records` 指定 | Typer が渡す値 | 意味 |
|---|---|---|
| 省略 | `None` | **toml の `skip_records` を使用** |
| `--skip-records ""` | `""` | **明示的に空 set（全件翻訳）** |
| `--skip-records "HDPT:FULL,..."` | 非空文字列 | **toml を完全置換** |

優先順位: `--skip-records`（非 `None`・明示指定時）＞ `iroiro.toml` ＞ （内蔵デフォルト無し）

`--no-skip-default-records` 廃止後の「全件翻訳」CLI 手段は `--skip-records ""` で提供される
（`_parse_skip_records("")` は空 set を返す・§4.2 の代替手段）。

### 4.4 派生判断 3: `is_translation_needed` の signature 変更（Codex review 指摘反映）

現行 `def is_translation_needed(source: str, rec: str = "", skip_records: frozenset[str] | None = None) -> bool`
は、`skip_records` を必須化する場合に Python 構文上不可能（デフォルト値を持つ `rec=""` の後に
デフォルト無し引数は置けない）。以下のいずれかにする必要がある:

- **(a) `rec` も必須化**: `def is_translation_needed(source: str, rec: str, skip_records: frozenset[str]) -> bool`
- **(b) keyword-only 化**: `def is_translation_needed(source: str, rec: str = "", *, skip_records: frozenset[str]) -> bool`

**採用: (a) `rec` も必須化**。理由:
- 呼出側（`cli.py:336/342/347/444` / `test_translator.py`）は既に `rec` を明示渡している
- v0.1 互換の `is_translation_needed(source)` 呼出は既存コードに無い（grep 確認済み）
- signature がシンプルで分かりやすい
- `None` フォールバック削除と併せ「`DEFAULT_SKIP_RECORDS` への暗黙依存」が完全に消える

`None` を渡した場合の挙動: **`TypeError`（Python の引数欠落と同じ）**。これは意図的（暗黙フォールバックを許さない）。
T165 は「`is_translation_needed(source, rec)` で `skip_records` 省略時 `TypeError`」を検証する。

### 4.5 派生判断 4: `compute_skip_records_fingerprint` の空集合特例は維持

空集合 = `""` を返す特例は、v0.1 形式 progress.json との互換性のため **維持**。
案 α でも「`skip_records = []`（全件翻訳）」を許容するため、空 set は正当値のままとする。

### 4.6 派生判断 5: skip リストと rec_hints の重複レコードの扱い

`FACT:FULL` / `RACE:FULL` / `CLAS:FULL` / `MGEF:FULL` は skip リストに入るため、
rec_hints から **除外** する（skip されるのでヒントが意味をなさない）。
ユーザーが `--skip-records` で個別に翻訳対象に変更した場合は rec_hints が効かないが、
これは v0.2 と同じ「skip リストと rec_hints は独立管理・ユーザー責任で整合」方針。

### 4.7 派生判断 6: `INFO:RNAM` → `INFO:NAM1` への整理

現在の `iroiro.toml.example` の `[iroiro.rec_hints]` に `INFO:RNAM` があるが、
NG ガイド §4 では `INFO:NAM1`（Dialogue line text）/ `INFO:NAM2`（Additional dialogue text）
が標準。xTranslator の Skyrim XML では `INFO:NAM1` が主流（NPC セリフ本文）のため、
`INFO:NAM1` に置換する。`INFO:RNAM` は今回の採用から外す。
※ 実データでの `INFO:RNAM` 出現有無は実装時に要確認（サンプル XML が git 管理外のため確認不可）。

---

## 5. skip_records の toml 化詳細（案 α）

### 5.1 TOML スキーマ

```toml
[iroiro]
# ...既存項目...
skip_records = [
  "HDPT:FULL", "FURN:FULL", "CLAS:FULL", "DOOR:FULL",
  "FACT:FULL", "CLFM:FULL", "TREE:FULL", "MGEF:FULL",
  "RACE:FULL", "EXPL:FULL", "HAZD:FULL", "BPTD:BPTN",
  "FLST:FULL", "KYWD:FULL",
]
```

- 型: `list[str]`（TOML 配列）
- 各要素: 非空 `str`・大文字正規化（`hdpt:full` → `HDPT:FULL`）
- 空リスト `[]` は **許可**（全件翻訳・`compute_skip_records_fingerprint` の空集合特例と整合）
- 重複: `frozenset` 化で自動除去
- 必須: 欠損時 `IroiroError`（v0.5 の `system_prompt` 等と同様）

### 5.2 validator

`iroiro/config.py` に `_validate_skip_records(v, key, path) -> frozenset[str]` を追加:

- `list` 型のみ許可（文字列スカラー拒否・`_validate_reject_phrases` と同パターン）
- 各要素は `str` のみ（`int` / `bool` 拒否）
- 各要素は非空（`""` 拒否）
- 各要素を `strip().upper()` で正規化（`_parse_skip_records` と同様）
- 空リスト `[]` は許可
- 戻り値は `frozenset[str]`（重複除去済み）

`_VALIDATORS` dict に `"skip_records": _validate_skip_records` を追加。
v0.6 必須チェックを §5.3 で追加。

### 5.3 必須チェック

`load_config()` の §5 必須チェック部分に以下を追加:

```python
if "skip_records" not in result:
    raise IroiroError(f"[iroiro] skip_records is required in {path}")
```

`system_prompt` / `reject_phrases` / `rec_hints` と同パターン。

### 5.4 コード削除

`iroiro/translator.py` から:

- `DEFAULT_SKIP_RECORDS` 定数（103-116 行）を **完全削除**
- `is_translation_needed` の `skip_records: frozenset[str] | None = None` を
  `skip_records: frozenset[str]` に変更（必須引数化）
- `if skip_records is None: skip_records = DEFAULT_SKIP_RECORDS` を削除

`iroiro/cli.py` から:

- `from iroiro.translator import DEFAULT_SKIP_RECORDS` の import 削除
- `--no-skip-default-records` フラグ定義削除
- `--skip-records` フラグの Typer signature を `str | None = None` に変更（§4.3）
- skip_records 構築ロジック（231-238 行）を以下に変更:
  ```python
  # 優先順位（§4.3）: --skip-records（非 None・明示指定時）＞ iroiro.toml
  # - None（省略）: toml の skip_records を使用
  # - ""（明示的空文字）: 空 set = 全件翻訳
  # - 非空文字列: 完全置換（toml を無視）
  if skip_records_text is None:
      skip_records = cast(frozenset[str], file_cfg["skip_records"])
  else:
      skip_records = _parse_skip_records(skip_records_text)
  ```

---

## 6. skip リスト拡充（14 件）

新デフォルト（`iroiro.toml.example` に記載）:

```text
HDPT:FULL  FURN:FULL  CLAS:FULL  DOOR:FULL  FACT:FULL  CLFM:FULL
TREE:FULL  MGEF:FULL  RACE:FULL  EXPL:FULL  HAZD:FULL  BPTD:BPTN
FLST:FULL  KYWD:FULL
```

根拠: NG ガイド §3 Common Skip List / §9.1 Conservative Preset（**EDID を除く**・Codex review 指摘反映）。
3 ゲーム共通で「内部管理用レコード」として翻訳非推奨の最小セット。
※ NG ガイド §2 で `EDID` は「Absolute NG」だが、iroiro の `REC:FIELD` 形式 skip リストには不向き
（全レコード型のフィールド名として現れるため・ユーザー判断により除外）。docs では「EDID を除く
Conservative skip list」と正確に表記する。

`MGEF:FULL` / `RACE:FULL` は v0.2 から引き続きスキップのまま（実データ検証済み）。
ユーザーが個別に翻訳したい場合は `iroiro.toml` の `skip_records` から該当レコードを削除するか、
CLI で `--skip-records "HDPT:FULL,..."`（13 件を再指定）で制御可能。

---

## 7. rec_hints 拡充

### 7.1 新 rec_hints（`iroiro.toml.example` 記載内容）

NG ガイド §4 + 既存のうち skip リストと重複しないもの:

```toml
[iroiro.rec_hints]
# === 会話・クエスト・メッセージ ===
"INFO:NAM1" = "NPC の会話本文。自然な会話文。"
"INFO:NAM2" = "NPC の会話追加テキスト。"
"DIAL:FULL" = "会話トピック・選択肢。簡潔な表現。"
"QUST:FULL" = "クエストのタイトル。"
"QUST:CNAM" = "クエストの目的テキスト。"
"QUST:NNAM" = "クエストの進行ログ・ジャーナル。"
"MESG:FULL" = "メッセージのタイトル。"
"MESG:DESC" = "メッセージの本文。"

# === 書籍・メモ ===
"BOOK:FULL" = "書籍・メモ・ホロテープのタイトル。"
"BOOK:DESC" = "書籍・メモ・端末の本文。物語風の自然な日本語。"

# === NPC・アイテム・装備 ===
"NPC_:FULL"  = "NPC の名称。固有名詞として扱う。"
"WEAP:FULL" = "武器の名称。1〜4語程度。"
"WEAP:DESC" = "武器の説明文。"
"ARMO:FULL" = "防具・服・宇宙服の名称。1〜4語程度。"
"ARMO:DESC" = "防具の説明文。"
"AMMO:FULL" = "弾薬の名称。"
"ALCH:FULL" = "薬・回復アイテム・食料・化学物質の名称。"
"MISC:FULL" = "雑貨アイテムの名称。"
"SPEL:FULL" = "スペル・能力の名称。"
"SPEL:DESC" = "スペル・能力の説明文。"
"PERK:FULL" = "パークの名称。"
"PERK:DESC" = "パークの説明文。"
"AVIF:FULL" = "Actor Value の名称（UI に表示される場合）。"

# === 場所 ===
"CELL:FULL" = "セル・場所の名称。"
"LCTN:FULL" = "ロケーションの名称。"
"WRLD:FULL" = "ワールドスペースの名称。"

# === その他（既存維持・汎用化） ===
"MGEF:DESC" = "魔法効果の説明文。自然な日本語の文章。"
"ENCH:FULL" = "エンチャントの名称。"
"ACTI:FULL" = "アクティベータ（家具・看板等）の名称。"
"INGR:FULL" = "錬金素材の名称。"
```

### 7.2 既存から除外するレコード

| レコード | 除外理由 |
|---|---|
| `FACT:FULL` | skip リスト（14 件）に含まれるため |
| `RACE:FULL` | 同上 |
| `CLAS:FULL` | 同上 |
| `MGEF:FULL` | 同上（`MGEF:DESC` は維持） |
| `INFO:RNAM` | `INFO:NAM1` に置換（§4.7） |

### 7.3 skip リストと rec_hints の整合性

skip リスト 14 件と rec_hints の重複は **意図的にゼロ** にする。
ユーザーが `iroiro.toml` で skip リストから外したレコードに対応する rec_hints が存在しない場合、
ヒント無しで翻訳される（v0.2 と同じ・ユーザー責任）。

### 7.4 `PERK` / `AVIF` の扱いに関する注記（Codex review 指摘）

`PERK:FULL` / `PERK:DESC` / `AVIF:FULL` は NG ガイド内で扱いが揺れている:
- §4「Usually Safe Translation Targets」では safe target（翻訳候補）
- §5「Review-Needed List」/ §9.1「Conservative Preset review-needed」では review-needed

iroiro は review-needed 状態を持たないため、本計画では §4 に従い rec_hints に採用する（翻訳候補）。
ただし **docs に「NG ガイド内で review-needed ともされるため、保守的運用では注意が必要」**
と注記する（`docs/usage.md` の skip_records 節・`docs/design.md` の制限事項）。

---

## 8. 課題（Codex review で確認）

### 8.1 `--skip-records ""` のセマンティクス（解決済み・Codex review 採用）

§4.3 に統合。`str | None = None` パターンで 3 状態を明確に区別する。
`None`（省略）= toml 使用、`""`（明示的空文字）= 空 set = 全件翻訳、非空文字列 = 完全置換。
これは v0.5 の `retry_failed: bool | None = None` と同パターン。

### 8.2 既存テストの `DEFAULT_SKIP_RECORDS` 参照

`tests/test_translator.py` / `tests/test_cli.py` で `DEFAULT_SKIP_RECORDS` を直接 import している
テストがある場合、案 α で定数が削除されるため collection error になる。
GaOTTT memory（v0.5 の教訓）に従い、**既存テストの signature 追随は WP-2 の最初のタスク** とする。
WP-1 は「新規テスト追加・既存 fixtures 拡充」のみ。

### 8.3 既存 fixtures の `skip_records` 追記

`tests/fixtures/iroiro_v05_*.toml`（6 種）+ 既存 7 種 = 計 13 種の toml fixtures に
`skip_records` を追記する必要がある（v0.6 必須チェックで fail しないよう）。
新規 fixture として `iroiro_v06_missing_skip_records.toml`（必須チェック検証用）を追加。

### 8.4 `docs/notes/translate-skip-records.md` の更新

v0.2 の根拠資料だが「✅ implemented」スタンプ済み。v0.6 で skip リストが変わるため、
「v0.6 で toml 化・14 件に拡充」の追記が必要。

### 8.5 `progress.json` 後方互換性

v0.5 までの `progress.json` は `skip_records_fingerprint` に 12 件の fingerprint を持つ。
v0.6 で 14 件に変わるため、resume 時に fingerprint 不一致で停止する（安全側の挙動・仕様通り）。
ユーザーは `progress.json` を削除して再実行する必要がある。これは **文書化** する（usage.md / handoff）。

---

## 9. テスト戦略

### 9.1 テスト追加・更新対象

| ファイル | 追加・更新内容 |
|---|---|
| `tests/test_translator.py` | `DEFAULT_SKIP_RECORDS` 削除に伴う既存テスト更新（`skip_records` 明示渡しに）・`is_translation_needed` の `skip_records` 必須化検証（`TypeError` 確認） |
| `tests/test_config.py` | `skip_records` toml 読み込み・必須化検証・型検証（`list[str]`・各要素非空・大文字正規化）・空リスト `[]` 許可・重複除去 |
| `tests/test_cli.py` | `--no-skip-default-records` 廃止に伴うテスト削除・`--skip-records TEXT` 完全置換セマンティクスの検証・toml `skip_records` と CLI `--skip-records` の優先順位 |
| `tests/test_progress.py` | `skip_records_fingerprint` は変更無し（14 件でも既存ロジックで動くことを確認） |
| `tests/fixtures/iroiro_v05_*.toml`（6 種）+ 既存 7 種 | `skip_records` 配列を追記（必須チェックで fail しないよう） |
| `tests/fixtures/iroiro_v06_missing_skip_records.toml`（新規） | `skip_records` 欠損で `IroiroError` 検証用 |
| `tests/fixtures/iroiro_v06_custom_skip.toml`（新規・任意） | カスタム skip リスト検証用 |
| `tests/conftest.py` | `default_skip_records` fixture 追加（14 件の frozenset・テストヘルパー） |

### 9.2 テストケース ID（v0.6 で追加）

**config 周辺:**

- T158: `load_config` が `skip_records` を `frozenset[str]` で返す
- T159: `skip_records` 欠損で `IroiroError`
- T160: `skip_records` が `list` で無いと `IroiroError`
- T161: `skip_records` 要素が空文字（`""`）で `IroiroError`
- T161b: `skip_records` 要素が strip 後空文字（`"   "`）で `IroiroError`
- T161c: `skip_records` 要素が `int` / `bool` で `IroiroError`（Codex review 指摘）
- T162: `skip_records = []` は空 `frozenset` として許可
- T163: `skip_records` の大文字正規化（`hdpt:full` → `HDPT:FULL`）
- T164: `skip_records` 重複除去（`["HDPT:FULL", "HDPT:FULL"]` → 1 件）

**translator 周辺:**

- T165: `is_translation_needed(source, rec)` で `skip_records` 省略時 `TypeError`（必須引数化・§4.4）

**CLI 周辺:**

- T166a: `--skip-records` 省略時 toml の `skip_records` を使用
- T166b: `--skip-records ""` で明示的空 set（全件翻訳）
- T166c: `--skip-records "HDPT:FULL,..."` で完全置換（toml を無視）
- T166d: `--skip-records "hdpt:full"` の CLI 側正規化 + 完全置換の組み合わせ（Codex review 指摘）
- T167: `--no-skip-default-records` が未知オプションとして `SystemExit`（廃止確認）

**example / progress 周辺:**

- T168: `iroiro.toml.example` が tomllib で parse 可能（14 件 skip + 拡充 rec_hints）→ **WP-3 で追加**（example 更新が WP-3 のため・Codex review 指摘）
- T169: `progress.json` resume 時の fingerprint 検証（14 件）

### 9.3 既存テストの取扱い

- `DEFAULT_SKIP_RECORDS` を直接 import するテスト → WP-2 で signature 追随
- `--no-skip-default-records` を使う CLI テスト → 削除（廃止のため）
- skip_records 関連で 12 件を前提とするテスト → 14 件に更新

---

## 10. 実装計画

### 10.1 Work package 構成

normal タスクの推奨分割。ただし今回の特性上、toml の最終形が確定しないと docs が書けないため
**シリアル気味** に進める（WP-1 → WP-2 → WP-3）。

#### WP-1-tests

- **Goal**: 新規テスト追加・既存 fixtures 拡充
- **Owner**: implementer
- **Allowed paths**: `tests/test_*.py`, `tests/fixtures/*.toml`, `tests/conftest.py`
- **Forbidden paths**: `iroiro/*.py`, `docs/*`, `iroiro.toml.example`
- **Inputs**: 本計画書 §9 テスト戦略
- **Expected outputs**: T158-T167, T169 の新規テスト（red 状態・WP-2 完了まで）・既存 fixtures に `skip_records` 追記
  - ※ **T168 は WP-3 に移動**（`iroiro.toml.example` 更新が WP-3 のため・Codex review 指摘反映）
- **Dependencies**: なし（ただし新規テストは WP-2 完了まで red）
- **Can run in parallel**: いいえ（WP-2 の signature に依存）
- **Merge criteria**: 既存テスト green 維持・新規テスト追加（red 許容・T168 以外）・fixtures 拡充
- **Tests to run**: `uv run pytest`（既存 green 確認・新規 red 許容）
- **Docs responsibility**: なし
- **Risk**: low

#### WP-2-core

- **Goal**: `translator.py` / `config.py` / `cli.py` の実装 + **既存テストの signature 追随**（GaOTTT memory 教訓: 既存テストの signature 追随は WP-2 の最初のタスク）
- **Owner**: implementer
- **Allowed paths**: 
  - `iroiro/translator.py`, `iroiro/config.py`, `iroiro/cli.py`, `iroiro/__init__.py`
  - `tests/test_translator.py`, `tests/test_cli.py`, `tests/test_config.py`, `tests/test_progress.py`（**既存テストの signature 追随のみ**・新規テスト追加・変更は不可・T158-T169 は触らない）
- **Forbidden paths**: `tests/conftest.py`, `tests/fixtures/*`（WP-1 管轄）, `docs/*`, `iroiro.toml.example`, `iroiro/progress.py`（§4.5 で空集合特例維持のため **変更不要**・触る場合は理由をコミットメッセージに明記）
- **Inputs**: 本計画書 §4-§8・WP-1 のテスト
- **Expected outputs**: 
  - `DEFAULT_SKIP_RECORDS` 完全削除（`iroiro/translator.py:103-116`）
  - `is_translation_needed` signature 変更（`rec` / `skip_records` 共に必須・`iroiro/translator.py:119-153`）
  - `_validate_skip_records` 追加・`_VALIDATORS` 登録（`iroiro/config.py`）
  - `load_config` の必須チェック追加（`iroiro/config.py:150-160` 付近）
  - `--no-skip-default-records` 廃止・`--skip-records` を `str | None = None` + 完全置換化（`iroiro/cli.py:175-184, 231-238`）
  - `__version__` の `0.6` 更新（`iroiro/__init__.py`）
  - **既存テストの signature 追随**:
    - `tests/test_translator.py`: `DEFAULT_SKIP_RECORDS` import 削除・`is_translation_needed("Hello")` 等の呼出に `rec=""` と `skip_records=frozenset()` を明示渡し・モック signature 型宣言（22, 26 行）更新
    - `tests/test_cli.py`: `--no-skip-default-records` 使用テストの削除・`skip_records` 構築の検証テスト更新
    - ※ 新規テスト T158-T169 は触らない（WP-1/WP-3 管轄）
- **Dependencies**: WP-1 完了（テストが定義されていること）
- **Can run in parallel**: いいえ
- **Merge criteria**: 全テスト green（T158-T167, T169 含む・T168 は WP-3 まで red）・`ruff check` クリーン・`mypy iroiro` クリーン
- **Tests to run**: `uv run pytest` / `uv run ruff check iroiro/ tests/` / `uv run mypy iroiro`
- **Docs responsibility**: なし
- **Risk**: medium（signature 変更・CLI 互換性破れ）

#### WP-3-docs-handoff

- **Goal**: ドキュメント・handoff・`iroiro.toml.example` 更新・T168 テスト追加
- **Owner**: implementer
- **Allowed paths**: `iroiro.toml.example`, `README.md`, `docs/design.md`, `docs/usage.md`, `docs/development.md`, `docs/notes/translate-skip-records.md`, `docs/handoff/006-multi-game.md`, `tests/test_cli.py`（T168 追加のみ・他テスト修正禁止）
- **Forbidden paths**: `iroiro/*.py`（`__init__.py` 除く）, `tests/test_translator.py`, `tests/test_config.py`, `tests/test_progress.py`, `tests/fixtures/*`（WP-1 管轄）
- **Inputs**: WP-2 完了後の最終挙動・本計画書
- **Expected outputs**: 
  - `iroiro.toml.example`: `skip_records`（14 件）追記・`rec_hints` 拡充・ヘッダコメント更新
  - `README.md`: 「Skyrim MOD」→「Skyrim / Fallout4 / Starfield」・v0.6 の破壊的変更記述
  - `docs/design.md`: skip_records の toml 化（案 α）節追加
  - `docs/usage.md`: `--no-skip-default-records` 廃止・`--skip-records` 完全置換化・`skip_records` toml 項目・移行ガイド
  - `docs/development.md`: モジュール構成・ロードマップ（v0.6 完了）更新
  - `docs/notes/translate-skip-records.md`: v0.6 移行メモ追記
  - `docs/handoff/006-multi-game.md`: 新規 handoff
  - `tests/test_cli.py`: T168（`iroiro.toml.example` の tomllib parse 検証）追加
- **Dependencies**: WP-2 完了
- **Can run in parallel**: いいえ
- **Merge criteria**: docs と実装の整合・`iroiro.toml.example` が tomllib で parse 可能・T168 green
- **Tests to run**: `uv run pytest -k T168` または `uv run pytest tests/test_cli.py`（T168 green 確認）
- **Docs responsibility**: 全 docs + T168 テスト
- **Risk**: low

### 10.2 実装順序

1. WP-1（テスト・fixtures 拡充）
2. WP-2（実装・テスト修復）
3. WP-3（docs・handoff）
4. PM 検証（full diff inspection）
5. Codex CLI final review
6. QA final review
7. GaOTTT writeback
8. final report

---

## 11. ドキュメント影響

### 11.1 更新対象

| ファイル | 更新内容 |
|---|---|
| `iroiro.toml.example` | `skip_records`（14 件）追記・`rec_hints` 拡充・ヘッダコメント（v0.6 破壊的変更・3 ゲーム対応） |
| `README.md` | 「Skyrim MOD」→「Skyrim / Fallout4 / Starfield」・主な機能に v0.6 追加・クイックスタートの移行メモ |
| `docs/design.md` | 「skip_records の toml 化（v0.6）」節追加・制限事項の 3 ゲーム対応記述 |
| `docs/usage.md` | `--no-skip-default-records` 廃止・`--skip-records` 完全置換化（`str \| None = None` パターン）・`skip_records` toml 項目・移行ガイド・3 ゲーム対応記述・`PERK` / `AVIF` の保守的運用注記・`INFO:RNAM` が既存 custom toml に残ってもエラーではない点の移行メモ（Codex review 指摘） |
| `docs/development.md` | モジュール構成（`DEFAULT_SKIP_RECORDS` 削除等）・ロードマップ（v0.6 完了・v0.7 以降） |
| `docs/notes/translate-skip-records.md` | v0.6 移行メモ（toml 化・14 件）追記 |
| `docs/handoff/006-multi-game.md` | 新規 handoff（本計画の成果） |
| `AGENTS.md` | 必要に応じて「v0.6 での破壊的変更」追記 |

### 11.2 言語ポリシー

- 全ドキュメントの説明文は **日本語**
- 技術識別子（`skip_records` / `--skip-records` / `DEFAULT_SKIP_RECORDS` 等）は **英語のまま**
- NG ガイド（`docs/notes/xtranslator_translation_ng_guide.md`）は英語のまま維持（参照元・変更不要）

---

## 12. 引き継ぎ影響

`docs/handoff/006-multi-game.md` を新規作成。以下を記載:

- ステータス（done / done-with-notes / partial / blocked）
- 変更内容（skip_records toml 化・14 件拡充・rec_hints 拡充・CLI 廃止）
- 変更理由（3 ゲーム対応・v0.5 哲学の一貫性）
- Work packages（WP-1 / WP-2 / WP-3 の status・files・verification）
- 触ったファイル一覧
- テスト（実行コマンド・結果・未実行項目）
- ドキュメント更新状況
- 手動確認項目（実データでの `INFO:NAM1` 出現確認等）
- 既知の問題（`progress.json` fingerprint 不整合による resume 停止等）
- 残 TODO（review-needed 状態導入・プリセット機能等の将来機能）
- リスク
- ロールバックメモ
- 次の担当者へのメモ

---

## 13. 言語影響

- コードコメント・docstring: **日本語**（既存規約通り）
- ユーザー向けドキュメント: **日本語**
- 技術識別子・CLI フラグ・TOML キー: **英語**
- エラーメッセージ: **英語**（`IroiroError` のメッセージは既存英語形式を維持）
- NG ガイド（`docs/notes/xtranslator_translation_ng_guide.md`）: **英語維持**（参照元のため）

---

## 14. リスク

### 14.1 高リスク項目

- **後方互換性の破れ（複数）**: 
  - `DEFAULT_SKIP_RECORDS` 定数削除（外部コードが import している場合壊れる）
  - `--no-skip-default-records` 廃止（既存ユーザーのスクリプトが壊れる）
  - `--skip-records` セマンティクス変更（追加→置換）
  - `iroiro.toml` に `skip_records` が必須（既存 toml に追記必要）
  - `progress.json` fingerprint 不整合（resume 時停止）
- **移行コスト**: 既存ユーザーは `iroiro.toml` に `skip_records` を追記する必要

### 14.2 低リスク項目

- XML 安全性中核（`xml_io.py`）は触らない
- 並行安全性（`progress.py` の Lock 機構）は触らない
- プレースホルダ保護（`escape.py`）は触らない
- LLM クライアント（`translator.py` の `Translator` クラス）は触らない

### 14.3 軽減策

- `iroiro.toml.example` に 14 件のデフォルトを予め記載（`cp` で即動作）
- `docs/usage.md` に移行ガイドを明記
- `progress.json` fingerprint 不整合は「仕様通りの安全側挙動」として文書化
- Codex CLI final review で後方互換性の破れを網羅的に確認

---

## 15. 受け入れ基準

- [ ] `DEFAULT_SKIP_RECORDS` が `iroiro/translator.py` から完全削除されている
- [ ] `is_translation_needed` が `skip_records` 必須引数になっている
- [ ] `iroiro.toml` の `skip_records` が必須（欠損で `IroiroError`）
- [ ] `_validate_skip_records` が `frozenset[str]` を返す
- [ ] `--no-skip-default-records` フラグが削除されている
- [ ] `--skip-records` が `str | None = None` パターンで 3 状態（省略=toml / `""`=空set / 非空=置換）を区別する
- [ ] `is_translation_needed` が `source, rec, skip_records` 全て必須引数になっている
- [ ] `iroiro.toml.example` に 14 件の `skip_records` が記載されている
- [ ] `iroiro.toml.example` の `[iroiro.rec_hints]` が §7.1 の内容になっている
- [ ] `uv run pytest` が全件 green（T158-T169 含む）
- [ ] `uv run ruff check iroiro/ tests/` がクリーン
- [ ] `uv run mypy iroiro` がクリーン
- [ ] `iroiro.toml.example` が tomllib で parse 可能
- [ ] `README.md` / `docs/*.md` が 3 ゲーム対応・v0.6 破壊的変更を記載
- [ ] `docs/handoff/006-multi-game.md` が作成されている
- [ ] Codex CLI final review が pass（blocking issues 無し）
- [ ] QA final review が pass（release blockers 無し）

---

## 16. Codex CLI review points

### 16.1 計画書 review（本フェーズ）

以下を確認:

- 案 α の適用が v0.5 哲学と整合しているか
- `--no-skip-default-records` 廃止が妥当か（代替手段でユーザー不便が無いか）
- `--skip-records ""` のセマンティクス（§8.1）の判断
- skip リスト 14 件が NG ガイド §9.1 と整合しているか
- rec_hints 拡充が NG ガイド §4 を網羅しているか
- skip リストと rec_hints の重複ゼロが妥当か
- `INFO:RNAM` → `INFO:NAM1` の置換が妥当か
- テスト戦略（T158-T169）が網羅的か
- Work package 分割が v0.5 の教訓（GaOTTT memory）を反映しているか
- 後方互換性の破れが全て文書化されているか

### 16.2 最終 diff review（実装後）

以下を確認:

- 上記 16.1 の全項目が実装に反映されているか
- `DEFAULT_SKIP_RECORDS` がコードから完全削除されているか（残参照無し）
- `is_translation_needed` の signature 変更が呼出側全てに反映されているか
- `_validate_skip_records` が `reject_phrases` validator と対称的な厳格性か
- テスト weakning / skip が無いか
- docs と実装の乖離が無いか
- 言語ポリシー（日本語説明文・英語識別子）が守られているか

### 16.3 計画書 Codex review 履歴

**1 回目（2026-06-29）: fail → 修正済み**

Blocking issues（3）と修正:

1. `--skip-records ""` のセマンティクス矛盾 → §4.3 で `str | None = None` パターン採用（Codex 推奨案）に確定。`None`=toml使用 / `""`=明示的空set / 非空=完全置換。
2. `is_translation_needed` の signature 曖昧 → §4.4 で `rec` も必須化（案 a 採用）に確定。
3. WP-1 と T168 の順序矛盾 → T168 を WP-3 に移動（example 更新が WP-3 のため）。

Non-blocking issues（4）と対応:

- EDID 扱いの docs 表現 → §6 で「EDID を除く Conservative skip list」に修正
- `PERK` / `AVIF` の扱い揺れ → §7.4 に注記追加・docs 更新対象に追加
- `INFO:RNAM` が既存 toml 残存時の非エラー → §11.1 docs 更新対象に移行メモ追記
- WP-2 の `progress.py` → 「変更不要・触る場合は理由明記」に明確化

Missing tests（5）を追加: T161b / T161c / T166a / T166b / T166c / T166d（§9.2 参照）。

**修正は Codex 推奨案そのものであるため、implementer 委譲に進む。最終 diff review で全体を再確認する。**

---

## 17. 関連資料

- [NG ガイド](../notes/xtranslator_translation_ng_guide.md) — 3 ゲーム対応のコーディングガイド（本計画の根拠）
- [Plan 005](005-llm-config.md) — v0.5 LLM 挙動中核の toml 化（案 α の先例）
- [設計判断](../design.md) — 既存の設計判断（skip リスト・fingerprint 等）
- [実装計画 002](002-skip-records.md) — v0.2 skip リスト導入の経緯
- [開発者向け](../development.md) — ロードマップ・モジュール構成
