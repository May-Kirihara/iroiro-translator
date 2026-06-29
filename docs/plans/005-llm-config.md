# v0.5: LLM プロンプト・エラー判定語句の完全 toml 化（ハードコード撤廃）

**日付**: 2026-06-29
**リスク分類**: `normal`（後方互換性を破るが、ユーザーが明示的に承認済み・影響範囲は小）
**前バージョン**: v0.4（`--retry-failed`）
**次バージョン**: v0.5（本計画）

---

## 1. 背景・目的

### 現状（v0.4 まで）

LLM 挙動の中核である以下の 3 要素は `iroiro/translator.py` に **ハードコード** されている:

| 定数 | 場所 | 役割 |
|---|---|---|
| `_SYSTEM_PROMPT` | L152-158 | 翻訳方針のシステムプロンプト（6行・日本語） |
| `_REC_HINTS` | L163-182 | `<REC>` 別のヒント辞書（18種） |
| `REJECT_PHRASES` | L215-227 | LLM メタ返答ブラックリスト（21語） |

ユーザーはこれらを編集するためにコードを直接書き換える必要がある。これは:

- 配布物（`pip install` / `uv tool install`）として使う場合に困る
- 翻訳方針を試行錯誤するために都度コードを編集するのは重い
- コードの差分管理と設定の差分管理が混在する

### ユーザー要望（2026-06-29）

> tomlでエージェント・ハーネスのプロンプトや、LLMの返信エラー候補をいじれるようにしてほしい
> 内蔵も含めてtomlで指定にしたい。ハードコードなし。

**案 α（徹底版）を採用**: コードから定数を完全削除し、`iroiro.toml` を必須化する。後方互換性の破れ（`iroiro.toml` 無しで実行するとエラー）はユーザー承認済み。

---

## 2. 設計判断

### 2.1 「ハードコード」の対象範囲

**対象（コードから完全削除）**:

- `system_prompt` — LLM のシステムメッセージ全文
- `reject_phrases` — LLM メタ返答ブラックリスト
- `[iroiro.rec_hints]` — REC 別ヒント辞書

**非対象（v0.4 までの挙動を維持）**:

- `api_base` / `api_key` / `model` / `timeout` / `concurrency` / `max_chars`（接続設定・環境固有・元からハードコードでは無い）
- `retry_failed`（実行制御フラグ・v0.4 互換のデフォルト False）

### 2.2 必須化の方針

| 項目 | 必須? | 理由 |
|---|---|---|
| `iroiro.toml` ファイル自体 | **必須** | 案 α の中核。`--dry-run` 含む全操作で必須 |
| `system_prompt` | **必須** | ハードコード無しの字義通りの実現 |
| `reject_phrases` | **必須** | 同上 |
| `[iroiro.rec_hints]` テーブル | **テーブル自体は必須** | 中身が空 `{}` は許可（REC ヒント無効化） |
| 既存 6 項目（api_base 等） | 省略可 | v0.3/v0.4 と同じ（CLI フラグで上書き可能） |
| `retry_failed` | 省略可 | v0.4 と同じ（デフォルト False） |

**補足**: 既存 6 項目の「省略可」は「内蔵デフォルト値に落ちる」ではなく「CLI フラグ指定時はそちら優先、未指定時は内蔵デフォルト」。この「内蔵デフォルト」は接続設定固有の値であり、LLM 挙動の中核ではないためハードコード撤廃の対象外。

### 2.3 優先順位（v0.3/v0.4 と同じ）

```
強 ← CLI フラグ（明示指定時） ＞ iroiro.toml ＞ 内蔵デフォルト → 弱
```

LLM 挙動 3 項目は「内蔵デフォルト = 無」なので、toml 未指定時は **即座にエラー**（CLI フラグ経由の上書きも提供しない）。

### 2.4 toml 形式

