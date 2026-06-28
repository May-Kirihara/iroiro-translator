# 引き継ぎメモ: iroiro-translator v0.3 設定ファイル (003-config-file)

- 作成日: 2026-06-28
- 計画書: [`docs/plans/003-config-file.md`](../plans/003-config-file.md)
- 状態: **done-with-notes**

---

## ステータス

| 項目 | 値 |
|---|---|
| 状態 | done-with-notes |
| 日付 | 2026-06-28 |
| 担当 | PM + implementer（WP-1 テスト / WP-2 実装 / WP-3 ドキュメント） |
| 概要 | v0.3「設定ファイル（`iroiro.toml`）」機能を実装。LLM エンドポイント・API キー・モデル名・タイムアウト・並列数・`max_chars` のデフォルト値を `iroiro.toml` に外部化した。優先順位は **CLI フラグ（明示指定時）＞ `iroiro.toml` ＞ 内蔵デフォルト**。`--config PATH` フラグ・cwd 自動検出（親遡りなし）。後方互換（`iroiro.toml` 無しなら v0.2.1 と同じ挙動）。144件のテストが全て green。 |

---

## 変更内容

v0.3 は **後方互換** の新機能。既存の CLI フラグ運用はそのまま動く。

### 新規作成

| ファイル | 内容 |
|---|---|
| `iroiro.toml.example` | 設定ファイル雛形（git 管理対象・全項目コメントアウト・セキュリティ注意書き付き） |
| `tests/test_config.py` | `load_config` のユニットテスト（T88-T102・15件） |
| `tests/fixtures/iroiro_*.toml` | `load_config` 検証用 TOML フィクスチャ（8種: `full` / `partial` / `broken` / `not_table` / `other_only` / `unknown_key` / `empty_base` / `max_chars_zero`） |
| `docs/plans/003-config-file.md` | 実装計画書（PM 作成） |
| `docs/handoff/003-config-file.md` | 本ファイル |

### 修正（実装コード）

| ファイル | 変更内容 |
|---|---|
| `iroiro/config.py` | `load_config(explicit_path: Path \| None) -> dict[str, object]` を追加。`[iroiro]` テーブルを読み、型検証・値域検証済みの dict を返す。個別 validator（`_validate_str_nonempty` / `_validate_str_allow_empty` / `_validate_number_positive` / `_validate_int_min`）と `_VALIDATORS` マップを追加。`bool` 拒否・未知キー警告（例外送出なし）・`max_chars = 0` 正当値・前方互換を網羅 |
| `iroiro/cli.py` | `translate()` に `--config PATH` フラグ追加。既存6フラグ（`--api-base` / `--api-key` / `--model` / `--concurrency` / `--max-chars` / `--timeout`）を `Optional[type] = None` 化。`_resolve[T](cli_val, file_cfg, key, default)` helper を追加（`is None` 判定で `or` 演算子の falsy 事故を回避）。`load_config(config)` を呼び `IroiroError` を catch して exit 2。各フラグの `help=` テキストに「未指定時は `iroiro.toml` → 内蔵デフォルトの順で解決」と明記 |

### 修正（設定・運用）

| ファイル | 変更内容 |
|---|---|
| `.gitignore` | `iroiro.toml`（実体）を追加。コメントで「`iroiro.toml.example` は git 管理対象」を明記 |

### 修正（テスト）

| ファイル | 変更内容 |
|---|---|
| `tests/test_cli.py` | T103-T109（7件）を追加。`--config` 明示・cwd 自動検出・CLI フラグ優先・`--max-chars 0` の falsy 回避・`--api-key ""` の falsy 回避・`--config missing.toml` の exit 2 を検証 |

### 修正（ドキュメント・WP-3）

