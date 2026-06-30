# 引き継ぎメモ: iroiro-translator v0.6 Fallout4 / Starfield 対応 + skip_records の toml 化 (006-multi-game)

- 作成日: 2026-06-30
- 計画書: [`docs/plans/006-multi-game.md`](../plans/006-multi-game.md)
- 状態: **done-with-notes**

---

## ステータス

| 項目 | 値 |
|---|---|
| 状態 | done-with-notes |
| 日付 | 2026-06-30 |
| リスク分類 | `normal`（後方互換性を破るが、ユーザー承認済み・影響範囲は明示的） |
| バージョン | v0.6（`__version__ = "0.6.0"`） |
| 前バージョン | v0.5（LLM 挙動中核の完全 toml 化） |
| 担当 | PM + implementer（WP-1 テスト / WP-2 実装 / WP-3 ドキュメント・handoff） |
| テスト | 208 passed（+17: T158-T167, T169・既存 fixtures 拡充・T168 は本 WP で追加） |
| ruff | clean |
| mypy | clean |
| example parse | OK（`tomllib.load` 成功） |
| 概要 | v0.6 で `DEFAULT_SKIP_RECORDS` 定数を `iroiro/translator.py` から **完全削除** し、`iroiro.toml` の `skip_records`（必須）に移行（案 α 徹底版・v0.5 と同じ哲学）。skip リストを 12件 → **14件** に拡充（`FLST:FULL` / `KYWD:FULL` 追加）。`[iroiro.rec_hints]` を NG ガイド §4 に基づき 3 ゲーム共通の翻訳候補レコードに拡充。CLI `--no-skip-default-records` 廃止・`--skip-records` を完全置換セマンティクスに変更。**後方互換性の破れ**: 既存 `iroiro.toml` に `skip_records` 追記必要・`progress.json` fingerprint 不整合で resume 停止。 |

---

## 変更内容

v0.6 は **後方互換性を破る** 変更。v0.5 の「LLM 挙動中核の完全 toml 化（案 α）」と同じ哲学を
`skip_records` に拡張し、Skyrim / Fallout4 / Starfield の 3 ゲーム対応を実現した。

### 機能サマリ

1. **`skip_records` toml 必須化**（案 α 徹底版）— `DEFAULT_SKIP_RECORDS` 定数を `iroiro/translator.py` から完全削除し、`iroiro.toml` の `[iroiro] skip_records`（`list[str]`）を必須化。各要素は `strip().upper()` で大文字正規化・重複は `frozenset` 化で除去。空リスト `[]` は許可（全件翻訳）。欠損で `IroiroError`。
2. **skip リスト 14 件拡充** — v0.5 までの 12 件に `FLST:FULL`（FormID List）/ `KYWD:FULL`（Keyword）を追加。根拠は NG ガイド §9.1 Conservative Preset（EDID 抜き）。3 ゲーム共通の内部管理用レコード。
3. **`[iroiro.rec_hints]` 拡充** — NG ガイド §4「Usually Safe Translation Targets」に基づき、3 ゲーム共通の翻訳候補レコード（`INFO:NAM1` / `AMMO:FULL` / `MISC:FULL` / `WRLD:FULL` / `PERK:FULL` / `AVIF:FULL` 等）を追加。skip リストと重複する `FACT:FULL` / `RACE:FULL` / `CLAS:FULL` / `MGEF:FULL` は除外（`MGEF:DESC` は維持）。`INFO:RNAM` は `INFO:NAM1` に置換（NG ガイド §4 標準・計画書 §4.7）。
4. **CLI `--no-skip-default-records` 廃止** — `DEFAULT_SKIP_RECORDS` 定数がコードから消えたため意味を成さない。代替手段: `--skip-records ""`（明示的空 set = 全件翻訳）か `iroiro.toml` で `skip_records = []`。
5. **CLI `--skip-records` 完全置換セマンティクス化** — v0.5 までの「DEFAULT への追加」から `str | None = None` パターン（3 状態: 省略=toml使用 / `""`=空set / 非空=完全置換）に変更。v0.5 の `retry_failed` と同形式（Codex review 採用案）。
6. **`is_translation_needed` の全引数必須化** — `skip_records` の `None` フォールバック削除・`rec` も必須化（`def is_translation_needed(source, rec, skip_records)`・計画書 §4.4）。省略時は `TypeError`（意図的・暗黙フォールバックを許さない）。