```toml
[iroiro]
# === 既存（接続設定・省略可）===
api_base      = "http://localhost:8081/v1"
api_key       = "iroiro"
model         = "ggml-org/gemma-4-12B-it-GGUF:Q4_K_M"
timeout       = 120.0
concurrency   = 1
max_chars     = 4000
retry_failed  = false

# === v0.5 新規（LLM 挙動中核・必須）===
system_prompt = """
Skyrim MOD の英文を日本語に翻訳する。
固有名詞・ <alias=...> 等のプレースホルダ・ <br>・改行文字・ # 記号は
**そのまま維持** すること。
簡潔で自然な日本語。**訳文のみ** 出力し、
説明・マークダウン・ラベル・複数行は禁止。
"""

reject_phrases = [
  "了解", "了解しました", "了解いたしました",
  "承知", "承知いたしました", "承知しております",
  "かしこまりました",
  "翻訳", "翻訳します", "翻訳しました", "翻訳結果", "翻訳文",
  "訳文", "訳しました", "訳します",
  "以下に訳します", "訳文を示します",
  "以下の通りです", "以下の通りとなります", "次のようになります",
  "上記の通りです",
]

[iroiro.rec_hints]
"MGEF:FULL" = "魔法の効果名。1〜4語程度の簡潔な表現。"
"MGEF:DESC" = "魔法の効果の説明文。自然な日本語の文章。"
"ARMO:FULL" = "防具の名称。1〜4語程度。"
"ARMO:DESC" = "防具の説明文。"
"BOOK:FULL" = "書籍のタイトル。簡潔な表現。"
"BOOK:DESC" = "書籍の本文。物語風の自然な日本語。"
"WEAP:FULL" = "武器の名称。1〜4語程度。"
"SPEL:FULL" = "スペル（能力）の名称。"
"ACTI:FULL" = "アクティベータ（家具/看板等）の名称。"
"ALCH:FULL" = "錬金術素材/薬の名称。"
"ENCH:FULL" = "エンチャント（効果）の名称。"
"INGR:FULL" = "錬金術素材の名称。"
"NPC_:FULL" = "NPC の名称。固有名詞として扱う。"
"FACT:FULL" = "派閥（ファクション）の名称。"
"INFO:RNAM" = "NPC のセリフ（会話の応答）。自然な会話文。"
"QUST:FULL" = "クエストのタイトル。"
"RACE:FULL" = "種族の名称。"
"CLAS:FULL" = "クラス（職業）の名称。"
```

**重要（TOML 構文）**: `[iroiro.rec_hints]` 配下のキーは `MGEF:FULL` のように `:` を含むため、**必ず quoted key**（`"MGEF:FULL"` のように `"` で囲む）で書く必要がある。TOML 1.0 の bare key は `[A-Za-z0-9_-]` のみ許容するため `:` を含むと parse error になる（Codex review 2回目・B5 指摘）。`iroiro.toml.example`・fixtures・docs 内の全 TOML 例で quoted key を統一する。

### 2.5 検証ルール

| キー | 型 | 制約 | 備考 |
|---|---|---|---|
| `system_prompt` | `str` | 非空・strip 後も非空 | `""` / `"   "` 拒否 |
| `reject_phrases` | `list[str]` | **各要素** が非空 `str`・`bool` 拒否 | 空リスト `[]` は許可（ユーザーが意図的に無効化する場合）・重複は自動で `frozenset` 化 |
| `[iroiro.rec_hints]` | `dict[str, str]` | **各キー** が非空・**各値** が非空 `str`・`bool` 拒否 | 空テーブル `{}` は許可（`[iroiro.rec_hints]` 行自体が存在しない場合は必須エラー） |

**`bool` 拒否**: `reject_phrases = [True]` や `"MGEF:FULL" = true` のようなミスを防ぐため、**全要素で厳格な型検証**（`isinstance(v, bool)` なら即座に拒否）を実施。既存の `_validate_int_min` / `_validate_number_positive` / `_validate_bool` と対称的な「厳格型検証」思想（Codex review 指摘・N2）。

**未知キーの扱い**: v0.3/v0.4 と同じ（`WARNING` ログのみ・例外送出しない）。

**未知 REC キー**: `[iroiro.rec_hints]` に未知の REC（`"FOO:BAR"` 等・quoted key で指定）があっても **許可**（将来の Skyrim REC 型拡張のため・`WARNING` ログも出さない）。

### 2.6 `Translator` への注入

現状:

```python
class Translator:
    def __init__(self, cfg: ApiConfig, client=None):
        ...
```

v0.5:

```python
@dataclass(slots=True)
class PromptConfig:
    """LLM 挙動中核設定（v0.5）.

    注: ``frozen=True`` は付けない。``rec_hints: dict[str, str]`` が
    mutable な dict であるため、frozen でも完全な不変性が保証できない
    （Codex review 指摘・N1）。実用上 ``PromptConfig`` の再代入を防ぐだけで十分。
    """

    system_prompt: str
    rec_hints: dict[str, str]
    reject_phrases: frozenset[str]


class Translator:
    def __init__(self, cfg: ApiConfig, prompts: PromptConfig, client=None):
        ...
```

- `_SYSTEM_PROMPT` 定数は削除 → `self._prompts.system_prompt`
- `_REC_HINTS` 定数は削除 → `self._prompts.rec_hints`
- `REJECT_PHRASES` 定数は削除 → `self._prompts.reject_phrases`
- `_is_meta_response(text)` はモジュール関数のまま → `_is_meta_response(text, self._prompts.reject_phrases)` に変更（テスト容易性のためインスタンスメソッド化せず）
- `_build_user_message(source, rec)` はモジュール関数のまま → `_build_user_message(source, rec, rec_hints)` に変更