| ファイル | 変更内容 |
|---|---|
| `docs/usage.md` | CLI フラグ表に `--config` 行を追加・解決順序の注記を追加。「設定ファイル（v0.3）」節を新設（書き方・優先順位・検索位置・導入手順・各項目の意味・セキュリティ注意事項・エラー例） |
| `docs/design.md` | モジュール表の `config.py` 行に `load_config` を追記。「設定ファイル読込の設計（v0.3）」節を新設（`pyproject.toml` でなく専用ファイルの理由・親遡りしない理由・`bool` 拒否・`max_chars = 0` 正当値・`is None` 判定・単一テーブル・未知キー警告） |
| `docs/development.md` | テスト件数（144件）・モジュール表の `config.py` 行（`load_config` 追記）・テストファイル表に `test_config.py` 追加・フィクスチャ一覧に `iroiro_*.toml` 追加・ロードマップに v0.3 完了 / v0.4 以降を更新 |
| `README.md` | 「主な機能」に v0.3 設定ファイルの1行を追加。クイックスタートに「4. 設定を保存（任意）」節を追加。ドキュメントリンクに v0.3 計画・引き継ぎを追加 |
| `AGENTS.md` | 「触ってはいけないもの」表に `iroiro.toml`（実体）を追加。クイックコマンドのテスト件数（144件）・ディレクトリ構成に `iroiro.toml.example` と `.gitignore` 運用の注記・参考ドキュメントに v0.3 を追加 |

---

## 変更理由

v0.2.1 まで LLM エンドポイント・API キー・モデル名等のデフォルト値は `iroiro/cli.py` の
`DEFAULT_*` 定数にハードコードされており、**LLM サーバーを頻繁に切り替える利用者**
（llama.cpp / LM Studio / Ollama / リモート OpenAI 互換サーバー等）は毎回 CLI フラグを打つ必要があった。

v0.3 では:

1. **設定の外部化**: `iroiro.toml` にデフォルト値を書けるようにし、CLI フラグの反復入力を不要化
2. **環境依存情報のプロジェクト混入回避**: `pyproject.toml [tool.iroiro]` でなく専用ファイル採用
   （API キー等の個人情報・ローカルネット情報をプロジェクト共有ファイルに入れない）
3. **後方互換**: `iroiro.toml` 無しなら v0.2.1 と同じ挙動。既存ユーザーへの影響ゼロ

計画書 §2（背景）・§4（設計方針）のユーザー確定事項（Q1/Q2/Q3）に従い実装。
詳細な設計判断・却下代替案は計画書 §14 を参照。

---

## Work packages

### WP-1-tests

| 項目 | 値 |
|---|---|
| Scope | T88-T102（`load_config` ユニットテスト）+ T103-T109（CLI 統合テスト）+ TOML フィクスチャ |
| Status | done |
| Files | `tests/test_config.py`（新規）, `tests/test_cli.py`（T103-T109 追記）, `tests/fixtures/iroiro_*.toml`（8種・新規） |
| Verification | WP-2 完了後に `uv run pytest` で全 green（144/144）。ruff / mypy クリーン |
| Remaining risks | low。実 LLM は使わず `--dry-run` と単体テストで論理網羅 |

### WP-2-impl

| 項目 | 値 |
|---|---|
| Scope | `load_config` ローダー + CLI 改修（`--config` / Optional 化 / `_resolve`）+ `iroiro.toml.example` + `.gitignore` |
| Status | done |
| Files | `iroiro/config.py`, `iroiro/cli.py`, `iroiro.toml.example`（新規）, `.gitignore` |
| Verification | `uv run pytest`（144/144 green）, `uv run ruff check iroiro/ tests/`（クリーン）, `uv run mypy iroiro`（クリーン）, `uv run iroiro translate --help` で `--config` フラグ表示を確認 |
| Remaining risks | low。実 LLM E2E は未実施（単体テストで論理網羅・プロトコルは v0.1 で実機確認済み） |

### WP-3-docs

| 項目 | 値 |
|---|---|
| Scope | ドキュメント更新 + 引き継ぎメモ |
| Status | done |
| Files | `docs/usage.md`, `docs/design.md`, `docs/development.md`, `README.md`, `AGENTS.md`, `docs/handoff/003-config-file.md`（新規・本ファイル） |
| Verification | 計画書 §7.4 の更新内容を全て網羅。`uv run pytest` / ruff / mypy がクリーンであることを確認（docs 変更なので結果は不変・念のため確認） |
| Remaining risks | なし |

---

## 触ったファイル（全リスト・絶対パス）

### 実装コード

- `/mnt/holyland/Project/iroiro-translator/iroiro/config.py`（修正）
- `/mnt/holyland/Project/iroiro-translator/iroiro/cli.py`（修正）