### 行動変更（破壊的）

- **`iroiro.toml` に `skip_records` が無い** → `IroiroError("[iroiro] skip_records is required in <path>")`
- **`--no-skip-default-records` 指定** → Typer が未知オプションとして弾く（非ゼロ exit code）
- **`--skip-records` のセマンティクス変更** — v0.5 で `--skip-records "LCTN:FULL"` は「DEFAULT12件 + LCTN:FULL」（13件）だったが、v0.6 では「LCTN:FULL のみ」（1件）になる（完全置換）
- **`progress.json` fingerprint 不整合** — v0.5 までの `progress.json`（12件 fingerprint）を v0.6 で `--resume` すると停止（14件に変更のため・安全側の挙動）

### 削除

| 旧要素 | 場所 | 新しい注入元 |
|---|---|---|
| `DEFAULT_SKIP_RECORDS` 定数 | 旧 `iroiro/translator.py:103-116` | `iroiro.toml` の `[iroiro] skip_records` |
| `--no-skip-default-records` フラグ | 旧 `iroiro/cli.py` | 廃止（代替: `--skip-records ""` または `skip_records = []`） |

---

## 変更理由

### 3 ゲーム対応（主目的の一つ）

Fallout4 / Starfield MOD も xTranslator 形式 XML（`SSTXMLRessources` v2）を採用しており、
iroiro で翻訳可能にする需要があった。skip リスト・rec_hints を 3 ゲーム共通の NG ガイド
（`docs/notes/xtranslator_translation_ng_guide.md`）に基づき整備した。

### v0.5 哲学の一貫性（案 α 徹底版）

v0.5 は「LLM 挙動中核（`system_prompt` / `reject_phrases` / `[iroiro.rec_hints]`）のコード内
ハードコードを完全削除し toml 必須化」を採用した。本 v0.6 の「`DEFAULT_SKIP_RECORDS` も案 α で
toml 必須化」は v0.5 の哲学を `skip_records` に拡張するもので、プロジェクト全体の一貫性を高める
（計画書 §2.3）。配布物（`pip install` / `uv tool install`）状態でユーザーがリストを編集できない
問題も解決する。

### Codex review での確定事項

計画書 Codex review（1回目・2026-06-29）で 3 つの blocking issues を解決済み（計画書 §16.3）:

1. `--skip-records ""` のセマンティクス矛盾 → `str | None = None` パターン（3 状態）採用
2. `is_translation_needed` の signature 曖昧 → `rec` も必須化（案 a 採用）
3. WP-1 と T168 の順序矛盾 → T168 を WP-3 に移動

---

## Work packages

### WP-1-tests（✅ 完了）

| 項目 | 値 |
|---|---|
| Goal | 新規テスト追加・既存 fixtures 拡充 |
| Status | done |
| Files | `tests/test_config.py`（T158-T164）/ `tests/test_translator.py`（T165）/ `tests/test_cli.py`（T166a-T167）/ `tests/test_progress.py`（T169）/ `tests/conftest.py`（`default_skip_records` fixture・14件）/ `tests/fixtures/iroiro_v05_*.toml`（6種）+ 既存 7種 に `skip_records` 追記 / `tests/fixtures/iroiro_v06_missing_skip_records.toml`・`iroiro_v06_custom_skip.toml`（新規） |
| Verification | 新規テスト追加（WP-2 完了まで red 許容）・既存 fixtures に `skip_records` 追記で必須チェック回避 |

### WP-2-core（✅ 完了）

| 項目 | 値 |
|---|---|
| Goal | `translator.py` / `config.py` / `cli.py` の実装 + 既存テストの signature 追随 |
| Status | done |
| Files | `iroiro/translator.py`（`DEFAULT_SKIP_RECORDS` 完全削除・`is_translation_needed` の `skip_records` 必須化）/ `iroiro/config.py`（`_validate_skip_records` 追加・`_VALIDATORS` 登録・必須チェック）/ `iroiro/cli.py`（`--no-skip-default-records` 廃止・`--skip-records` を `str \| None = None` の完全置換化）/ `iroiro/__init__.py`（`__version__ = "0.6.0"`）/ 既存テストの signature 追随（`tests/test_translator.py`・`tests/test_cli.py`・`tests/test_config.py`） |
| Verification | `uv run pytest`（T158-T167, T169 green・T168 は WP-3 まで red）・`uv run ruff check iroiro/ tests/` clean・`uv run mypy iroiro` clean |
| Notes | `iroiro/progress.py` は §4.5 で空集合特例維持のため **変更不要**（触っていない） |

