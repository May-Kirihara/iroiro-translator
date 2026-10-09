# 引き継ぎメモ: iroiro-translator v0.5 LLM プロンプト・エラー判定語句の完全 toml 化 (005-llm-config)

- 作成日: 2026-06-29
- 計画書: [`docs/plans/005-llm-config.md`](../plans/005-llm-config.md)
- 状態: **done-with-notes**

---

## ステータス

| 項目 | 値 |
|---|---|
| 状態 | done-with-notes |
| 日付 | 2026-06-29 |
| リスク分類 | `normal`（後方互換性を破るが、ユーザー承認済み・影響範囲は小） |
| バージョン | v0.5 |
| 前バージョン | v0.4（`--retry-failed`） |
| 担当 | PM + implementer（WP-1 テスト / WP-2 実装 / WP-3 ドキュメント） |
| テスト | 191 passed（+26: T132-T157・既存 fixtures 拡充） |
| ruff | clean |
| mypy | clean（11 source files） |
| 概要 | v0.5 で LLM 挙動中核 3 要素（`system_prompt` / `reject_phrases` / `[iroiro.rec_hints]`）を `iroiro/translator.py` から **完全削除** し、`iroiro.toml` から注入する形式に変更（案 α）。`iroiro.toml` の **必須化**（`--dry-run` 含む全操作でファイル無し・`[iroiro]` 欠損・3 新項目欠損時にエラー停止）。`PromptConfig` dataclass の導入（`Translator(cfg, prompts, client)`）。**後方互換性の破れ**: v0.4 までの「`iroiro.toml` 無しで内蔵デフォルトで動く」挙動を廃止。 |

---

## 変更内容

v0.5 は **後方互換性を破る** 変更。LLM 挙動の中核（翻訳方針・メタ返答ブラックリスト・REC 型別ヒント）をコードから完全に toml へ移行した。

### 機能サマリ

1. **`system_prompt`**（toml・必須）— LLM へのシステムメッセージ全文（翻訳方針）。TOML の multiline string（`"""..."""`）で記述。`""` / `"   "` は拒否。
2. **`reject_phrases`**（toml・必須）— LLM メタ返答ブラックリスト。`list[str]`・各要素が非空 `str`・`bool` 拒否。空リスト `[]` は許可（メタ返答チェック無効化）・重複は自動で `frozenset` 化して除去。
3. **`[iroiro.rec_hints]`**（toml・必須）— `<REC>` 別ヒント辞書。テーブル自体は必須・中身が空 `{}` は許可（REC ヒント無効化）。REC キーは `:` を含むため **必ず quoted key**（`"MGEF:FULL"`）。
4. **`PromptConfig` dataclass** — `system_prompt` / `rec_hints: dict[str, str]` / `reject_phrases: frozenset[str]` の 3 要素を保持。`frozen=True` 無（mutable な `dict` と矛盾するため・Codex review N1）。
5. **`Translator` の signature 変更** — `Translator(cfg, prompts, client=...)` に `prompts: PromptConfig` を追加。
6. **`_is_meta_response` / `_build_user_message` の純粋関数化** — `reject_phrases` / `rec_hints` を引数で受ける形に変更（テスト容易性のためインスタンスメソッド化しない）。
7. **`load_config()` の必須化** — ファイル無し・`[iroiro]` セクション無し・3 新項目欠損時に `IroiroError`（exit code 2）。v0.4 までは `{}` 返却で後方互換だったが破壊的変更。
8. **`--dry-run` の挙動変更** — LLM を呼ばないが `iroiro.toml` の設定検証は走る（案 α の精神・一貫性のため）。

### 行動変更（破壊的）

- **`iroiro.toml` ファイル無し** → `IroiroError("iroiro.toml not found in <cwd>. -> Run: cp iroiro.toml.example iroiro.toml -> Or specify: --config /path/to/iroiro.toml")`
- **`[iroiro]` セクション自体が無い** → `IroiroError("[iroiro] section is required in <path>")`
- **`system_prompt` 欠損** → `IroiroError("[iroiro] system_prompt is required in <path>")`
- **`reject_phrases` 欠損** → `IroiroError("[iroiro] reject_phrases is required in <path>")`
- **`[iroiro.rec_hints]` 欠損** → `IroiroError("[iroiro.rec_hints] table is required in <path>")`
- **`--dry-run` も `iroiro.toml` が必須**（LLM を呼ばないが設定検証は走る）

### 削除

| 旧定数 | 場所 | 新しい注入元 |
|---|---|---|
| `_SYSTEM_PROMPT` | 旧 `iroiro/translator.py` L152-158 | `PromptConfig.system_prompt` |
| `_REC_HINTS` | 旧 `iroiro/translator.py` L163-182 | `PromptConfig.rec_hints` |
| `REJECT_PHRASES` | 旧 `iroiro/translator.py` L215-227 | `PromptConfig.reject_phrases` |