### 設定・運用

- `/mnt/holyland/Project/iroiro-translator/iroiro.toml.example`（新規）
- `/mnt/holyland/Project/iroiro-translator/.gitignore`（修正）

### テスト

- `/mnt/holyland/Project/iroiro-translator/tests/test_config.py`（新規）
- `/mnt/holyland/Project/iroiro-translator/tests/test_cli.py`（修正・T103-T109 追記）
- `/mnt/holyland/Project/iroiro-translator/tests/fixtures/iroiro_broken.toml`（新規）
- `/mnt/holyland/Project/iroiro-translator/tests/fixtures/iroiro_empty_base.toml`（新規）
- `/mnt/holyland/Project/iroiro-translator/tests/fixtures/iroiro_full.toml`（新規）
- `/mnt/holyland/Project/iroiro-translator/tests/fixtures/iroiro_max_chars_zero.toml`（新規）
- `/mnt/holyland/Project/iroiro-translator/tests/fixtures/iroiro_not_table.toml`（新規）
- `/mnt/holyland/Project/iroiro-translator/tests/fixtures/iroiro_other_only.toml`（新規）
- `/mnt/holyland/Project/iroiro-translator/tests/fixtures/iroiro_partial.toml`（新規）
- `/mnt/holyland/Project/iroiro-translator/tests/fixtures/iroiro_unknown_key.toml`（新規）

### ドキュメント

- `/mnt/holyland/Project/iroiro-translator/docs/usage.md`（修正）
- `/mnt/holyland/Project/iroiro-translator/docs/design.md`（修正）
- `/mnt/holyland/Project/iroiro-translator/docs/development.md`（修正）
- `/mnt/holyland/Project/iroiro-translator/README.md`（修正）
- `/mnt/holyland/Project/iroiro-translator/AGENTS.md`（修正）
- `/mnt/holyland/Project/iroiro-translator/docs/plans/003-config-file.md`（新規・PM 作成）
- `/mnt/holyland/Project/iroiro-translator/docs/handoff/003-config-file.md`（新規・本ファイル）

---

## テスト

### 実行したコマンド

```bash
uv run pytest --tb=short -q
uv run ruff check iroiro/ tests/
uv run mypy iroiro
uv run iroiro translate --help
```

### 結果

#### pytest

```
144 passed in 1.39s
```

ファイル別内訳:

| ファイル | 件数 |
|---|---|
| `tests/test_xml_io.py` | 22 |
| `tests/test_escape.py` | 15 |
| `tests/test_translator.py` | 53 |
| `tests/test_progress.py` | 20 |
| `tests/test_cli.py` | 19 |
| `tests/test_config.py` | 15 |
| **合計** | **144** |

v0.3 追加分:

- T88-T102（`load_config` ユニットテスト・`tests/test_config.py`）: 15件 green
  - パス解決（明示 / cwd 自動 / 存在しない / `[iroiro]` 無し / テーブルでない）
  - 型検証（`str` / `int` / `float`・`bool` 拒否・文字列フィールドに `int`）
  - 値域検証（`timeout > 0` / `concurrency >= 1` / `api_base` 非空 / `max_chars >= 0`）
  - `max_chars = 0` の正当値受理（T102）
  - 未知キー警告 + 既知キー反映（T98）
- T103-T109（CLI 統合テスト・`tests/test_cli.py`）: 7件 green
  - `iroiro.toml` 無し + フラグ無し → 内蔵デフォルト（T103・回帰保証）
  - `iroiro.toml` 有り + フラグ無し → toml 値反映（T104）
  - `iroiro.toml` 有り + `--api-base` 明示 → フラグ優先（T105）
  - `--config custom.toml` → 指定パス読込（T106）
  - `--config missing.toml` → exit 2（T107）
  - toml `max_chars` + CLI `--max-chars 0` → CLI の `0` が勝つ（T108・falsy 回避）
  - toml `api_key` + CLI `--api-key ""` → CLI の空文字が勝つ（T109・falsy 回避）

#### ruff / mypy

```
All checks passed!                       # ruff
Success: no issues found in 11 source files   # mypy
```

#### `--help` 確認