### WP-3-docs-handoff（✅ 完了・本 WP）

| 項目 | 値 |
|---|---|
| Goal | ドキュメント・handoff・`iroiro.toml.example` 更新・T168 テスト追加 |
| Status | done |
| Files | `iroiro.toml.example`（`skip_records` 14件追記・`rec_hints` §7.1 内容で完全置換・ヘッダコメント v0.6 破壊的変更追記）/ `README.md`（3 ゲーム対応・v0.6 破壊的変更・Plan 006 / handoff 006 追記）/ `docs/design.md`（「skip_records の toml 化（v0.6）」節追加）/ `docs/usage.md`（CLI 表更新・`skip_records` toml 項目・v0.6 移行ガイド・3 ゲーム対応・`PERK`/`AVIF` 注記・`INFO:RNAM` 移行メモ・「翻訳スキップ REC 型（v0.2 / v0.6）」節全面更新）/ `docs/development.md`（モジュール構成・テスト数 208・fixtures 説明・ロードマップ v0.6 完了）/ `docs/notes/translate-skip-records.md`（v0.6 移行メモ追記）/ `docs/handoff/006-multi-game.md`（本ファイル・新規）/ `tests/test_cli.py`（T168 追加のみ） |
| Verification | `uv run pytest`（T155 / T168 green・全 208 green）・`uv run ruff check iroiro/ tests/` clean・`uv run mypy iroiro` clean・`iroiro.toml.example` の `tomllib.load` 成功 |

---

## 触ったファイル一覧

### WP-3 で触ったファイル（本 WP）

| ファイル | 変更内容 |
|---|---|
| `iroiro.toml.example` | ヘッダを `(v0.3 / v0.4 / v0.5 / v0.6)` に更新。v0.6 の破壊的変更（`skip_records` 必須化・`--no-skip-default-records` 廃止・`--skip-records` セマンティクス変更・3 ゲーム対応・`progress.json` fingerprint 不整合）を追記。`[iroiro]` セクションに `skip_records`（14件）を追記。`[iroiro.rec_hints]` を計画書 §7.1 の内容で完全置換（`INFO:RNAM` → `INFO:NAM1`・`AMMO:FULL` / `MISC:FULL` / `WRLD:FULL` 等 追加・skip リストと重複する `FACT:FULL` / `RACE:FULL` / `CLAS:FULL` / `MGEF:FULL` は除外） |
| `README.md` | 1 行目「Skyrim MOD の」→「Skyrim / Fallout4 / Starfield MOD の」。主な機能に v0.6 の破壊的変更追記。ドキュメント一覧に Plan 006 / handoff 006 追記 |
| `docs/design.md` | 「skip_records の toml 化（v0.6）」節を新規追加（案 α の理由・14 件拡充・CLI セマンティクス変更・3 ゲーム対応・skip と rec_hints の重複ゼロ・`PERK`/`AVIF` 注記・`INFO:RNAM` 整理） |
| `docs/usage.md` | CLI フラグ一覧表の `--no-skip-default-records` 行を削除・`--skip-records` 行を 3 状態セマンティクスに更新。v0.6 破壊的変更の注記追記。TOML 例に `skip_records` 追記。「各項目の意味」に「翻訳スキップ REC 型（v0.6 新規・必須）」節追加。エラーメッセージ表に `skip_records is required` 追加。「skip_records の toml 必須化と移行（v0.6）」節を新規追加（影響範囲・移行手順・`--no-skip-default-records` 廃止と代替・`--skip-records` セマンティクス変更・`progress.json` fingerprint 不整合・3 ゲーム対応・`PERK`/`AVIF` 保守的運用・`INFO:RNAM` 移行メモ）。「翻訳スキップ REC 型（v0.2 / v0.6）」節を全面更新（14件・完全置換セマンティクス）。再開節の fingerprint 言及更新。rec_hints カスタマイズ例の `INFO:RNAM` → `INFO:NAM1` |
| `docs/development.md` | モジュール構成の `translator.py` / `config.py` / `cli.py` 説明に v0.6 変更追記。テスト数を 208 に更新。fixtures 説明に v0.6 追加分（`iroiro_v06_*`・既存 13 fixtures に `skip_records` 追記）を追記。ロードマップの v0.6 を「✅ 完了」に変更・v0.7 以降のロードマップから「`skip_records` の `iroiro.toml` 化」を削除・代わりに「`--game` ゲーム選択機能」「review-needed 状態」を将来機能として明記 |
| `docs/notes/translate-skip-records.md` | ステータス行に「v0.6 で toml 化・14 件に拡充」追記。v0.6 移行メモ節を新規追加。原本の v0.2 12 件リストは歴史記録として残し v0.6 注記を付加 |
| `docs/handoff/006-multi-game.md` | 新規作成（本ファイル） |
| `tests/test_cli.py` | T168（`iroiro.toml.example` の v0.6 内容検証・14件 skip_records + §7.1 主要 rec_hints + skip と rec_hints の重複ゼロ + `load_config` で `frozenset[str]` 14件）を追加。**既存テストは触っていない** |