### 修正（実装コード・WP-2）

| ファイル | 変更内容 |
|---|---|
| `iroiro/translator.py` | `_SYSTEM_PROMPT` / `_REC_HINTS` / `REJECT_PHRASES` のハードコード定数を **完全削除**。`PromptConfig` dataclass 追加（`system_prompt: str` / `rec_hints: dict[str, str]` / `reject_phrases: frozenset[str]`・`frozen=True` 無）。`Translator.__init__` に `prompts: PromptConfig` パラメータ追加。`_is_meta_response(text, reject_phrases)` / `_build_user_message(source, rec, rec_hints)` を引数受取型の純粋関数に変更。`translate_entry` / `_translate_with_retry` で `self._prompts` を参照 |
| `iroiro/config.py` | `_validate_system_prompt` / `_validate_reject_phrases` / `_validate_rec_hints` validator 追加（厳格型検証・`bool` 拒否）。`_VALIDATORS` に 3 キーを登録。`load_config()` の行動変更: ファイル無し時 `IroiroError` 化・`[iroiro]` テーブル自体が存在しない場合も `IroiroError` 化・3 キーの必須チェック追加。戻り値の normalisation 一元化（`reject_phrases` を `frozenset[str]` に重複除去・`rec_hints` は `dict[str, str]`） |
| `iroiro/cli.py` | `RunConfig` に `prompts: PromptConfig` フィールド追加。`translate()` で `load_config()` 結果から `PromptConfig` を構築（薄い組み立てのみ・validation は `load_config()` 側で完結）。`Translator` の初期化で `PromptConfig` を渡す。`--config` の `--help` 説明文を「v0.5 では iroiro.toml は必須: 無い場合はエラーで停止」に更新 |
| `iroiro.toml.example` | ヘッダを `(v0.3 / v0.4 / v0.5)` に更新。`system_prompt` / `reject_phrases`（21語） / `[iroiro.rec_hints]`（18種）の全文デフォルトを記載（**REC key は全て quoted**）。LLM 挙動中核・必須の注記・v0.5 破壊的変更の説明を追加 |

### 修正（テスト・WP-1）

| ファイル | 変更内容 |
|---|---|
| `tests/conftest.py` | `default_prompt_config` fixture 追加（`iroiro/translator.py` から `PromptConfig` を local import し、ハードコード定数と意味的に同等の値を組み立て・実装コードのデフォルトを import しない・B7 指摘）。既存テストの `Translator(cfg, client=...)` を `Translator(cfg, prompts=default_prompt_config, client=...)` に追随させるための helper |
| `tests/test_cli.py` | `v05_default_config` fixture 追加（`iroiro_v05_full.toml` を cwd に配置して chdir する・`default_prompt_config` とは別物） |
| `tests/test_translator.py` | 既存 22 箇所の `Translator` 構築箇所を新 signature に追随（`prompts=default_prompt_config` を注入）。T143（`PromptConfig` 注入で system メッセージ検証）・T144（カスタム `reject_phrases` で `_is_meta_response` 検証）・T145（カスタム `rec_hints` で user メッセージ検証）・T157（空 `rec_hints` 時の `_build_user_message`）を追加 |
| `tests/test_cli.py` | 既存 factory 署名を追随。T146（`iroiro.toml` 無しで `--dry-run` → exit 2）・T147（3 新項目欠損 → exit 2）・T148（3 新項目あり `--dry-run` → 正常終了）・T154（CLI → `PromptConfig` 注入検証）を追加 |
| `tests/test_config.py` | T132-T142（`system_prompt` / `reject_phrases` / `[iroiro.rec_hints]` の型・値域・必須検証）・T149-T156（`[iroiro]` セクション無し・未知キー WARNING・未知 REC キー許可・`rec_hints` 形エラー・`rec_hints` 値 bool 拒否・`iroiro.toml.example` の `tomllib` parse 検証・quoted REC key）を追加。既存 T88 / T94 / T103 等を v0.5 化（`{}` 返却 → `IroiroError` に変更） |

### fixtures（WP-1）

**新規 6 ファイル**（全て quoted REC key で記述）:

- `tests/fixtures/iroiro_v05_full.toml` — 全項目（v0.5 デフォルト・`system_prompt` + `reject_phrases` 21語 + `rec_hints` 18種）
- `tests/fixtures/iroiro_v05_missing_prompt.toml` — `system_prompt` 欠損
- `tests/fixtures/iroiro_v05_missing_reject.toml` — `reject_phrases` 欠損
- `tests/fixtures/iroiro_v05_missing_rec_hints.toml` — `[iroiro.rec_hints]` 欠損
- `tests/fixtures/iroiro_v05_empty_reject.toml` — `reject_phrases = []`
- `tests/fixtures/iroiro_v05_custom_prompt.toml` — カスタム `system_prompt`・カスタム `reject_phrases`

