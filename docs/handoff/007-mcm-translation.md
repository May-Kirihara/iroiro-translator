# 引き継ぎメモ: iroiro-translator v0.7 Skyrim MCM 翻訳 TXT 対応 (007-mcm-translation)

- 作成日: 2026-07-02
- 計画書: [`docs/plans/007-mcm-translation.md`](../plans/007-mcm-translation.md)
- 状態: **done-with-notes**

---

## ステータス

| 項目 | 値 |
|---|---|
| 状態 | done-with-notes |
| 日付 | 2026-07-02 |
| リスク分類 | `normal`（新機能追加・既存 XML `translate` パスには破壊的変更無し） |
| バージョン | v0.7（機能面・ドキュメント・`iroiro/__init__.py.__version__` = `"0.7.0"` 全て v0.7 に更新済み・follow-up で bump 完了） |
| 前バージョン | v0.6（Fallout4 / Starfield 対応 + skip_records の toml 化） |
| 担当 | PM + implementer（WP-1 テスト / WP-2 実装 / WP-3 ドキュメント・handoff・本 WP） |
| テスト | 246 passed（+38: T-MCM-01〜T-MCM-RESUME / T-ESC-N1〜N5 / T-CLI-MCM-01〜05, HELP, SKIP-RECORDS-REJECTED, MAXCHARS-ZERO・新規 fixtures `mcm_tiny.txt` / `mcm_lf.txt`） |
| ruff | clean（`All checks passed!`） |
| mypy | clean（`Success: no issues found in 12 source files`） |
| smoke test | OK（`uv run iroiro mcm sample/daymoyl_ENGLISH.txt --dry-run` → 216 entries parse・`BOM=True, newline='\r\n', encoding=utf-16-le`） |
| 概要 | v0.7 で **Skyrim MCM（Mod Configuration Menu）翻訳 TXT** 形式に対応。`iroiro mcm INPUT.txt` サブコマンドで SkyUI MCM 翻訳ファイル（`*_ENGLISH.txt` 系・UTF-16 LE + BOM）の値を英→日翻訳。新モジュール `iroiro/mcm_io.py`（`parse_mcm` / `serialize_mcm` / `McmFormat`）・`escape.py` 共有 regex に `{0}` `{1}` 等の数値プレースホルダ保護を追加。**既存 XML `translate` パスは1行も変更せず回帰ゼロ**（サブコマンド分離）。 |

---

## 変更内容

v0.7 は **新機能追加** で、既存 XML `translate` パスに破壊的変更は無い。
MCM TXT パイプラインは XML パイプラインと **エントリモデル（`StringEntry`）と翻訳エンジン
（`Translator`）を共有** し、I/O（`parse_mcm` / `serialize_mcm`）と CLI エントリポイント（`mcm` サブコマンド）だけが異なる。

### 機能サマリ

1. **`iroiro mcm` サブコマンド**（`iroiro/cli.py`）— `translate` と共通のオプションを持つが、`--skip-records` は **無い**（MCM に REC 概念無し・指定すると typer が `No such option: --skip-records` exit 2 で拒否）。出力デフォルトは `<input>.translated.txt`（`.translated.xml` でない・`_default_mcm_output_path` で専用化）。
2. **`iroiro/mcm_io.py` 新規**（`parse_mcm` / `serialize_mcm` / `McmFormat` dataclass）— MCM TXT の I/O。エンコーディング判定（UTF-16 LE / UTF-16 BE / UTF-8 BOM / UTF-8）・支配的改行判定・末尾改行判定・行モデル（passthrough 行と entry 参照）。
3. **`iroiro/escape.py` 拡張** — `PROTECTED_TOKENS_RE` に `\{\d+\}`（`{0}` `{1}` 等・Skyrim GlobalVariable 置換）を追加。共有 regex への追加で XML / MCM 両方で保護（安全バイアス・`{{0}}` 過剰マッチは受容）。
4. **skip/fail 時の値保護**（`original_dest = source`）— MCM エントリは英文値そのものを `original_dest` に設定。skip/fail 時の出力値が英文のまま（空にならない・data-loss 無し・Codex review blocking fix）。

### 出力形式（フォーマット保存 + 改行正規化）