### WP-1 / WP-2 で触ったファイル（参考・本 WP では触っていない）

- `iroiro/translator.py` / `iroiro/config.py` / `iroiro/cli.py` / `iroiro/__init__.py`（WP-2）
- `tests/test_config.py` / `tests/test_translator.py` / `tests/test_progress.py`（WP-1・WP-2 で signature 追随）
- `tests/conftest.py`（WP-1・`default_skip_records` fixture 追加）
- `tests/fixtures/iroiro_v05_*.toml`（6種）+ 既存 7種 + `tests/fixtures/iroiro_v06_*.toml`（2種・WP-1）

---

## テスト

### 実行コマンド

```bash
uv run pytest                          # 全テスト（208件）
uv run pytest tests/test_config.py::test_T155_example_file_parses_and_loads  # T155 個別
uv run pytest tests/test_cli.py::test_T168_example_contains_v06_skip_records_and_rec_hints  # T168 個別
uv run ruff check iroiro/ tests/       # lint
uv run mypy iroiro                     # 型チェック
uv run python -c "import tomllib; tomllib.load(open('iroiro.toml.example','rb')); print('parse OK')"  # example parse
```

### 結果

- **`uv run pytest`**: 208 passed（v0.5 の 207 件 + T168 の 1 件）
- **T155**: green（`iroiro.toml.example` に `skip_records` が含まれるため・本 WP で解決）
- **T168**: green（新規追加・`iroiro.toml.example` が 14件 skip + §7.1 拡充 rec_hints を含むため・本 WP で追加・green 化）
- **`uv run ruff check iroiro/ tests/`**: clean
- **`uv run mypy iroiro`**: clean
- **example parse**: OK

### T155 / T168 の WP-3 解決の経緯

- WP-1 完了時点では `iroiro.toml.example` が v0.5 形式（`skip_records` 無し）のままだったため、T155 は `IroiroError("[iroiro] skip_records is required")` で red だった。
- WP-3（本 WP）で `iroiro.toml.example` に `skip_records`（14件）を追記したことで T155 が green 化。
- T168 は計画書 §9.2 で WP-3 管轄と明記されていたため、本 WP で新規追加。T155（v0.5 由来・`load_config` 全体が通ることの検証）と T168（v0.6 新規・14件 skip + 拡充 rec_hints の内容検証）は同じ `iroiro.toml.example` を使うが検証粒度が異なる。

### 未実行項目

- **実 LLM での E2E テスト**: CI 上では実施せず（v0.1 と同じ方針）。ユーザー環境での手動検証に委ねる（後述「手動確認項目」）。
- **実データ（Fallout4 / Starfield MOD XML）での検証**: サンプル XML が第三者著作物で git 管理外のため、本 WP では実施不可。ユーザー環境での手動検証を期待。

---

## ドキュメント更新状況