**既存 7 ファイル拡充**（3 新項目を追記・既存テストが必須チェックで fail しないよう）:

- `tests/fixtures/iroiro_full.toml` / `iroiro_partial.toml` / `iroiro_retry_true.toml` / `iroiro_retry_false.toml` / `iroiro_unknown_key.toml` / `iroiro_empty_base.toml` / `iroiro_max_chars_zero.toml`

> ※ `iroiro_broken.toml`（TOML シンタックスエラー）・`iroiro_not_table.toml`（`[iroiro]` がテーブルでない）・`iroiro_other_only.toml`（`[iroiro]` セクション自体が無い）は、3 新項目の必須チェックに到達する **前** の段階でエラーになることを検証する fixtures のため、あえて 3 新項目を追記していない（追記すると検証意図が変わるため）。

### 修正（ドキュメント・WP-3）

| ファイル | 変更内容 |
|---|---|
| `docs/usage.md` | CLI フラグ表の `--config` 行に v0.5 必須化を明記。解決順序の注記に v0.5 LLM 挙動中核 3 項目の例外を追加。「設定ファイル」節の冒頭注記・書き方（2 群に分類・quoted REC key）・検索位置（v0.5 ではファイル無しでエラー）・各項目表（LLM 挙動中核 3 項目を追加）・エラーメッセージ例（v0.5 新エラー 6 種）を更新。「`iroiro.toml` 必須化と移行（v0.5）」節・「LLM プロンプトのカスタマイズ（v0.5）」節を新設（新規・既存ユーザー別の移行手順・toml 例・TOML 構文注意）。dry-run 節に v0.5 必須注記。トラブルシュートの `--reject-phrases` CLI フラグ誤記を `iroiro.toml` に修正 |
| `docs/design.md` | 「メタ返答チェック（ルール7）」節の `REJECT_PHRASES` 定数参照を `PromptConfig.reject_phrases` + `iroiro.toml` カスタマイズに更新。「LLM 挙動中核の完全 toml 化（v0.5）」節を新設（9 つの設計判断: 案 α 採用・対象/非対象分類・`iroiro.toml` 必須化・3 新項目必須・`[iroiro]` セクション欠損エラー・`PromptConfig` dataclass・純粋関数化・`load_config()` normalisation 一元化・却下代替案 4 件） |
| `docs/development.md` | テスト件数（165 → 191）・モジュール構成ツリーの `cli.py` / `config.py` / `translator.py` キャプション更新（v0.5 の `PromptConfig` / 3 validator / 定数削除を明記）・テストファイル表に v0.5 追加分（T132-T157）を明記・フィクスチャ一覧に v0.5 新規 6 種・既存 7 拡充を追加・ロードマップに v0.5 完了 / v0.6 以降を更新 |
| `README.md` | 「主な機能」に v0.5（LLM プロンプト・エラー判定語句の完全 toml 化）の1行を追加。v0.5 破壊的変更の callout を追加（新規・既存ユーザー別の移行手順）。クイックスタートの順序を変更（「3. 設定ファイルを作成（必須）」→「4. dry-run」・`cp iroiro.toml.example iroiro.toml` を dry-run 前に移動）。「設定を保存（任意）」節を廃止（v0.5 で必須化のため）。ドキュメントリンクに v0.5 計画・引き継ぎを追加 |
| `AGENTS.md` | クイックコマンドのテスト件数（165 → 191）・`--dry-run` 行に v0.5 必須注記。「触ってはいけないもの」表の `iroiro.toml`（実体）行を強化（v0.5 で LLM 挙動中核を含む・全操作で必須・を明記）。ドキュメント更新タイミングに「LLM 挙動中核のデフォルト値編集時（v0.5）」項を追加（`iroiro.toml.example` と fixtures の同時更新・`default_prompt_config` helper の確認）。参考ドキュメントに v0.5 計画・引き継ぎを追加 |
| `docs/handoff/005-llm-config.md` | 本ファイル（新規） |

---

## 変更理由

### ユーザー要望（2026-06-29）

> tomlでエージェント・ハーネスのプロンプトや、LLMの返信エラー候補をいじれるようにしてほしい
> 内蔵も含めてtomlで指定にしたい。ハードコードなし。

LLM 挙動の中核である `system_prompt`（翻訳方針）・`reject_phrases`（メタ返答ブラックリスト）・`[iroiro.rec_hints]`（REC 型別ヒント）が v0.4 まで `iroiro/translator.py` に **ハードコード** されており、ユーザーが編集するにはコードを直接書き換える必要がありました。これは:

- 配布物（`pip install` / `uv tool install`）として使う場合にユーザーがプロンプトを編集できない
- 翻訳方針の試行錯誤・モデル差し替え時のチューニングに都度コード編集が必要で重い
- コードの差分管理と設定の差分管理が混在する