- **エンコーディング・BOM**: 入力と同一を保存（UTF-16 LE → UTF-16 LE）。
- **改行**: 入力の **支配的改行**（CRLF 件数 ≥ LF-only 件数 なら CRLF）へ正規化。行ごとの改行保存はしない（`xml_io.py` と対称）。
- **末尾改行**: 入力の有無を保存。
- **`$KEY`**: そのまま・値側のみ訳文で置換。
- **空行・タブ無し非空行**: passthrough（未翻訳・そのまま保持）。

完全なバイト同一性は意図的に保証しない（混在改行は正規化される）。

### 削除・廃止

無し（既存機能は全て保持・回帰ゼロ）。

---

## 変更理由

### MCM TXT 形式への需要

Skyrim の MCM（Mod Configuration Menu）は SkyUI 翻訳ファイル（`*_ENGLISH.txt` 系・UTF-16 LE + BOM）を
使用し、xTranslator は扱わない形式。ユーザーが個別に英→日翻訳する需要があり、`iroiro` で対応した。

### サブコマンド分離（既存 XML パスの保護）

`translate` の `_run` は `parse_xml` / `serialize_xml` に強結合しているため、分岐を入れると
既存 XML パスの回帰リスクが生じる。サブコマンド分離により **既存 XML パスは1行も変更しない**
（リスク隔離・AGENTS.md「触ってはいけないもの」の精神）。翻訳エンジン `_translate_all` は
`rec=""` `skip_records=frozenset()` でそのまま再利用（`entry.rec in cfg.skip_records` ブランチが no-op）。

### `escape.py` 共有 regex 拡張（却下: MCM ローカル関数）

`{N}` 保護を MCM ローカル関数ではなく共有 `escape.py` の regex に追加した理由: トークン整合性検証の
単一系統を維持し、`{0}` は XML Source にも出現しうるため保護の厳密化（安全方向）になるため。
既存 XML テストへの回帰は `{N}` リテラルを含む fixture が存在しないため確認済み（T-ESC-N3 で pin）。

---

## Work packages

### WP-1-tests（✅ 完了）

| 項目 | 値 |
|---|---|
| Goal | MCM テスト・フィクスチャ追加（test-first） |
| Status | done |
| Files | `tests/test_mcm_io.py`（新規・T-MCM-01〜T-MCM-RESUME）/ `tests/test_escape.py`（`{N}` ケース T-ESC-N1〜N5 追記）/ `tests/test_cli.py`（MCM E2E: T-CLI-MCM-01〜05, HELP, SKIP-RECORDS-REJECTED, MAXCHARS-ZERO, T-MCM-FAIL/LONG/JP/RESUME 追記）/ `tests/fixtures/mcm_tiny.txt`（新規・UTF-16 LE BOM / CRLF / `{0}` / 空行 / タブ無し行 含む・自作）/ `tests/fixtures/mcm_lf.txt`（新規・LF / BOM 無し / 末尾改行あり・自作） |
| Verification | WP-2 完了後に全 green・既存 escape テストに回帰無し |

### WP-2-core（✅ 完了）

| 項目 | 値 |
|---|---|
| Goal | `mcm_io.py` 新設・`escape.py` 拡張・`cli.py` に `mcm` サブコマンド追加 |
| Status | done |
| Files | `iroiro/mcm_io.py`（新規・`parse_mcm` / `serialize_mcm` / `McmFormat`）/ `iroiro/escape.py`（`PROTECTED_TOKENS_RE` に `\{\d+\}` 追加）/ `iroiro/cli.py`（`mcm` サブコマンド + `_run_mcm` + `_default_mcm_output_path` 追加・既存 `translate` / `_run` / `_translate_all` は1行も変更せず） |
| Verification | `uv run pytest`（246 passed）・`uv run ruff check iroiro/ tests/` clean・`uv run mypy iroiro` clean（12 source files） |
| Notes | `iroiro/__init__.py` の `__version__` は WP-3 時点では `"0.6.0"` のまま残したが、PM 主導の follow-up 委譲で `"0.7.0"` に bump 済み（後述「既知の問題」は解決済みに更新）。`iroiro.toml.example` は §3.5 で編集見送り・v0.7 では一切未触接（作業ツリーの `M` はユーザー由来） |