**注意**: `_is_meta_response` / `_build_user_message` がモジュール関数のままの場合、呼出側が `Translator` インスタンス経由で `reject_phrases` / `rec_hints` を渡す必要がある。これはテスト容易性を保つため（純粋関数のまま）。

### 2.7 `RunConfig` の拡張

`RunConfig` に `prompts: PromptConfig` を追加:

```python
@dataclass(slots=True)
class RunConfig:
    input_path: Path
    output_path: Path
    api: ApiConfig
    prompts: PromptConfig  # v0.5 新規
    resume: bool
    dry_run: bool
    verbose: bool
    skip_records: frozenset[str]
    retry_failed: bool
```

`cli.py` の `translate()` で `load_config()` 結果から `PromptConfig` を構築し、`Translator` に渡す。

### 2.8 エラーメッセージ

```
Error: iroiro.toml not found in <cwd>.
  → Run: cp iroiro.toml.example iroiro.toml
  → Or specify: --config /path/to/iroiro.toml

Error: [iroiro] section is required in <path>
Error: [iroiro] system_prompt is required in <path>
Error: [iroiro] reject_phrases is required in <path>
Error: [iroiro.rec_hints] table is required in <path>
```

```
Error: system_prompt must be non-empty str in <path>
Error: reject_phrases[N] must be non-empty str in <path>
Error: reject_phrases must be a list in <path>
Error: [iroiro.rec_hints] must be a table, got <type> in <path>
Error: rec_hints key must be non-empty in <path>
Error: rec_hints[<key>] must be non-empty str in <path>
```

### 2.9 `--dry-run` の挙動

- v0.4 まで: LLM 不要・`iroiro.toml` 無しでも動く
- v0.5: `iroiro.toml` が必須・3 新項目も必須（**LLM を呼ばないが設定検証は走る**）

一貫性のため（案 α の精神）。`--dry-run` で toml エラーが出るのは「設定不備の早期発見」として有用。

---

## 3. 却下代替案

### 3.1 案 β（折衷版）: コード内に予備デフォルトを残す

**却下理由**: 「コードの深いところに魔法の文字列が残る」ことで案 α の字義趣旨から外れる。ユーザー承認済み。

### 3.2 `reject_phrases` の「追加」モード

**却下理由**: 内蔵デフォルト 21 語 + toml 追加、だと「内蔵デフォルト」がコードに残る。案 α では完全 toml 指定なので追加モード不要。ユーザーが 21 語全部を toml に書く（`iroiro.toml.example` から `cp` すれば初期値が入る）。

### 3.3 CLI フラグ `--system-prompt`

**却下理由**: 長文を shell history に残すリスク・セキュリティ的に不適（`--api-key` と同じ理由）。toml のみ提供。

### 3.4 `system_prompt` のプレースホルダ検証

**却下理由**: 「`<alias=` を含まないなら WARNING」等の検証は over-engineering。非空 `str` のみ（ユーザー指定）。

### 3.5 `pyproject.toml [tool.iroiro]` への統合

**却下理由**: v0.3 で却下済み。`pyproject.toml` に個人の LLM エンドポイント・API キーを書くと commit 事故に繋がる。`iroiro.toml`（`.gitignore` 対象）を維持。

---

## 4. テスト戦略

### 4.1 新規テスト（`test_config.py`）

- **T132**: `system_prompt` 非空 `str` のみ受入（`""` / `"   "` / `None` / `123` / `True` 拒否）
- **T133**: `system_prompt` 必須（toml に無いと `IroiroError`）
- **T134**: `reject_phrases` `list[str]` 受入・各要素非空・`bool` 拒否（`[True]` が `int` 経由で混入しない）
- **T135**: `reject_phrases` 重複要素は `frozenset` 化で除去（`["了解", "了解"]` → 1件）
- **T136**: `reject_phrases` 空リスト `[]` は許可（メタ返答チェック無効化）
- **T137**: `reject_phrases` 必須（toml に無いと `IroiroError`）
- **T138**: `[iroiro.rec_hints]` テーブル必須（行自体が無いと `IroiroError`）
- **T139**: `[iroiro.rec_hints]` 空テーブル `{}` は許可（REC ヒント無効化）
- **T140**: `[iroiro.rec_hints]` 各キー非空・各値非空 `str`・`bool` 拒否
- **T141**: `[iroiro.rec_hints]` 未知 REC キー許可（`"FOO:BAR" = "..."` が WARNING 無しで通る・**quoted key 必須**）
- **T142**: `iroiro.toml` ファイル無し時の `load_config` 挙動（v0.5 では `IroiroError`・v0.4 までは `{}` 返却）