### 案 α（徹底版）の採用

コードから定数を完全削除し、`iroiro.toml` を必須化する方針（案 α）を採用。後方互換性の破れ（`iroiro.toml` 無しで実行するとエラー）はユーザー承認済み。詳細な設計判断・却下代替案（案 β / 追加モード / CLI フラグ / プレースホルダ検証）は計画書 §2 / §3 を参照。

---

## Work packages

### WP-1-tests

| 項目 | 値 |
|---|---|
| Scope | T132-T142（3 新 validator・必須検証）+ T143-T145（`PromptConfig` 注入・カスタム検証）+ T146-T148（CLI dry-run エラー・必須検証）+ T149-T157（`[iroiro]` 欠損・未知キー・`rec_hints` 形エラー・`iroiro.toml.example` parse・quoted key・空 `rec_hints`）+ 既存テストの v0.5 化（T88 / T94 / T103 等）+ 既存 fixtures 7 種への 3 新項目追記 + 新規 fixtures 6 種 |
| Status | done |
| Files | `tests/test_config.py`（T132-T142, T149-T156 追記・既存 v0.5 化）, `tests/test_translator.py`（T143-T145, T157 追記・既存 signature 追随）, `tests/test_cli.py`（T146-T148, T154 追記・既存 signature 追随・`v05_default_config` fixture 含む）, `tests/conftest.py`（`default_prompt_config` fixture 追加）, `tests/fixtures/iroiro_v05_*.toml`（6 種新規）, 既存 7 fixtures へ 3 新項目追記 |
| Verification | WP-2 完了後に `uv run pytest` で全 green（191/191）。ruff / mypy クリーン |
| Remaining risks | low。実 LLM は使わず `httpx.MockTransport` と単体テストで論理網羅 |

### WP-2-impl

| 項目 | 値 |
|---|---|
| Scope | `PromptConfig` dataclass + 3 validator + `Translator` signature 変更 + `_is_meta_response` / `_build_user_message` 純粋関数化 + `load_config()` 必須化・normalisation 一元化 + CLI `RunConfig.prompts` 構築 + `--config` help 更新 + `iroiro.toml.example` 全文デフォルト追記 |
| Status | done |
| Files | `iroiro/translator.py`, `iroiro/config.py`, `iroiro/cli.py`, `iroiro.toml.example` |
| Verification | `uv run pytest`（191/191 green）, `uv run ruff check iroiro/ tests/`（クリーン）, `uv run mypy iroiro`（クリーン・11 source files）, `uv run iroiro translate --help` で `--config` の v0.5 必須注記を確認 |
| Remaining risks | low。実 LLM E2E は未実施（単体テスト + CLI 統合テストで論理網羅・LLM 呼出部分は v0.1 で実機確認済みで v0.5 では `PromptConfig` 注入のみ変更） |

### WP-3-docs

| 項目 | 値 |
|---|---|
| Scope | ドキュメント更新 + 引き継ぎメモ |
| Status | done |
| Files | `docs/usage.md`, `docs/design.md`, `docs/development.md`, `README.md`, `AGENTS.md`, `docs/handoff/005-llm-config.md`（新規・本ファイル） |
| Verification | 計画書 §5 WP-3 / §6 の更新内容を全て網羅。`uv run pytest` / ruff / mypy がクリーンであることを確認（docs 変更なので結果は不変・念のため確認） |
| Remaining risks | なし |

### その他

- **Codex plan review**: 5 回（最終 `approve-with-notes`・B1-B7 / N1-N3 / T149-T157 等の指摘を全て反映）
- **Codex final review**: 未実施（PM 統合後）
- **QA review**: 未実施（PM 統合後）

---

## 触ったファイル（全リスト・リポジトリ相対パス）

### 実装コード（WP-2）

- `iroiro/translator.py`（修正・定数完全削除 + `PromptConfig` + `Translator` signature）
- `iroiro/config.py`（修正・3 新 validator + `load_config()` 必須化・normalisation）
- `iroiro/cli.py`（修正・`RunConfig.prompts` + `PromptConfig` 構築 + `--config` help 更新）

### 設定・運用（WP-2）

- `iroiro.toml.example`（修正・ヘッダ `(v0.3 / v0.4 / v0.5)` + 3 新項目の全文デフォルト + 注記）

### テスト（WP-1）