### WP-3-docs-handoff（✅ 完了・本 WP）

| 項目 | 値 |
|---|---|
| Goal | ドキュメント更新・handoff 作成・Plan 007 §3.9 整合修正 |
| Status | done-with-notes |
| Allowed paths | `README.md` / `docs/usage.md` / `docs/development.md` / `docs/handoff/007-mcm-translation.md`（新設）/ `docs/plans/007-mcm-translation.md`（§3.9 の1行修正のみ） |
| Forbidden | `iroiro/*` / `tests/*` / `iroiro.toml.example` / その他（§3.5 で `iroiro.toml.example` の `system_prompt` 編集見送り決定） |
| Files | `README.md`（MCM サブコマンド追記・プロジェクト概要拡張・クイックスタート例追加・Plan 007 / handoff 007 追記）/ `docs/usage.md`（「MCM 翻訳 TXT（v0.7）」節新設・CLI フラグ表・出力形式・プレースホルダ保護・skip/fail 時の挙動・first-line-only 既知制限のトラブルシュート・reset 節に MCM ファイル追記）/ `docs/development.md`（モジュール構成に `mcm_io.py` 追加・バージョン表記 v0.7・テスト数 246・テスト戦略表に `test_mcm_io.py` 行・fixtures に MCM 追加・ロードマップ v0.7 完了 + v0.8 以降）/ `docs/handoff/007-mcm-translation.md`（本ファイル・新設）/ `docs/plans/007-mcm-translation.md`（§3.9 CR-only 記述の1行修正・実装と整合） |
| Verification | `uv run pytest -q`（246 passed・docs 変更でテストは壊れないことを確認）・smoke test 再確認（216 entries） |

---

## 触ったファイル一覧

### WP-3 で触ったファイル（本 WP）