### 4.2 既存テストへの影響（Codex review 指摘・拡充）

**重要**: WP-1 で **既存テストが green のまま維持される保証は無い**。WP-2 の実装完了まで新 `PromptConfig` 関連テストは red になる（B1・Codex review 指摘）。

**`test_config.py` への影響**:

- T89 等の「`iroiro.toml` ファイル無し時の `{}` 返却」を期待するテストは v0.5 では **`IroiroError` に変更**
- T94（`[iroiro]` セクション無し → `{}`）は v0.5 では **ファイルが存在するが `[iroiro]` セクションが無い場合も `IroiroError`**（案 α の一貫性・「3 新項目が必須」のため空 `{}` では要件を満たせない・B3）
- 既存の全 fixture（`iroiro_full.toml` / `iroiro_partial.toml` / `iroiro_retry_true.toml` / `iroiro_retry_false.toml` / その他 v0.3/v0.4 fixtures）に **3 新項目を追加**（既存テストが必須チェックで fail しないよう・B4）

**`test_translator.py` への影響**:

- **全 `Translator(cfg, client=...)` 構築箇所** に `PromptConfig` を追加（直接 `REJECT_PHRASES` 参照のみならず全構築に影響・B4）
- `_SYSTEM_PROMPT` / `REJECT_PHRASES` / `_REC_HINTS` 直接参照テストは `PromptConfig` を **テストヘルパー（factory 関数・`tests/conftest.py` 等）** から組み立てる形に修正（**実装コードからデフォルトを import しない**・案 α の一貫性・Codex review 2回目・B7）
- `_is_meta_response(text)` / `_build_user_message(source, rec)` のシグネチャ変更に追随

**注意**: これら既存テストの signature 追随は **WP-2 の最初のタスク**（実装と同時進行でないと red が継続するため・B6）。

### 4.3 新規テスト（`test_translator.py`）

- **T143**: `PromptConfig` を construct して `Translator` に渡す・LLM モックで system メッセージが `PromptConfig.system_prompt` であることを検証
- **T144**: `reject_phrases` をカスタマイズした `PromptConfig` で `_is_meta_response("カスタム語")` が True を返す
- **T145**: `rec_hints` をカスタマイズした `PromptConfig` で user メッセージが カスタムヒントを含む

### 4.4 新規テスト（`test_cli.py`）

- **T146**: `iroiro.toml` 無しで `translate INPUT.xml --dry-run` → exit 2 + エラーメッセージ（v0.3/v0.4 の config error と同じ `typer.Exit(code=2)`・B2）
- **T147**: `iroiro.toml` 有り・3 新項目無し → exit 2 + 各項目の必須エラー（B2）
- **T148**: `iroiro.toml` 有り・3 新項目有り・`--dry-run` → 正常終了（件数表示）

### 4.5 追加テスト（Codex review 指摘）

- **T149**: `[iroiro]` セクション自体が無い toml → `IroiroError`（B3・案 α の一貫性）
- **T150**: 未知の `[iroiro]` セクション内キー（下記 TOML 断片の `unknown_key`・top-level `[other]` テーブルは別物・v0.5 では `[iroiro]` 必須なので `[other]` 単独だと `[iroiro]` 欠損エラーになる）→ WARNING ログのみ・例外送出しない

  ```toml
  [iroiro]
  unknown_key = "x"   # 未知キー → WARNING のみ
  ```
- **T151**: `[iroiro.rec_hints]` に未知の REC キー（`"FOO:BAR" = "..."`・**quoted key 必須**）→ WARNING 無しで許可（T141 と分離して独立テスト化）
- **T152**: `rec_hints` の形エラー（`rec_hints = "x"` のようにテーブルでなく文字列）→ `IroiroError`
- **T153**: `[iroiro.rec_hints]` の値が bool（`"MGEF:FULL" = true`）→ `IroiroError`（厳格 str 検証）
- **T154**: CLI の `translate()` が `load_config()` から `PromptConfig` を構築し `Translator` に渡すことの検証（`--resume` で実際に `Translator` が construct される経路をモックで確認・`--dry-run` では `Translator` が construct されないため non-dry-run 経路が必要）
- **T155**: `iroiro.toml.example` が `tomllib` で parse でき、`load_config()` で通ることの検証（`:` bare key 問題の回帰防止・Codex review 2回目指摘）
- **T156**: `[iroiro.rec_hints]` の quoted REC key（`"MGEF:FULL"`）が期待どおり `dict["MGEF:FULL"]` になることの検証
- **T157**: `rec_hints = {}`（空テーブル）のとき `_build_user_message(source, rec, rec_hints={})` が source のみを返すことの検証（空テーブル許可の仕様閉包）