- `tests/conftest.py`（修正・`default_prompt_config` fixture）
- `tests/test_cli.py`（修正・`v05_default_config` fixture・`patch_translator.factory` 等の signature 追随）
- `tests/test_translator.py`（修正・既存 signature 追随 + T143-T145, T157）
- `tests/test_cli.py`（修正・既存 signature 追随 + T146-T148, T154）
- `tests/test_config.py`（修正・T132-T142, T149-T156 追記 + 既存 v0.5 化）
- `tests/fixtures/iroiro_v05_full.toml`（新規）
- `tests/fixtures/iroiro_v05_missing_prompt.toml`（新規）
- `tests/fixtures/iroiro_v05_missing_reject.toml`（新規）
- `tests/fixtures/iroiro_v05_missing_rec_hints.toml`（新規）
- `tests/fixtures/iroiro_v05_empty_reject.toml`（新規）
- `tests/fixtures/iroiro_v05_custom_prompt.toml`（新規）
- `tests/fixtures/iroiro_full.toml`（修正・3 新項目追記）
- `tests/fixtures/iroiro_partial.toml`（修正・3 新項目追記）
- `tests/fixtures/iroiro_retry_true.toml`（修正・3 新項目追記）
- `tests/fixtures/iroiro_retry_false.toml`（修正・3 新項目追記）
- `tests/fixtures/iroiro_unknown_key.toml`（修正・3 新項目追記）
- `tests/fixtures/iroiro_empty_base.toml`（修正・3 新項目追記）
- `tests/fixtures/iroiro_max_chars_zero.toml`（修正・3 新項目追記）

### ドキュメント（WP-3）

- `docs/usage.md`（修正）
- `docs/design.md`（修正）
- `docs/development.md`（修正）
- `README.md`（修正）
- `AGENTS.md`（修正）
- `docs/plans/005-llm-config.md`（新規・PM 作成）
- `docs/handoff/005-llm-config.md`（新規・本ファイル）

---

## テスト

### 実行したコマンド

```bash
uv run pytest
uv run ruff check iroiro/ tests/
uv run mypy iroiro
uv run iroiro translate --help
uv run iroiro translate tests/fixtures/tiny.xml --dry-run    # iroiro.toml 無しでエラー確認
cp iroiro.toml.example /tmp/test.toml && uv run iroiro translate tests/fixtures/tiny.xml --config /tmp/test.toml --dry-run
```

### 結果

#### pytest

```
191 passed
```

ファイル別内訳（v0.4 からの差分）:

| ファイル | 件数 | v0.4 からの差分 |
|---|---|---|
| `tests/test_xml_io.py` | 22 | — |
| `tests/test_escape.py` | 15 | — |
| `tests/test_translator.py` | 56 | +3（T143-T145・既存 signature 追随分は件数に反映・T157 は `test_translator.py` 側ではなく `test_config.py` 側で検証） |
| `tests/test_progress.py` | 25 | — |
| `tests/test_config.py` | 38 | +19（T132-T142・T149-T157・既存 v0.5 化） |
| `tests/test_cli.py` | 35 | +4（T146-T148・T154・既存 signature 追随） |
| **合計** | **191** | **+26**（v0.4 の 165 から） |

v0.5 追加分の詳細:

- **T132-T142**（3 新 validator・`test_config.py`）: 11件 green
  - `system_prompt` 非空 `str` のみ受入（`""` / `"   "` / `None` / `123` / `True` 拒否）（T132）
  - `system_prompt` 必須（toml に無いと `IroiroError`）（T133）
  - `reject_phrases` `list[str]` 受入・各要素非空・`bool` 拒否（T134）
  - `reject_phrases` 重複要素は `frozenset` 化で除去（T135）
  - `reject_phrases` 空リスト `[]` は許可（T136）
  - `reject_phrases` 必須（T137）
  - `[iroiro.rec_hints]` テーブル必須（T138）
  - `[iroiro.rec_hints]` 空テーブル `{}` は許可（T139）
  - `[iroiro.rec_hints]` 各キー非空・各値非空 `str`・`bool` 拒否（T140）
  - `[iroiro.rec_hints]` 未知 REC キー許可（quoted key・T141）
  - `iroiro.toml` ファイル無し時の `load_config` が `IroiroError`（T142）
- **T143-T145**（`PromptConfig` 注入・`test_translator.py`）: 3件 green
  - `PromptConfig.system_prompt` が LLM への system メッセージになる（T143）
  - カスタム `reject_phrases` で `_is_meta_response` が True を返す（T144）
  - カスタム `rec_hints` で user メッセージがカスタムヒントを含む（T145）
- **T146-T148**（CLI 統合・`test_cli.py`）: 3件 green
  - `iroiro.toml` 無しで `--dry-run` → exit 2（T146）
  - 3 新項目欠損 → exit 2（T147）
  - 3 新項目あり・`--dry-run` → 正常終了（T148）