| ファイル | 更新状況 | 備考 |
|---|---|---|
| `iroiro.toml.example` | ✅ 更新 | `skip_records` 14件・`rec_hints` §7.1・ヘッダ v0.6 破壊的変更 |
| `README.md` | ✅ 更新 | 3 ゲーム対応・v0.6 破壊的変更・Plan 006 / handoff 006 |
| `docs/design.md` | ✅ 更新 | 「skip_records の toml 化（v0.6）」節追加 |
| `docs/usage.md` | ✅ 更新 | CLI 表・TOML 例・各項目の意味・エラー表・v0.6 移行ガイド・翻訳スキップ REC 型節・全面更新 |
| `docs/development.md` | ✅ 更新 | モジュール構成・テスト数・fixtures・ロードマップ |
| `docs/notes/translate-skip-records.md` | ✅ 更新 | v0.6 移行メモ追記 |
| `docs/handoff/006-multi-game.md` | ✅ 新規作成 | 本ファイル |
| `AGENTS.md` | ✅ 更新 | v0.6 一貫性向上（3 ゲーム対応・LLM 挙動中核節の v0.5/v0.6 拡張・skip_records 同時更新ルール・参考ドキュメント追記） |
| `docs/plans/006-multi-game.md` | （触っていない） | PM 作成済み・参照元 |
| `docs/notes/xtranslator_translation_ng_guide.md` | （触っていない） | 参照元・英語維持 |

### AGENTS.md の更新内容

`AGENTS.md` の v0.6 一貫性向上のため以下を更新した:

- プロジェクト概要を 3 ゲーム対応（Skyrim / Fallout4 / Starfield）化
- 「LLM 挙動中核のデフォルト値編集時（v0.5）」節を（v0.5 / v0.6）に拡張し、`skip_records` と `tests/conftest.py` の `default_skip_records` fixture・`tests/test_cli.py` の T168 との整合ルールを明記
- 「触ってはいけないもの」表の `iroiro.toml` 記述に v0.6 `skip_records` を追記
- ディレクトリ構成の注記に v0.6 `skip_records` 必須化を追記
- 参考ドキュメント一覧に Plan 006 / handoff 006 を追記

---

## 手動確認項目

本 WP では実施していないが、リリース前にユーザー環境で確認すべき項目:

### 実データでの `INFO:NAM1` 出現確認

計画書 §4.7 で `INFO:RNAM` → `INFO:NAM1` に置換したが、「実データでの `INFO:RNAM` 出現有無」は
サンプル XML が git 管理外のため未確認。xTranslator が生成する Skyrim / Fallout4 / Starfield の
XML で `INFO:NAM1` が主流であることを確認することが望ましい:

```bash
# ユーザー環境での確認例:
grep -c "INFO:NAM1" your_mod.xml
grep -c "INFO:RNAM" your_mod.xml
```

`INFO:RNAM` が多数出現する場合は、`iroiro.toml` の `[iroiro.rec_hints]` に `INFO:RNAM` を
追加することを検討する（未知 REC キーとして WARNING 無しで許可される）。

### Fallout4 / Starfield 実データでの検証

skip リスト 14 件と拡充 `rec_hints` が 3 ゲームで意図通り動作することを確認:

- Fallout4 MOD XML で `AMMO:FULL` / `MISC:FULL` が翻訳対象になること
- Starfield MOD XML で `WRLD:FULL` が翻訳対象になること
- 3 ゲーム共通で `FLST:FULL` / `KYWD:FULL` がスキップされること

### v0.5 からの移行確認

- 既存 `iroiro.toml` に `skip_records`（14件）を追記して `--dry-run` が通ること
- v0.5 までの `progress.json` を削除して `--resume` し直すこと（fingerprint 不整合回避）

---

## 既知の問題

### `progress.json` fingerprint 不整合による resume 停止（仕様通り・安全側）

v0.5 までの `progress.json`（12件の `skip_records_fingerprint`）を v0.6 で `--resume` すると、
14件に変更されたため fingerprint 不一致で停止する。これは `input_hash` 不一致と同じ
「安全側の挙動」（仕様通り）。ユーザーは `progress.json` を削除して再実行する必要がある。

```bash
rm path/to/your_mod.xml.iroiro-progress.json
```