### 4.6 fixtures

新規:

- `tests/fixtures/iroiro_v05_full.toml` — 全項目（v0.5 デフォルト・`system_prompt` + `reject_phrases` 21語 + `rec_hints` 18種）
- `tests/fixtures/iroiro_v05_missing_prompt.toml` — `system_prompt` 欠損
- `tests/fixtures/iroiro_v05_missing_reject.toml` — `reject_phrases` 欠損
- `tests/fixtures/iroiro_v05_missing_rec_hints.toml` — `[iroiro.rec_hints]` 欠損
- `tests/fixtures/iroiro_v05_empty_reject.toml` — `reject_phrases = []`
- `tests/fixtures/iroiro_v05_custom_prompt.toml` — カスタム `system_prompt`・カスタム `reject_phrases`

既存 fixtures への追記:

- `tests/fixtures/iroiro_full.toml` / `iroiro_partial.toml` / `iroiro_retry_true.toml` / `iroiro_retry_false.toml` 等（v0.3/v0.4 fixtures 全て）に **3 新項目を追加**（必須チェックで fail しないよう）

---

## 5. 実装計画

### WP-1: テスト先行

**許可パス**: `tests/test_config.py`, `tests/test_translator.py`, `tests/test_cli.py`, `tests/fixtures/iroiro_v05_*.toml`, **既存 fixtures（`iroiro_full.toml` 等への 3 新項目追加のみ・既存テストコードの signature 変更は禁止）**
**禁止パス**: `iroiro/*`（実装コード）, **既存テストの `Translator(cfg, client=...)` signature 修正**（← WP-2 の責務）
**依存**: なし（テスト先行）

やること:

1. T132-T142 を `test_config.py` に **新規追加**
2. T143-T145 を `test_translator.py` に **新規追加**（`PromptConfig` の import を含むが、WP-2 で実装されるまでは import error で red・これは期待通り）
3. T146-T148 を `test_cli.py` に **新規追加**
4. T149-T157（Codex review 1-3回目 指摘の追加分）を各テストファイルに **新規追加**
5. fixtures 6個を作成（`iroiro_v05_full.toml` / `iroiro_v05_missing_prompt.toml` / `iroiro_v05_missing_reject.toml` / `iroiro_v05_missing_rec_hints.toml` / `iroiro_v05_empty_reject.toml` / `iroiro_v05_custom_prompt.toml`）— 全て quoted REC key で書く
6. **既存 fixtures（`iroiro_full.toml` / `iroiro_partial.toml` / `iroiro_retry_true.toml` / `iroiro_retry_false.toml` 等）に 3 新項目を追加**（既存テストが必須チェックで fail しないよう・B4）。REC key は quoted で書く。
7. `uv run pytest` を実行し、以下を確認:
   - **既存テストは全て green**（fixtures 拡充により通る・signature は触らないので破壊しない）
   - **新テスト T132-T157 は red**（WP-2 未実装のため `PromptConfig` import error 等・期待通り）

**重要（Codex review 2回目・B6 指摘反映）**: WP-1 では **既存テストコードの signature 修正をしない**。`test_translator.py` の `Translator(cfg, client=...)` 構築箇所への `PromptConfig` 追加は **WP-2 の最初のタスク** に移動する（実装と同時進行でないと既存テストが red になり続けるため）。WP-1 の完了条件は:

- 既存テスト: 全て green（fixture 拡充のみ・signature は触らない）
- 新テスト T132-T157: 全て red（WP-2 完了まで赤いまま正常）

### WP-2: コア実装

**許可パス**: `iroiro/config.py`, `iroiro/translator.py`, `iroiro/cli.py`, `iroiro.toml.example`, **`tests/test_translator.py` の `Translator(cfg, client=...)` 構築箇所の signature 追随のみ**, **`tests/test_cli.py` の `Translator` 構築/mock 箇所の signature 追随のみ**（T154 の `PromptConfig` 注入検証のため・Codex review 3回目指摘）
**禁止パス**: `tests/test_config.py`（WP-1 で完了済み・触らない）, `tests/fixtures/*`（WP-1 で完了済み・触らない）, 他実装モジュール
**依存**: WP-1 のテスト契約（T132-T157・fixtures 拡充）

やること:

0. **【最初のタスク】既存 `test_translator.py` / `test_cli.py` の signature 追随**（Codex review 2-3回目・B6 指摘）:
   - `test_translator.py` の `Translator(cfg, client=...)` 構築箇所を `Translator(cfg, prompts=<PromptConfig>, client=...)` に変更
   - `test_cli.py` の `Translator` 構築 / mock 箇所（特に T154 の `PromptConfig` 注入検証）も同様に signature 追随
   - `PromptConfig` はテストヘルパー（`tests/conftest.py` 等の factory・**実装コードのデフォルトを import しない**・B7）から組み立て
   - これを先にやらないと WP-2 実装中に既存テストが red になり続ける