- **T149-T157**（Codex review 指摘の追加分）: 9件 green
  - `[iroiro]` セクション自体が無い → `IroiroError`（T149）
  - 未知 `[iroiro]` セクション内キー → WARNING のみ（T150）
  - 未知 REC キー → WARNING 無し（T151）
  - `rec_hints` 形エラー（`rec_hints = "x"`）→ `IroiroError`（T152）
  - `rec_hints` 値が bool → `IroiroError`（T153）
  - CLI → `PromptConfig` 注入検証（T154・`--resume` 経路）
  - `iroiro.toml.example` の `tomllib` parse 検証（T155・`:` bare key 回帰防止）
  - quoted REC key（`"MGEF:FULL"`）が `dict["MGEF:FULL"]` になる（T156）
  - 空 `rec_hints` 時の `_build_user_message` が source のみを返す（T157）

#### ruff / mypy

```
All checks passed!                       # ruff
Success: no issues found in 11 source files   # mypy
```

#### `--help` 確認

`uv run iroiro translate --help` の `--config` に「v0.5 では iroiro.toml は必須: 無い場合はエラーで停止」
が含まれることを確認。

#### `iroiro.toml` 無し dry-run 確認

```
$ uv run iroiro translate tests/fixtures/tiny.xml --dry-run
Error: iroiro.toml not found in <cwd>. -> Run: cp iroiro.toml.example iroiro.toml -> Or specify: --config /path/to/iroiro.toml
```

exit code 2 で停止することを確認。

#### `iroiro.toml` あり dry-run 確認

```
$ cp iroiro.toml.example /tmp/test.toml
$ uv run iroiro translate tests/fixtures/tiny.xml --config /tmp/test.toml --dry-run
INFO  Parsing input: tests/fixtures/tiny.xml
...
--dry-run: LLM を呼ばず終了します
```

正常終了することを確認。

### 未実行

- 実 LLM（llama.cpp server / Gemma 4 12B）による E2E 翻訳検証
  - 理由: v0.5 の主眼は LLM 挙動中核の toml 注入・必須化・厳格型検証。T143-T154 + 既存テスト群が
    `httpx.MockTransport` で論理網羅している。実 LLM 呼出部分（`Translator.translate_entry` /
    `_translate_with_retry`）は v0.1 で実機確認済みで、v0.5 では `PromptConfig` 注入のみ変更
    （プロトコル・post-processing・リトライロジックは無変更）。再検証は次回実機時で十分。

---

## ドキュメント

### 更新

- `docs/usage.md` — CLI フラグ表 `--config` v0.5 必須化・解決順序 v0.5 例外・設定ファイル節（書き方 2 群・検索位置・各項目表 LLM 挙動中核 3 項目・エラーメッセージ例 v0.5 6 種）・「`iroiro.toml` 必須化と移行（v0.5）」節新設・「LLM プロンプトのカスタマイズ（v0.5）」節新設・dry-run 節 v0.5 注記・トラブルシュート `--reject-phrases` 誤記修正
- `docs/design.md` — 「メタ返答チェック（ルール7）」の `REJECT_PHRASES` → `PromptConfig.reject_phrases` + toml カスタマイズに更新・「LLM 挙動中核の完全 toml 化（v0.5）」節新設（9 設計判断 + 4 却下代替案）
- `docs/development.md` — テスト件数（191）・モジュール構成ツリー・テストファイル表（T132-T157）・フィクスチャ一覧（v0.5 新規 6 種・既存 7 拡充）・ロードマップ（v0.5 完了 / v0.6 以降）更新
- `README.md` — 「主な機能」に v0.5 1行追加・v0.5 破壊的変更 callout 追加・クイックスタート順序変更（設定ファイル作成 → dry-run）・「設定を保存（任意）」節廃止・ドキュメントリンク v0.5 追加
- `AGENTS.md` — テスト件数（191）・`--dry-run` 行 v0.5 注記・「触ってはいけないもの」`iroiro.toml` 行強化・ドキュメント更新タイミング「LLM 挙動中核デフォルト値編集時」追加・参考ドキュメント v0.5 追加
- `docs/handoff/005-llm-config.md` — 本ファイル（新規）

### 未更新

- なし。計画書 §5 WP-3 / §6 で想定された全ドキュメントを更新済み。

---

## 手動確認

実施済み（WP-3 時点）:

- `uv run iroiro translate --help` の `--config` に v0.5 必須注記が含まれることを確認
- `uv run iroiro translate tests/fixtures/tiny.xml --dry-run` で `iroiro.toml` 無し時に `Error: iroiro.toml not found` で停止（exit 2）することを確認
- `cp iroiro.toml.example /tmp/test.toml` して `--config /tmp/test.toml --dry-run` で正常終了することを確認

推奨される実機確認（次回実 LLM 検証時）:

1. `cp iroiro.toml.example iroiro.toml`（初回または移行）
2. 既存ユーザー: 既存の `iroiro.toml` に 3 新項目（`system_prompt` / `reject_phrases` / `[iroiro.rec_hints]`）を手動追記
3. `uv run iroiro translate INPUT.xml --dry-run` が正常動作すること
4. `system_prompt` を編集 → LLM への system メッセージが変わることを `--verbose` 等で確認
5. `reject_phrases` に語句を追加 → メタ返答検出が追加されることを確認
6. `rec_hints["MGEF:FULL"]` を変更 → user メッセージのヒントが変わることを確認
7. `system_prompt` を削除 → `Error: [iroiro] system_prompt is required` で停止することを確認
8. `[iroiro]` セクションを削除 → `Error: [iroiro] section is required` で停止することを確認
9. `[iroiro.rec_hints]` のキーの quote を外す（`MGEF:FULL` と書く）→ TOML parse error で停止することを確認（quoted key 必須の回帰防止）

---

## 既知の問題・残 TODO・リスク

### 既知の問題

1. **「内蔵も含めて toml 指定」がテストヘルパーで妥協している点**
   - `tests/conftest.py` の `default_prompt_config` fixture が、既存テストの `Translator(cfg, client=...)`
     signature を新 signature に追随させるため、`iroiro/translator.py` から `PromptConfig` を local import し
     ハードコード定数と **意味的に同等** の値を組み立てている（B7 指摘）。実用上の妥協・製品コードではなく
     テストコードのため許容。実装コードからデフォルトを import していない点は案 α の字義を遵守。

2. **T89 / T90 / T110 / T111 で 3 新項目の byte 完全一致を検証していない点**
   - TOML multiline string の改行・空白の細部まで byte 完全一致は保証しない（TOML シリアライザの細部に
     振り回されないため・R2・Codex review 2回目指摘）。代わりに `len(result) == 9` で key 数量を保証し、
     型 + 非空を検証している。ユーザー編集後はユーザー責任。

3. **実 LLM での動作検証が未実施**
   - toml 注入・必須化・厳格型検証・`PromptConfig` の受け渡しは単体テスト + CLI 統合テスト（T132-T157）で
     担保済み。実モデルでの `system_prompt` / `reject_phrases` / `rec_hints` カスタマイズの動作確認は
     次回実機検証時に行う。

### 残 TODO（v0.6 候補）

- **`max_tokens` 設定** — LLM の生成トークン上限を `iroiro.toml` / CLI フラグで調整可能に。
  `--ctx-size` 不足の空応答対策。v0.5 でスコープ外。
- **接続設定 6 項目の必須化検討** — `api_base` 等の接続設定も v0.5 と同様に `iroiro.toml` 必須にするか。
  v0.5 では LLM 挙動中核のみ必須化・接続設定は省略可のまま。
- **選択的リトライ**（`--retry-failed-only INDEX` 等）— v0.4 から継続議論。
- **CI での `iroiro.toml.example` 構文検証** — T155 で回帰防止済み（ローカルテスト）。CI での継続保証を検討。
- **`--config --help` のさらなる改善** — v0.5 で基本更新済み・更なる親切化は需要次第。
- 用語集機能（JSON/YAML形式・人間メンテ可能）— v0.2 計画書から継続。
- 長文 BOOK の自動分割 — 同上。

### リスク

| リスク | 影響度 | 状態 |
|---|---|---|
| 既存ユーザーの移行コスト（`cp` または 3 新項目の手動追記が必要） | 中 | エラーメッセージ + docs/usage.md + 本 handoff で移行手順を明記。README の callout でも周知 |
| 未知の Skyrim REC 型を使った時のヒント欠落 | 低 | `rec_hints` でカスタマイズ可能（空 `{}` でも動作・未知 REC キーも WARNING 無しで許可） |
| 実 LLM E2E 未検証 | 低 | 単体テスト + CLI 統合テストで論理網羅・実 LLM パスは v0.1 実機確認後 v0.5 で `PromptConfig` 注入のみ変更 |
| T89 等の 3 新項目の緩い検証 | 極低 | `len(result) == 9` で key 数量を保証・fixture 編集時に assertion が見逃される可能性は低い |
| v0.4 以下の `iroiro.toml` をそのまま使うと `Error: [iroiro] system_prompt is required` で停止 | 中 | エラーメッセージ + docs で 3 新項目の手動追記を強調。`cp` 上書きは API 設定消失の危険もあるため注意喚起 |

---

## ロールバックメモ

`iroiro` は入力 XML を破壊しない設計。v0.5 の生成物を削除すれば v0.4 の状態に戻る:

```bash
rm path/to/your_mod.translated.xml
rm path/to/your_mod.xml.iroiro-progress.json
rm -f path/to/your_mod.xml.iroiro-progress.json.tmp
```

### v0.4 動作に戻したい場合（コードは v0.5 のまま）

v0.5 では `iroiro.toml` が必須のため、コードを v0.5 のまま v0.4 相当の挙動に戻すことはできません。
`--dry-run` 含む全操作で `iroiro.toml` が要求されます。

### v0.5 コード自体を巻き戻す場合

`git revert <v0.5 commit>` で v0.4（commit `a4479f5`）に戻る。