| ファイル | 変更内容 |
|---|---|
| `README.md` | プロジェクト概要に「Skyrim MCM 翻訳 TXT」を1文追加。主な機能に v0.7 MCM 項目を追記。クイックスタート dry-run 例に `iroiro mcm INPUT.txt --dry-run` を追加。よく使うフラグに MCM 注記（`--skip-records` は無い）を追記。ドキュメント一覧に Plan 007 / handoff 007 を追記。**既存 XML `translate` 記述は全て保持** |
| `docs/usage.md` | 「MCM 翻訳 TXT（v0.7）」節を新設（使い方・dry-run 出力例・CLI フラグ全一覧表・`--skip-records` 無しの明記・`iroiro.toml` 必須の注記・エントリ判定と出力形式・プレースホルダ保護・skip/fail 時の値保護・first-line-only 既知制限）。トラブルシュートに「MCM の訳文が途中で切れる（first-line-only）」項目を追加。reset 節の出力・進捗ファイル削除例に MCM を追記。**既存 XML `translate` 記述は全て保持** |
| `docs/development.md` | モジュール構成表に `mcm_io.py` 行を追加（`xml_io.py` の上）・`cli.py` / `escape.py` 説明に v0.7 変更を追記・`__init__.py` の `__version__` 表記を `v0.6: 0.6.0` → `v0.7: 0.7.0` に更新。テスト数を 208 → 246 に更新。テスト戦略表に `tests/test_mcm_io.py` 行を追加・`test_escape.py` 行に `{N}` 拡張を追記。fixtures 節に `mcm_tiny.txt` / `mcm_lf.txt` を追加。ロードマップに v0.7（✅ 完了）を追加・v0.7 以降を v0.8 以降に変更・「SSTXMLRessources v3 / Interface/*.txt 対応」から MCM は v0.7 で完了したため分離 |
| `docs/handoff/007-mcm-translation.md` | 新規作成（本ファイル） |
| `docs/plans/007-mcm-translation.md` | §3.9 の1行を修正: 「LF 扱いで正規化する」→「支配的改行判定の tie で CRLF 扱いとなり CRLF へ正規化される」（実装と整合・Codex 最終レビュー指摘）。**§3.9 以外は触っていない** |

### WP-1 / WP-2 で触ったファイル（参考・本 WP では触っていない）

- `iroiro/mcm_io.py`（WP-2・新規）/ `iroiro/escape.py`（WP-2・`{N}` 追加）/ `iroiro/cli.py`（WP-2・`mcm` サブコマンド + `_run_mcm` + `_default_mcm_output_path`）
- `tests/test_mcm_io.py`（WP-1・新規）/ `tests/test_escape.py`（WP-1）/ `tests/test_cli.py`（WP-1）
- `tests/fixtures/mcm_tiny.txt` / `tests/fixtures/mcm_lf.txt`（WP-1・新規・自作）

---

## テスト

### 実行コマンド

```bash
uv run pytest -q                                                    # 全テスト（246件）
uv run pytest -k "mcm or ESC_N or CLI_MCM" --tb=no -q              # MCM 関連のみ
uv run ruff check iroiro/ tests/                                    # lint
uv run mypy iroiro                                                  # 型チェック
uv run iroiro mcm sample/daymoyl_ENGLISH.txt --dry-run             # smoke test（sample は git 管理外）
uv run iroiro mcm sample/daymoyl_ENGLISH.txt --skip-records "HDPT:FULL"  # 拒否確認（exit 2 期待）
uv run iroiro mcm --help                                            # ヘルプ（--skip-records 無しを確認）
```

### 結果（2026-07-02 実機確認）

- **`uv run pytest -q`**: `246 passed in 2.55s`（v0.6 の 208 件 + 38 件）
- **`uv run ruff check iroiro/ tests/`**: `All checks passed!`
- **`uv run mypy iroiro`**: `Success: no issues found in 12 source files`
- **smoke test**（`sample/daymoyl_ENGLISH.txt` が存在する環境）: `Parsed 216 MCM entries (BOM=True, newline='\r\n', encoding=utf-16-le)` / `総エントリ数: 216` / `翻訳対象: 216`
- **`--skip-records` 拒否**: `No such option: --skip-records`（typer が exit 2 で拒否・期待通り）
- **`mcm --help`**: `-o/--output`, `--config`, `--api-base`, `--api-key`, `--model`, `--concurrency`, `--max-chars`, `--timeout`, `--resume`, `--dry-run`, `-v/--verbose`, `--retry-failed/--no-retry-failed`, `--help` を確認（`--skip-records` は存在しない）

### 未実行項目

- **実 LLM での MCM 翻訳 E2E**: CI 上では実施せず（`translate` と同じ方針）。ユーザー環境での手動検証に委ねる。
- **Fallout4 / Starfield の MCM 形式検証**: 構造は同一を想定するが v0.7 では Skyrim のみ保証（sample が第三者著作物で git 管理外・将来機能）。

---

## ドキュメント更新状況

| ファイル | 更新状況 | 備考 |
|---|---|---|
| `README.md` | ✅ 更新 | プロジェクト概要・主な機能・クイックスタート・よく使うフラグ・ドキュメント一覧 |
| `docs/usage.md` | ✅ 更新 | 「MCM 翻訳 TXT（v0.7）」節新設・トラブルシュート・reset 節 |
| `docs/development.md` | ✅ 更新 | モジュール構成・バージョン表記・テスト数・テスト戦略表・fixtures・ロードマップ |
| `docs/handoff/007-mcm-translation.md` | ✅ 新規作成 | 本ファイル |
| `docs/plans/007-mcm-translation.md` | ✅ §3.9 のみ修正 | CR-only 記述の1行整合修正（実装と整合） |
| `iroiro.toml.example` | （触っていない） | §3.5 で `system_prompt` 編集見送り決定・将来改善（v0.8 候補） |
| `docs/design.md` | （触っていない） | 歴史的記録・MCM 固有の設計判断は Plan 007 に集約 |

---

## 手動確認項目

本 WP では実施していないが、リリース前にユーザー環境で確認すべき項目:

### 実 LLM での MCM 翻訳

```bash
# LLM サーバー起動後（既定 http://localhost:8081/v1）
uv run iroiro mcm path/to/your_mod_ENGLISH.txt
# 出力: path/to/your_mod_ENGLISH.translated.txt
```

確認点:
- `$KEY` がそのまま保持されていること（`split("\t", 1)` で key/value 分離）
- `{0}` `{1}` 等 GlobalVariable プレースホルダが訳文でも保存されていること
- UTF-16 LE + BOM / CRLF が出力で保存されていること（`file` コマンド等で確認）
- skip/fail エントリの値が英文のままであること（空になっていないこと）

### UTF-16 以外の入力（import 便益）

```bash
# UTF-8（BOM 無し）入力も受入（出力は UTF-8）
uv run iroiro mcm path/to/utf8_input.txt --dry-run
```

---

## 既知の問題

### ~~`iroiro/__init__.py` の `__version__` が `"0.6.0"` のまま~~ → ✅ 解決済み（follow-up）

WP-3 直後は `iroiro/*` が forbidden だったため `"0.6.0"` のまま残っていたが、**PM 主導の follow-up
委譲で `"0.7.0"` に bump 済み**（`iroiro/__init__.py:12`・2026-07-02）。doc-code mismatch は解消。

### ~~`mcm_io.py` の `McmFormat` docstring に古い CR-only 記述~~ → ✅ 解決済み（follow-up）

WP-3 では `iroiro/*` が forbidden だったため未修正だったが、**PM 主導の follow-up 委譲で整合済み**。
`McmFormat.newline` docstring・`parse_mcm` line 104 コメント共に「CR-only は tie で CRLF 扱いとなり
CRLF へ正規化される」に書き換え済み（Plan §3.9 と一致）。実行時挙動への影響は元から無し。

### first-line-only（長文 description 系・既知制限）

`Translator.translate_entry` の `_postprocess` は複数行 LLM 出力を最初の行のみ採用する。
MCM 値は本来単一行だが、長文 description 系で LLM が複数行返した場合は **2行目以降が truncate** される
（XML `translate` と同じ挙動・v0.1 からの既知制限）。`docs/usage.md` のトラブルシュートに明記済み。

### MCM 独自プロンプトは未対応

v0.7 は既存 `system_prompt` をそのまま再利用。`{N}` 保存はトークン整合性検証が **プロンプト非依存で
強制保証** するため正確性は保証されるが、`{N}` 保存行の `system_prompt` 追記や MCM 専用
`[iroiro.mcm]` セクションは将来改善（v0.8 候補・§3.5 で見送り決定）。

### `iroiro.toml.example` の作業ツリー変更はユーザー由来（v0.7 非関連）

`git status` で `iroiro.toml.example` が `M`（modified）として現れるが、これは**ユーザー自身の
作業ツリー編集**（約70行のコメント削除によるテンプレート簡素化）であり、**v0.7 のどの WP も触れていない**。
セッション開始時（WP-1 委譲前）の最初の `git status` で既に `M` として存在していたことを確認済み。
diff は純粋なコメント削除のみで v0.7/mcm/007 関連の追加行は一切無し。設定値（`skip_records` 14件・
`system_prompt`・`reject_phrases`・`[iroiro.rec_hints]`）は不変・T168 green。コミット可否はユーザー判断。

---

## 残 TODO（将来機能・v0.7 ではスコープ外）

- ~~`iroiro/__init__.py` の `__version__` bump~~ → ✅ follow-up で解決（`0.7.0`）
- ~~`mcm_io.py` の docstring 整合修正~~ → ✅ follow-up で解決
- **MCM 独自プロンプト / `[iroiro.mcm]` セクション**（v0.8 候補）
- **Fallout4 / Starfield の MCM 形式実データ検証**（構造同一想定・v0.7 は Skyrim のみ保証）
- **ファィル形式の自動判別**（拡張子・内容でのフォーマット推論・v0.7 ではユーザー申告通りサブコマンドで明示指定）
- その他: `max_tokens` 設定・接続設定 6 項目の必須化検討・用語集機能・長文 BOOK の自動分割・
  実 LLM での品質レビュー用 diff 出力・SSTXMLRessources v3 対応・`--game` ゲーム選択機能・
  review-needed 状態の導入・`iroiro.toml` の親ディレクトリ遡り探索・選択的リトライ

---

## リスク

### 低リスク項目（既存パスは無傷）

- **既存 XML `translate` パス**: 1行も変更していない（サブコマンド分離）。全 246 テスト green で回帰無しを保証。
- **XML 安全性中核**（`xml_io.py`）: 触っていない。
- **並行安全性**（`progress.py`）: 触っていない（`_translate_all` 再利用・index ベース resume は XML と対称）。
- **LLM クライアント**（`translator.py` の `Translator`）: 触っていない。

### 中リスク項目（文書化済み）

- **`escape.py` 共有 regex 拡張**: `{N}` 追加で既存 XML テストが壊れる可能性があったが、`{N}` リテラルを含む fixture が存在しないため回帰無し（T-ESC-N3 で pin・確認済み）。
- **skip/fail 時の値保護**: `original_dest=""` だと data-loss になるが、`original_dest=source` で構築し解決（Codex review blocking fix・T-MCM-FAIL/LONG/JP で検証）。
- **UTF-16 + 混在改行 round-trip**: 「フォーマット保存 + 改行正規化」契約で固定（バイト同一を主張しない・T-MCM-02/03 で検証）。

---

## ロールバックメモ

v0.7 は新機能追加で既存機能に破壊的変更は無いため、ロールバックは容易:

### v0.6 への戻し

1. `mcm` サブコマンドを使わなければ、v0.7 のコードは v0.6 と同じ挙動（XML `translate` パスは不変）。
2. 完全に v0.6 に戻す場合: `iroiro/mcm_io.py` 削除・`iroiro/escape.py` の `\{\d+\}` 行削除・`iroiro/cli.py` の
   `mcm` サブコマンド + `_run_mcm` + `_default_mcm_output_path` 削除・関連テスト削除。
3. MCM 出力・進捗ファイルを削除:

```bash
rm path/to/your_mod_ENGLISH.translated.txt
rm path/to/your_mod_ENGLISH.txt.iroiro-progress.json
```

---

## 次の担当者・エンジニアへのメモ

### v0.7 リリース前の対応推奨

1. ~~`iroiro/__init__.py` の `__version__` bump~~ → ✅ PM follow-up で解決（`0.7.0`）
2. ~~`mcm_io.py` docstring 整合修正~~ → ✅ PM follow-up で解決
3. **ユーザー判断事項**: `iroiro.toml.example` が作業ツリーで `M`（ユーザー由来のコメント削除・v0.7 非関連）。コミット可否・ファイル先頭ヘッダの `v0.3/v0.4/v0.5/v0.6` → `v0.7` 更新はユーザー判断。

### v0.8 以降の開発への引き継ぎ

- **MCM 独自プロンプト** を検討する場合、`{N}` 保存はトークン検証で強制保証済みのため、プロンプト最適化は
  失敗率改善（正確性でなく品質）の観点で行う。`iroiro.toml.example` の `system_prompt` 編集時は
  AGENTS.md の「LLM 挙動中核デフォルト値編集時の同時更新ルール」（`tests/conftest.py` /
  `tests/test_cli.py:T168` のカスケード）に注意。
- **Fallout4 / Starfield MCM 検証** を行う場合、`mcm_io.py` の構造はゲーム非依存（タブ区切り・`$KEY` 慣行は共通）
  だが、実データでエンコーディング・`$` prefix 有無・改行が Skyrim と同じか要確認。

### テスト・CI の継続保証

- **T-CLI-MCM-HELP** / **T-CLI-MCM-SKIP-RECORDS-REJECTED** が `mcm` サブコマンドに `--skip-records` が無いことを
  pin する。`mcm` サブコマンドのフラグを追加・変更する場合は両テストを通すこと。
- **T-ESC-N3** が `{N}` regex 拡張の既存トークン回帰無しを pin する。`escape.py` の regex を編集する場合は通すこと。
- `mcm_io.py` の I/O 契約（フォーマット保存 + 改行正規化）は T-MCM-02 / T-MCM-03 で固定。バイト同一を主張する
  テストではないため、契約を変えない限り触る必要は無い。

### 関連資料

- [Plan 007](../plans/007-mcm-translation.md) — 本 v0.7 の設計判断・却下代替案の経緯
- [Plan 001 §5.3](../plans/001-initial.md) — エントリモデル・翻訳エンジン共有の基盤設計
- [詳細な使い方](../usage.md) — 「MCM 翻訳 TXT（v0.7）」節・トラブルシュート
- [開発者向け](../development.md) — モジュール構成（`mcm_io.py`）・ロードマップ v0.7