1. `iroiro/translator.py`:
   - `_SYSTEM_PROMPT` / `_REC_HINTS` / `REJECT_PHRASES` 定数を **完全削除**（案 α）
   - `PromptConfig` dataclass を追加
   - `Translator.__init__` に `prompts: PromptConfig` パラメータを追加
   - `_is_meta_response` / `_build_user_message` を `reject_phrases` / `rec_hints` 引数受取型に変更
   - `translate_entry` / `_translate_with_retry` で `self._prompts` を参照
2. `iroiro/config.py`:
   - `_validate_system_prompt` / `_validate_reject_phrases` / `_validate_rec_hints` validator を追加
   - `_VALIDATORS` に 3 キーを登録
   - **ファイル無し時の `IroiroError` 化**（v0.4 までは `{}` 返却・B3）
   - **`[iroiro]` テーブル自体が存在しない場合も `IroiroError` 化**（v0.4 までは `{}` 返却・B3）
   - 3 キーの必須チェックを追加（ファイル・`[iroiro]` テーブル・各キー各段階）
   - **戻り値の normalisation**: `reject_phrases` は validator 内で `frozenset[str]` に重複除去して normalize・`rec_hints` は `dict[str, str]` のまま（CLI 側で `PromptConfig` 構築時に型固定・Codex review 指摘「validation/normalization は `load_config()` 内で完結・CLI を thin に保つ」に準拠）
3. `iroiro/cli.py`:
   - `RunConfig` に `prompts: PromptConfig` フィールドを追加
   - `translate()` で `load_config()` 結果から `PromptConfig` を構築（validation/normalisation は `load_config()` 側で完結しているので CLI 側は薄い組み立てのみ）
   - `Translator` の初期化で `PromptConfig` を渡す
   - **`--config` の `--help` 説明文を更新**（v0.4 までは「missing config falls back to built-in defaults」だが、v0.5 では「config file is required」に変更・Codex review 指摘）
4. `iroiro.toml.example`:
   - ヘッダを `(v0.3 / v0.4 / v0.5)` に更新
   - `system_prompt` / `reject_phrases` / `[iroiro.rec_hints]` の全文デフォルトを記載（**REC key は全て quoted**）
   - 「LLM 挙動中核・必須」節を追加

**完了条件**:

- 既存テスト: 全て green（signature 追随済み）
- 新テスト T132-T157: 全て green（実装完了）
- `uv run ruff check` / `uv run mypy iroiro` クリーン

### WP-3: docs

**許可パス**: `docs/usage.md`, `docs/design.md`, `docs/development.md`, `README.md`, `AGENTS.md`, `docs/handoff/005-llm-config.md`
**禁止パス**: `iroiro/*`, `tests/*`
**依存**: WP-2 の実装確定後

やること:

1. `docs/usage.md`:
   - 「LLM プロンプトのカスタマイズ（v0.5）」節を追加
   - 「`iroiro.toml` 必須化（v0.5）」節を追加（後方互換性の破れ・移行手順）
2. `docs/design.md`:
   - 「LLM 挙動中核の完全 toml 化（v0.5）」節を追加
   - 設計判断 8項目を記述
3. `docs/development.md`:
   - モジュール表に `PromptConfig` 追加
   - テスト件数更新（165 + 新規 T132-T157 = 191 想定）
4. `README.md`:
   - 「主な機能」に v0.5 追加
   - クイックスタートの `--dry-run` 例に `cp iroiro.toml.example iroiro.toml` を追加
5. `AGENTS.md`:
   - テスト件数更新
   - 「触ってはいけないもの」に `iroiro.toml`（実体）の明記を強化
6. `docs/handoff/005-llm-config.md`:
   - `004-retry-failed.md` テンプレ準拠
   - 後方互換性の破れ・移行手順・手動確認ステップ

---

## 6. 後方互換性の破れと移行（Codex review 指摘・handoff 強化）

### 影響範囲

v0.4 までの以下の操作が v0.5 では **エラー** になる:

```bash
# これらが全てエラーになる
uv run iroiro translate INPUT.xml --dry-run
uv run iroiro translate INPUT.xml --api-base http://localhost:8081/v1 --api-key iroiro
uv run iroiro translate INPUT.xml --config custom.toml  # 3 新項目が無い場合
```

**`--dry-run` を含む全操作で `iroiro.toml` が必須**（一貫性のため）。

### 移行手順 — 新規ユーザー