`uv run iroiro translate --help` に `--config PATH` フラグが表示されることを確認。
既存6フラグ（`--api-base` 等）の help テキストに「未指定時は `iroiro.toml` → 内蔵デフォルトの順で解決」
が含まれることを確認。

### 未実行

- 実 LLM（llama.cpp server / Gemma 4 12B）による E2E 翻訳検証
  - 理由: 本 WP は設定読込機能が主体。設定のマージロジック（`_resolve`）・`load_config` の型/値域検証は
    単体テストと `--dry-run` で担保済み。実 LLM 呼び出し部分（`Translator`）は v0.1 で実機確認済みで
    v0.3 では無変更のため、再検証は次回実機時で十分

---

## ドキュメント

### 更新

- `docs/usage.md` — CLI フラグ表に `--config` 追加・解決順序の注記・「設定ファイル（v0.3）」節新設
- `docs/design.md` — モジュール表更新・「設定ファイル読込の設計（v0.3）」節新設
- `docs/development.md` — テスト件数・モジュール表・テストファイル表・フィクスチャ一覧・ロードマップ更新
- `README.md` — 「主な機能」に1行追加・クイックスタートに「4. 設定を保存（任意）」追加・ドキュメントリンク追加
- `AGENTS.md` — 「触ってはいけないもの」表に `iroiro.toml` 追加・クイックコマンド件数・ディレクトリ構成・参考ドキュメント更新
- `docs/handoff/003-config-file.md` — 本ファイル（新規）

### 未更新

- なし。計画書 §7.4 で想定された全ドキュメントを更新済み。

---

## 手動確認

実施済み（WP-3 時点）:

- `uv run iroiro translate --help` で `--config PATH` フラグが表示されることを確認
- `uv run pytest` / `ruff` / `mypy` が全てクリーンであることを確認

推奨される実機確認（次回実 LLM 検証時）:

1. `cp iroiro.toml.example iroiro.toml` で実体を作成
2. `iroiro.toml` のコメントを外し、値を編集（例: `api_base` を LM Studio の `http://localhost:1234/v1` に変更）
3. `uv run iroiro translate INPUT.xml --dry-run -v` で `iroiro.toml` が読み込まれたことを確認
   （v0.3.0 では `INFO Loaded iroiro.toml from <path>` ログが追加される予定・それまでは
   存在しないキーを混入させて WARNING を誘発する等で確認。**verbose ログでも `api_base`
   等の値は出力されない**ので注意）
4. `--config PATH` で別パスの TOML を明示指定し、cwd の `iroiro.toml` が無視されることを確認
5. `--api-base X` を明示指定し、`iroiro.toml` の `api_base` より CLI フラグが優先されることを確認
   （※ 5 は `--dry-run` では確認不可・実際に1件翻訳して `progress.json` の `api_base` を見る必要がある）

---

## 既知の問題・残 TODO・リスク

### 既知の問題

1. **`timeout` を TOML で整数（`120`）と書くと浮動小数点に正規化される**
   - TOML 仕様上 `timeout = 120` は整数、`timeout = 120.0` は浮動小数点。
   - `load_config` の `_validate_number_positive` は `float(v)` で正規化して返すため、
     どちらで書いても `ApiConfig.timeout`（`float` 型）には同じ値が入る。
   - 挙動への影響は **ない**（`httpx` タイムアウトは `float` を受け取る）。ドキュメント済み。

2. **実 LLM での動作検証が未実施**
   - 設定読込ロジック・マージ優先順位は単体テスト（T88-T109）と `--dry-run` で担保済み。
   - 実モデルでの `iroiro.toml` 経由の接続確認は次回実機検証時に行う。

### 残 TODO（v0.4 候補）

- **`skip_records` / `reject_phrases` の toml 化** — 計画書 §5.2 で v0.3 スコープ外。需要が出れば追加。
  現状は配列型（`["HDPT:FULL", ...]`）になるため、文字列/数値以外の validator 拡張が必要。
- **`iroiro.toml` の親ディレクトリ遡り探索** — 計画書 §4.3 / §14 で却下（v0.3）。将来必要になれば追加。
- **用語集機能** — v0.4 以降で検討（v0.2 計画書 §3.2 から継続）。
- **長文 BOOK の自動分割** — 同上。

### リスク