本挙動は `docs/usage.md` の「skip_records の toml 必須化と移行（v0.6）」節と
「翻訳スキップ REC 型（v0.2 / v0.6）」節で文書化済み。

### `INFO:RNAM` が既存カスタム toml に残存してもエラーではない

v0.5 までの `iroiro.toml.example` に含まれていた `INFO:RNAM` は v0.6 で `INFO:NAM1` に置換されたが、
既存ユーザーのカスタム `iroiro.toml` に `INFO:RNAM` が残っていてもエラーにならない
（未知 REC キーは WARNING 無しで許可・v0.5 仕様）。意味的に重複するため必要に応じて
`INFO:NAM1` に置き換えることを推奨（`docs/usage.md` に移行メモを記載）。

### `PERK` / `AVIF` の扱いの揺れ（NG ガイド内）

`PERK:FULL` / `PERK:DESC` / `AVIF:FULL` は NG ガイド内で §4（safe target）と §5（review-needed）の
両方に登場する。iroiro は review-needed 状態を持たないため §4 に従い翻訳候補（`rec_hints` 採用）
としたが、保守的運用では `skip_records` への追加を検討する必要がある
（`docs/usage.md` / `docs/design.md` に注記を記載）。

---

## 残 TODO（将来機能・v0.6 ではスコープ外）

以下は計画書 §3.2 で「非スコープ（ユーザー承認済み）」とした項目。v0.7 以降で検討:

- **review-needed 状態の導入** — iroiro は `translate` / `skip` の 2 状態だが、NG ガイド §5
  Review-Needed List（`OMOD:FULL` / `COBJ:*` / `PERK:FULL` / `AVIF:FULL` / `GMST:*` /
  `LSCR:*` / `TERM:*` 等）を扱うための第 3 状態。
- **`--game skyrim|fallout4|starfield` ゲーム選択機能** — ゲーム別の skip リスト / rec_hints
  プリセット切り替え（Conservative / Translation-Friendly / Starfield-Friendly）。
  v0.6 では 3 ゲーム共通デフォルトのみ提供。
- **プリセット機能** — Conservative / Translation-Friendly / Starfield-Friendly の
  skip リスト / rec_hints プリセットを `iroiro.toml` または `--preset` で切り替え。
- **`system_prompt` の汎用化** — 現在の `iroiro.toml.example` の `system_prompt` は
  「Skyrim MOD の英文を…」で始まっている。Fallout4 / Starfield にも対応する汎用表現に
 するかは別件（必要なら別タスク）。
- その他: `max_tokens` 設定・接続設定 6 項目の必須化検討・用語集機能・長文 BOOK の自動分割・
  実 LLM での品質レビュー用 diff 出力・`SSTXMLRessources` v3 / `Interface/*.txt` 対応・
  `iroiro.toml` の親ディレクトリ遡り探索・選択的リトライ

---

## リスク

### 高リスク項目（既知・文書化済み）

- **後方互換性の破れ（複数）**:
  - `DEFAULT_SKIP_RECORDS` 定数削除（外部コードが import している場合壊れる）
  - `--no-skip-default-records` 廃止（既存ユーザーのスクリプトが壊れる）
  - `--skip-records` セマンティクス変更（追加→置換・v0.5 と意味が変わる）
  - `iroiro.toml` に `skip_records` が必須（既存 toml に追記必要）
  - `progress.json` fingerprint 不整合（resume 時停止）
- **移行コスト**: 既存ユーザーは `iroiro.toml` に `skip_records` を追記する必要

### 軽減策（実施済み）

- `iroiro.toml.example` に 14 件のデフォルトを予め記載（`cp` で即動作）
- `docs/usage.md` に移行ガイドを明記（影響範囲・移行手順・代替手段）
- `progress.json` fingerprint 不整合は「仕様通りの安全側挙動」として文書化
- 計画書 Codex review（1回目）で blocking issues を解決済み

### 低リスク項目（触っていない中核）

- XML 安全性中核（`xml_io.py`）は触っていない
- 並行安全性（`progress.py` の Lock 機構）は触っていない（§4.5 で空集合特例維持・変更不要）
- プレースホルダ保護（`escape.py`）は触っていない
- LLM クライアント（`translator.py` の `Translator` クラス）は触っていない

---