```bash
# 1回だけ
cp iroiro.toml.example iroiro.toml
# 必要なら編集（api_key / model 等）

# 以降は今まで通り
uv run iroiro translate INPUT.xml --dry-run
uv run iroiro translate INPUT.xml --resume
```

### 移行手順 — 既存ユーザー（v0.4 以下から v0.5 へのアップグレード）

**重要**: 既存の `iroiro.toml` を流用する場合は **3 新項目を手動追加** する必要がある（`cp iroiro.toml.example iroiro.toml` で上書きすると既存の API 設定が消えるため）。

```toml
# 既存 iroiro.toml の [iroiro] セクション内に以下を追記
# （iroiro.toml.example から該当節をコピペ）

# [iroiro] セクション内:
system_prompt  = """..."""                     # 必須・multiline string（全文は example を参照）
reject_phrases = ["了解", "翻訳します"]          # 必須・list[str]（21語全文は example を参照）

# 別テーブルとして追記（[iroiro] の外・ quoted REC key 必須）:
[iroiro.rec_hints]
"MGEF:FULL" = "..."
"BOOK:DESC" = "..."
# ...（18種・全文は example を参照）
```

追加しない場合のエラー:

```
Error: [iroiro] system_prompt is required in iroiro.toml
```

### エラーメッセージ

```
Error: iroiro.toml not found in <cwd>.
  → Run: cp iroiro.toml.example iroiro.toml
  → Or specify: --config /path/to/iroiro.toml
```

親切に「何をすればいいか」を表示する。

---

## 7. リスク

- **R1**: 既存ユーザーが v0.5 に上げた瞬間に `--dry-run` が動かなくなる → エラーメッセージで誘導・handoff で強調
- **R2**: `iroiro.toml.example` の初期値が「現行コード内定数」と **意味的に同等** であることは保証するが、TOML multiline string の改行・空白の細部まで **byte 完全一致** は保証しない（TOML シリアライザの細部に振り回されないため・Codex review 2回目指摘）。ユーザー編集後はユーザー責任。CI で example の構文検証を検討（v0.6 候補・T155 で回帰防止）。
- **R3**: `_is_meta_response` をモジュール関数から引数受取型に変更する際、既存テストのシグネチャ修正が必要 → **WP-2 の最初のタスク（ステップ0）で吸収**（実装と同時進行でないと red が継続するため・B6/B7 指摘と整合）
- **R4**: `[iroiro.rec_hints]` テーブルの「存在するが中身が空」 `{}` を許可するか → 許可する（ユーザーが意図的に REC ヒントを無効化するケース）。ただしテーブル自体が無い場合は必須エラー。

---

## 8. 受け入れ基準

- [ ] `iroiro.toml` 無しで実行すると分かりやすいエラー
- [ ] `iroiro.toml` 有り・3 新項目無しで実行すると各項目の必須エラー
- [ ] `iroiro.toml` 有り・3 新項目有りで v0.4 と同じ挙動（`cp iroiro.toml.example iroiro.toml` 直後）
- [ ] `system_prompt` をカスタマイズすると LLM への system メッセージが変わる
- [ ] `reject_phrases` をカスタマイズするとメタ返答判定が変わる
- [ ] `[iroiro.rec_hints]` をカスタマイズすると user メッセージのヒントが変わる
- [ ] `iroiro/translator.py` から `_SYSTEM_PROMPT` / `_REC_HINTS` / `REJECT_PHRASES` が完全削除されている
- [ ] `uv run pytest` 全件 green（新規 T132-T157 含む）
- [ ] `uv run ruff check` クリーン
- [ ] `uv run mypy iroiro` クリーン
- [ ] Codex plan review 通過
- [ ] Codex final review 通過
- [ ] QA review 通過

---

## 9. 言語ポリシー

- 全 docstring / コメント / ドキュメント / handoff は **日本語**
- 技術識別子（`system_prompt` / `reject_phrases` / `rec_hints` / `PromptConfig` / `RunConfig` / `Translator`）は英語のまま
- toml 内の `system_prompt` 文・`reject_phrases` 語句・`rec_hints` 値は **日本語**（LLM への指示内容・ユーザー編集対象）

---

## 10. 次のステップ

1. 本計画書を Codex CLI で plan review ✅（2026-06-29・指摘反映済み）
2. WP-1（テスト先行）を implementer に委譲
3. WP-2（コア実装）を implementer に委譲
4. WP-3（docs）を implementer に委譲
5. PM 統合 diff 検査
6. Codex final diff review
7. QA final review
8. GaOTTT writeback
9. commit & push

---

## 11. Codex plan review 反映記録（2026-06-29）

**Verdict**: Needs revision → 指摘反映済み

### Blocking issues → 解決