| リスク | 影響度 | 状態 |
|---|---|---|
| ユーザーが `max_chars = 0` を書いて意図せず全件スキップになる | 低 | docs/usage.md の「各項目の意味」表と注記で明記。`0` は正当值だが全件スキップを意味する |
| ユーザーが `iroiro.toml` を cwd でなく XML と同じディレクトリに置く | 低 | docs/usage.md の「検索位置」節で「コマンドを実行したディレクトリ（cwd）」と明記 |
| `iroiro.toml.example` に実キーを書いて commit する事故 | 低 | 雛形にセキュリティ注意書きを明記。AGENTS.md の「触ってはいけないもの」で運用指導 |
| 既存ユーザーが v0.2.1 からアップデートして挙動が変わる | 極低 | v0.3 は後方互換。`iroiro.toml` 無しなら v0.2.1 と同じ挙動 |

---

## ロールバックメモ

`iroiro` は入力 XML を破壊しない設計。v0.3 の生成物を削除すれば v0.2.1 の状態に戻る:

```bash
rm path/to/your_mod.translated.xml
rm path/to/your_mod.xml.iroiro-progress.json
rm -f path/to/your_mod.xml.iroiro-progress.json.tmp
```

### v0.2.1 動作に戻したい場合（コードは v0.3 のまま）

`iroiro.toml` を置かず、`--config` も指定しなければ v0.2.1 と同じ挙動（CLI フラグ ＞ 内蔵デフォルト）。
既に `iroiro.toml` を作成済みの場合は削除・リネームすれば無効化される:

```bash
mv iroiro.toml iroiro.toml.disabled
```

### v0.3 コード自体を巻き戻す場合

`git revert <v0.3 commit>` で v0.2.1 に戻る。`iroiro.toml`（実体）が残っていても v0.2.1 では
読まれないため無害（`.gitignore` 対象なので commit もされない）。

---

## 次の担当者・エージェントへのメモ

### v0.3 は後方互換

- 既存の CLI フラグ運用（`--api-base` 等を毎回明示）は **そのまま動く**。
- `iroiro.toml` を置かなければ v0.2.1 と完全に同じ挙動。
- v0.2.1 で作成した `progress.json` は v0.3 でもそのまま resume 可能（`progress.json` 仕様は無変更）。

### コードを読む場合の推奨順序（v0.3 追加分）

1. `iroiro/config.py` — `load_config` / `_VALIDATORS` / 個別 validator（bool 拒否・値域チェック）
2. `iroiro/cli.py` — `_resolve` helper（`is None` 判定）/ `translate()` の `load_config` 呼び出しとマージ
3. `iroiro.toml.example` — 雛形とセキュリティ注意書き
4. `tests/test_config.py` — 検証ルールの契約（T88-T102）

### 設計上の重要事項（申送り事項）

- **`_resolve` は `is None` 判定を使う**（`or` 演算子は `0` / `""` を埋もれさせるため絶対に使わない）。
  これにより `--max-chars 0` / `--api-key ""` の明示値が正しく優先される（T108/T109）。
- **`bool` は数値フィールドで拒否**（Python `bool ⊂ int` 事故防止）。`isinstance(v, bool)` チェック必須。
- **`max_chars = 0` は正当値**（全件スキップの意味）。`>= 0` を許可し、負数のみ拒否。
- **未知キーは警告して続行**（例外送出しない・前方互換のため）。既知キーは反映。
- **親ディレクトリ遡りはしない**（cwd 直下のみ）。将来必要になれば追加。
- **探索は cwd 基準**（XML と同じディレクトリではない）。ユーザーが間違えやすい点。

### v0.4（用語集 / skip_records の toml 化等）を始める場合

- `skip_records` / `reject_phrases` を toml 化する場合、配列型（`["HDPT:FULL", ...]`）の validator が
  必要。現在の `_VALIDATORS` はスカラー型のみ。`_validate_str_list` 等の追加を想定すること。
- 用語集機能は `Translator._build_user_message` が自然な拡張点（v0.2 引き継ぎメモ参照）。
- 親ディレクトリ遡り探索を追加する場合、`load_config` のパス解決部分（`else` ブロック）を拡張。
  ただし「知らぬ間に親の `iroiro.toml` が読まれる」混乱を避けるため、ログ出力を慎重に設計すること。