## ロールバックメモ

v0.6 への移行で問題が発生した場合のロールバック手順:

### v0.5 への一時的な戻し

1. `iroiro.toml` の `skip_records` 行を削除（またはコメントアウト）
2. v0.5 の `iroiro` パッケージを再インストール: `uv sync` で `iroiro/__init__.py` の
   `__version__` が `0.5.x` のコミットに戻す
3. v0.6 で作成した `progress.json` があれば削除（fingerprint 値が v0.5 と異なるため）

### 部分的な戻し（v0.6 のまま特定の skip リストを使う）

`iroiro.toml` の `skip_records` を v0.5 と同じ 12 件にすれば、`--resume` 時の fingerprint
不一致は回避できる（ただし v0.5 までの `progress.json` と fingerprint が一致する必要がある）:

```toml
skip_records = [
  "HDPT:FULL", "FURN:FULL", "CLAS:FULL", "DOOR:FULL",
  "FACT:FULL", "CLFM:FULL", "TREE:FULL", "MGEF:FULL",
  "RACE:FULL", "EXPL:FULL", "HAZD:FULL", "BPTD:BPTN",
  # v0.6 の FLST:FULL / KYWD:FULL を含めない（v0.5 互換）
]
```

---

## 次の担当者・エージェントへのメモ

### v0.6 リリース後の運用上の注意

1. **ユーザーサポート**: v0.5 からのアップグレードで「`skip_records is required` エラー」に
   遭遇するユーザーが多いと想定される。`docs/usage.md` の「skip_records の toml 必須化と移行（v0.6）」節を案内すること。
2. **`--skip-records` セマンティクス変更の周知**: v0.5 までの「追加」から「完全置換」に変わった
   ため、既存のスクリプトで `--skip-records "LCTN:FULL"` 等を使っているユーザーは挙動が変わる。
   移行ガイドを案内すること。
3. **`progress.json` fingerprint 不整合**: resume 時の停止が「仕様通り・安全側」であることを
   ユーザーに説明できるようにしておくこと。

### v0.7 以降の開発への引き継ぎ

- **review-needed 状態導入** を検討する場合、本 v0.6 の skip リストと rec_hints の分離設計が
  基盤になる。NG ガイド §5 Review-Needed List を第 3 状態としてどう扱うかが論点。
- **`--game` ゲーム選択機能** を検討する場合、本 v0.6 の 3 ゲーム共通デフォルトをベースに
  ゲーム別の差分（Fallout4 では `MGEF:FULL` が翻訳候補 等）をプリセット化する方向になる。
- **`system_prompt` の汎用化** は本 v0.6 ではスコープ外としたが、Fallout4 / Starfield ユーザーが
  増えた場合は「MOD の英文を日本語に翻訳する」等の汎用表現に変更する需要が出る可能性がある。

### テスト・CI の継続保証

- **T155 / T168** が `iroiro.toml.example` の構文 / 内容の回帰防止を担う。`iroiro.toml.example` を
  編集する際は必ず両テストを通すこと。
- `iroiro.toml.example` の `skip_records` / `rec_hints` を編集する場合は、T168 の
  `expected_records` / `required_hints` との整合を確認すること（T168 が example の内容と
  実装を拘束する・CI での構文検証の役割）。
- **軽微な docs 整理（任意・Codex final review non-blocking 指摘）**: `tests/test_cli.py` の
  module docstring（23-28 行・40 行）に v0.5 時代の `--no-skip-default-records` 記述が残っている。
  実装・テスト挙動には影響しないが、後続タスクで整理する場合は追従推奨。

### 関連資料

- [Plan 006](../plans/006-multi-game.md) — 本 v0.6 の設計判断・却下代替案の経緯
- [NG ガイド](../notes/xtranslator_translation_ng_guide.md) — 3 ゲーム対応のコーディングガイド（英語・参照元）
- [Plan 005](../plans/005-llm-config.md) — v0.5 LLM 挙動中核の toml 化（案 α の先例）
- [設計判断](../design.md) — 「skip_records の toml 化（v0.6）」節
- [詳細な使い方](../usage.md) — 「skip_records の toml 必須化と移行（v0.6）」節・「翻訳スキップ REC 型（v0.2 / v0.6）」節