- **B1**: `[iroiro.rec_hints]` 空テーブル方針の矛盾 → §2.2 表で「テーブル自体は必須・中身が空 `{}` は許可」に統一
- **B2**: exit code 1 vs 2 の不整合 → T146/T147 を `exit 2`（`typer.Exit(code=2)`）に統一
- **B3**: `[iroiro]` セクション無し時の挙動「要検討」→ `IroiroError` に確定（§2.8 エラーメッセージ・§4.2 影響・§4.5 T149・WP-2 に明記）
- **B4**: テスト影響の過小評価 → §4.2 を全面拡充（既存 fixtures への 3 新項目追加・`test_translator.py` の全 `Translator` 構築に `PromptConfig` 追加・WP-1 完了条件に「新テストは red・既存は green」を明記）

### Non-blocking issues → 解決

- **N1**: `PromptConfig` の `frozen=True` が `dict[str, str]` と矛盾 → `frozen=True` を削除（§2.6 に理由コメント追加）
- **N2**: `bool` 拒否の理屈が不正確 → §2.5 を「厳格型検証思想（既存 validator と対称）」に修正
- **N3**: エラーメッセージ「`rec_hints table`」と「`[iroiro.rec_hints]`」の表記揺れ → `[iroiro.rec_hints]` に統一

### Missing tests → 追加（§4.5）

- T149: `[iroiro]` セクション無し → `IroiroError`
- T150: 未知 top-level キー → WARNING のみ
- T151: 未知 REC キー → WARNING 無し（T141 から分離）
- T152: `rec_hints` の形エラー
- T153: `rec_hints` 値が bool
- T154: CLI config→prompt 接続検証

### Documentation issues → 反映

- `iroiro/cli.py` の `--config` `--help` 説明文更新を WP-2 に明記

### Handoff issues → 反映

- §6 を全面改稿（新規ユーザー・既存ユーザー別の手順・3 新項目の手動追記を強調）

### Integration issues → 反映

- `load_config()` 戻り値の normalisation を WP-2 に明記（`reject_phrases` を `frozenset` 化・`rec_hints` を `dict[str, str]` のまま・CLI は thin に保つ）

### Final recommendation（Codex）

> Revise the plan before implementation. The 案 α direction, `PromptConfig` injection, and pure-function `_is_meta_response` / `_build_user_message` design are sound.

→ **指摘全て反映済み**。WP-1 に進む。

---

## 12. Codex plan review 2回目 反映記録（2026-06-29）

**Verdict**: needs-revision（追加 blocking 3件）→ 指摘反映済み

### Blocking issues → 解決

- **B5**: `[iroiro.rec_hints]` の TOML 例が invalid（`MGEF:FULL` のような bare key は `:` を含むため `tomllib` で parse error）→ 全 REC key を **quoted key**（`"MGEF:FULL"`）に統一・§2.4 に注意書き追加・`iroiro.toml.example`/fixtures/docs の全例で統一
- **B6**: WP-1 の完了条件が矛盾（「既存 `Translator(...)` signature 修正」+「WP-1 で既存 green」が両立しない）→ 既存テストの signature 追随を **WP-2 の最初のタスク** に移動・WP-1 は「fixtures 拡充のみ・既存 green 維持」に明確化
- **B7**: 「デフォルト値を import」方針が案 α と衝突（実装側にデフォルト定数を再導入させる危険）→ テストヘルパー（factory 関数・`tests/conftest.py`）から `PromptConfig` を組み立てる方針に明記

### Non-blocking issues → 解決

- T150 の「未知 top-level キー」表現を「未知 `[iroiro]` セクション内キー」に修正（top-level `[other]` は別物・v0.5 では `[iroiro]` 必須なので `[other]` 単独は `[iroiro]` 欠損エラー）
- R2 の「`cp` 直後は完全一致」を **byte 完全一致ではなく意味的同等** に緩和（TOML multiline string の細部に振り回されないため）

### Missing tests → 追加（§4.5 T155-T157）

- T155: `iroiro.toml.example` の `tomllib` parse 検証（`:` bare key 問題の回帰防止）
- T156: quoted REC key（`"MGEF:FULL"`）が `dict["MGEF:FULL"]` になる検証
- T157: 空 `rec_hints` 時の `_build_user_message` が source のみを返す検証

### Documentation issues → 反映

- テスト件数 182 → **191**（T132-T157）
- 受け入れ基準のテスト範囲 T132-T148 → **T132-T157**
- `iroiro.toml.example`・fixtures・handoff の REC key を全て quoted に統一（B5）

### Final recommendation（Codex 2回目）

> 前回指摘の多くは解消されていますが、quoted TOML key 問題と WP-1 完了条件の矛盾は実装を止めるべき blocking です。そこを直せば `approve-with-notes` に近い内容です。

→ **指摘全て反映済み**。3回目の review に進む。