注意: ユーザー側の `iroiro.toml` が v0.5 形式（3 新項目を含む）に更新済みの場合、v0.4 コードに
巻き戻すと 3 新項目は **未知キー扱い** で WARNING ログのみ出力され、例外送出せず続行します
（v0.4 の `load_config` の前方互換仕様）。実害はありません。

完全に v0.4 挙動に戻したい場合は、ユーザーが `iroiro.toml` の 3 新項目を削除する必要があります
（削除しなくても動作はする・WARNING のみ）。

---

## 次の担当者・エージェントへのメモ

### v0.5 は後方互換性を破る

- v0.5 は **後方互換性の破れ**（`iroiro.toml` 必須化）を含みます。ユーザーへの周知が必要です。
- README.md の callout・docs/usage.md の「`iroiro.toml` 必須化と移行（v0.5）」節・本 handoff で
  移行手順（新規ユーザー・既存ユーザー別）を明記しています。

### コードを読む場合の推奨順序（v0.5 追加分）

1. `iroiro/translator.py` — `PromptConfig` dataclass（L60 付近）・`Translator.__init__` の `prompts` パラメータ・`_is_meta_response` / `_build_user_message` の引数受取型
2. `iroiro/config.py` — `_validate_system_prompt` / `_validate_reject_phrases` / `_validate_rec_hints` validator・`load_config()` の必須チェック（L146-160）・normalisation（`frozenset` 化）
3. `iroiro/cli.py` — `RunConfig.prompts` フィールド・`translate()` での `PromptConfig` 構築
4. `tests/conftest.py` — `default_prompt_config` fixture（既存テスト signature 追随の helper・B7）
5. `tests/test_config.py` の T132-T157 — 契約の網羅

### 設計上の重要事項（申送り事項）

- **コード内に LLM 挙動中核のハードコードを再導入しないこと**: `_SYSTEM_PROMPT` / `_REC_HINTS` /
  `REJECT_PHRASES` のような定数は v0.5 で完全削除されました。全て `iroiro.toml` 経由で注入します。
  新しい LLM 挙動パラメータを追加する場合も、原則として `iroiro.toml` 経由で設定してください。

- **テストヘルパー `default_prompt_config` の位置づけ**: `tests/conftest.py` にハードコード定数と
  意味的に同等の値を組む fixture がありますが、これは「実装コードの既存テスト signature に触れないための
  妥協」です（B7）。実装コードからデフォルトを import していない点は案 α の字義を遵守。

- **TOML 構文上の落とし穴**: `[iroiro.rec_hints]` 配下のキーは `:` を含むため **必ず quoted key**
  （`"MGEF:FULL"`）で書く必要があります。TOML 1.0 の bare key は `:` を許容しないため、quote を外すと
  parse error になります。`iroiro.toml.example`・fixtures・docs の全 TOML 例で quoted key を統一
  してください（B5 指摘・T155 で回帰防止）。

- **`PromptConfig` の `frozen=True` は付けない**: `rec_hints: dict[str, str]` が mutable な `dict`
  であるため、`frozen` でも完全な不変性が保証できない（N1）。`reject_phrases` は `frozenset[str]` で
  完全不変・`rec_hints` は `dict` のまま（実用上再代入を防ぐだけで十分）。

- **`load_config()` の normalisation 一元化**: `reject_phrases` を `frozenset[str]` に重複除去して
  normalize するのは `load_config()` 内で完結。CLI 側は薄い組み立てのみ（Codex review 指摘）。
  `PromptConfig` 構築ロジックを分散させないこと。

- **`--dry-run` も `iroiro.toml` 必須**: LLM を呼ばないが設定検証は走る（案 α の精神・一貫性のため）。
  `--dry-run` で toml エラーが出るのは「設定不備の早期発見」として有用。

### v0.6（`max_tokens` 設定 / 接続設定必須化 等）を始める場合

- **`max_tokens` 設定** を追加する場合、`ApiConfig`（`RunConfig` でなく）に置くのが自然
  （LLM 呼出パラメータだから・`retry_failed` とは逆の置き場所）。`_validate_int_min` が再利用可能。
  CLI フラグ `--max-tokens` での上書きを提供するか（接続設定群と同じ）・`iroiro.toml` のみにするか
  （LLM 挙動中核と同じ）は設計判断。

- **接続設定 6 項目の必須化** を検討する場合、v0.5 の LLM 挙動中核必須化と同じパターン
  （ファイル無し・`[iroiro]` 欠損・各キー欠損でエラー）で拡張できる。ただし既存ユーザーへの影響が
  大きいため、v0.6 での別議論が必要。

- **CI での `iroiro.toml.example` 構文検証** を追加する場合、T155 のテストロジックを CI スクリプトに
  転用可能。`tomllib` で parse できることの継続保証。
