# 003 — 設定ファイル (iroiro.toml) 対応

## ステータス

- バージョン: v0.3
- リスク分類: **normal**（新機能・3-4 ファイル影響・後方互換性あり）
- 日付: 2026-06-28
- 依頼者確定事項:
  - Q1. ファイル形式: **A（`iroiro.toml` 専用）**
  - Q2. 「コンテキスト長」: **(a) `max_chars`** のこと
  - Q3. 環境変数: **非対応（CLI と toml の2経路のみ）**

## 1. 目標

カレントディレクトリの `iroiro.toml` を読み込み、LLM エンドポイント・API キー・
モデル名・タイムアウト・並列数・`max_chars` の **デフォルト値を上書き** できるようにする。
CLI フラグで明示指定した場合は toml より優先する。

## 2. 背景

現状（v0.2.1 時点）では、これら6項目のデフォルト値は `iroiro/cli.py` L70-76 の
`DEFAULT_*` 定数にハードコードされている。毎回 `--api-base http://...` のように
CLI フラグを打つ必要があり、**LLM サーバーを頻繁に切り替える利用者**（llama.cpp /
LM Studio / リモート OpenAI 互換サーバー等）には負担が大きい。

v0.1 設計判断（`docs/plans/001-initial.md` §13）では「デフォルト値 + CLI フラグ上書き」
で合意済み。設定ファイル排除の意図ではなく、単に v0.1 スコープ外だった。
ユーザー要望により v0.3 で追加する。

## 3. 現状

### 3.1 設定 dataclass

`iroiro/translator.py` L38-56:

```python
@dataclass(slots=True)
class ApiConfig:
    base_url: str
    api_key: str
    model: str
    timeout: float
    concurrency: int
    max_chars: int
```

`iroiro/config.py` L11-32 の `RunConfig` は `ApiConfig` を内包する。
**この構造は変更しない**（後方互換）。

### 3.2 CLI フラグとデフォルト

`iroiro/cli.py` L70-76 + L80-123 の `translate()`:

```python
DEFAULT_API_BASE = "http://localhost:8081/v1"
DEFAULT_API_KEY = "iroiro"
DEFAULT_MODEL = "ggml-org/gemma-4-12B-it-GGUF:Q4_K_M"
DEFAULT_CONCURRENCY = 1
DEFAULT_MAX_CHARS = 4000
DEFAULT_TIMEOUT = 120.0
```

各フラグはデフォルト値を持つ。`translate()` はフラグ値をそのまま `ApiConfig` に渡す。

## 4. 設計方針

### 4.1 設定ファイル形式

- **ファイル名**: `iroiro.toml`（専用・cwd 直下）
- **セクション**: 単一 `[iroiro]` テーブル
- **キー命名**: `snake_case`（Python 内部のフィールド名と一致・変換不要）
- **パーサー**: `tomllib`（Python 3.11+ 標準・3.12 なので追加依存なし）

### 4.2 `iroiro.toml` のスキーマ

```toml
# iroiro-translator 設定ファイル（v0.3）
# 詳細は docs/usage.md 参照

[iroiro]
api_base    = "http://localhost:8081/v1"
api_key     = "iroiro"
model       = "ggml-org/gemma-4-12B-it-GGUF:Q4_K_M"
timeout     = 120.0
concurrency = 1
max_chars   = 4000
```

**全項目省略可能**。書かれていない項目は内蔵デフォルト値に落ちる。

### 4.3 検索順序（発見規則）

1. **`--config PATH`** で明示指定された場合は **そのファイルのみ** 読む。
   存在しない場合は即時エラー（exit code 2）。
2. **`--config` 無指定時**は cwd の `iroiro.toml` を探す。
   - 存在すれば読む。存在しなければ **何もしない**（v0.1 動作・後方互換）。
3. **親ディレクトリへの遡りはしない**（git の `.git` 探索のような動作は v0.3 では導入しない。
   「知らぬ間に親の `iroiro.toml` が読まれる」混乱を避けるため）。

### 4.4 優先順位（マージ規則）

```
強 ← CLI フラグ（明示指定時）  ＞  iroiro.toml  ＞  内蔵デフォルト（DEFAULT_*）  → 弱
```

「明示指定時」の判定方法は **Typer の `Optional[type] = None` パターン** +
**`is None` チェック**（falsy 判定を避けるため）:

```python
def _resolve(cli_val: T | None, file_cfg: dict[str, object], key: str, default: T) -> T:
    """CLI フラグ（非 None）＞ toml ＞ 内蔵デフォルト、で解決する。"""
    if cli_val is not None:
        return cli_val
    if key in file_cfg:
        return file_cfg[key]  # 型は load_config が保証済み
    return default


def translate(
    input: Path,
    api_base: str | None = typer.Option(None, "--api-base", help="..."),
    ...
):
    file_cfg = load_config(config_path)  # dict[str, object] を返す・型検証済み
    base_url = _resolve(api_base, file_cfg, "api_base", DEFAULT_API_BASE)
    api_key = _resolve(api_key, file_cfg, "api_key", DEFAULT_API_KEY)
    timeout = _resolve(timeout, file_cfg, "timeout", DEFAULT_TIMEOUT)
    ...
```

**重要**: `or` 演算子は `0` や `""` を falsy 扱いしてしまうので **絶対に使わない**。
`is None` チェック必須。これにより:
- `--max-chars 0` は「明示的に 0 を指定」として採用される（0 = 全件スキップ扱い・後述）
- `--api-key ""` は「空文字を明示」として採用される

`_resolve` helper を `cli.py` に置くことで、`dict[str, object]` を直接扱う箇所を
局所化し、mypy の型汚染を防ぐ。

### 4.5 型・値域・エラー処理

#### 4.5.1 各項目の型と値域（正味仕様）

| キー | 型 | 値域 | 備考 |
|---|---|---|---|
| `api_base` | `str` | 非空（`""` 拒否） | URL 形式の厳密チェックはしない（llama.cpp 等の柔軟性のため） |
| `api_key` | `str` | `""` 許可 | llama.cpp は検証しないので空でも動く。ただし OpenAI 互換サーバーでは認証失敗 |
| `model` | `str` | `""` 拒否 | OpenAI クライアントに渡すモデル名 |
| `timeout` | `float` | `> 0` | 0 秒や負数は不可 |
| `concurrency` | `int` | `>= 1` | `Translator` が `max(1, n)` で clamp するが、toml 側は厳格に `>= 1` を要求 |
| `max_chars` | `int` | `>= 0` | `0` は「全件スキップ」の正当値（`len(source) > 0` が常に真） |

**`bool` 拒否**: Python では `bool` は `int` のサブクラス（`isinstance(True, int) == True`）。
`timeout = true` のような書き間違いを数値として受け入れてしまう事故を防ぐため、
**`isinstance(v, bool)` なら型エラーとして拒否** する。

#### 4.5.2 エラー処理一覧

| 状況 | 挙動 |
|---|---|
| `--config PATH` が存在しない | `Error: config file not found: PATH` → exit 2 |
| `iroiro.toml` が存在しない（cwd） | 何もしない（後方互換・何も出力しない） |
| `iroiro.toml` の TOML パース失敗 | `Error: invalid TOML in iroiro.toml: <詳細>` → exit 2 |
| `[iroiro]` セクションが存在しない（`[other]` だけ等） | `{}` を返す（警告なし・空と同じ） |
| `[iroiro]` がテーブルでない（`iroiro = "x"` 等） | `Error: iroiro.toml: [iroiro] must be a table` → exit 2 |
| 未知のキー（`[iroiro] unknown = "x"`） | **警告ログを出して続行**（前方互換のため）。**既知キーは反映** |
| 型不一致（`timeout = "abc"` / `api_base = 123`） | `Error: iroiro.toml: <key> must be <expected>, got <actual>` → exit 2 |
| bool を数値に割当（`timeout = true`） | 型エラー（上記と同じ・`bool` 拒否） |
| 値域エラー（`timeout = -1` / `concurrency = 0` / `api_base = ""` 等） | `Error: iroiro.toml: <key> must be <range>, got <value>` → exit 2 |

### 4.6 git 管理方針

- **`iroiro.toml.example`**（雛形・git 管理対象）: 全項目をコメントアウトした状態で置く。
- **`iroiro.toml`**（実体・`.gitignore` 対象）: 各ユーザーが個別に作成。`.env` と同じ運用。

LLM のエンドポイントや API キーは環境依存の個人情報・ローカルネット情報なので、
プロジェクト共有の `pyproject.toml` には入れない方針（Q1=A 採用理由）。

#### 4.6.1 セキュリティ注意事項（docs/usage.md に必ず明記）

- **`api_key` の露出リスク**: CLI フラグ `--api-key XXX` は shell history・`ps` 出力・
  bash `HISTFILE` に残る。本番環境では `iroiro.toml`（gitignore 対象・ファイル権限 `0600` 推奨）
  の方が安全。
- **`iroiro.toml.example` に実キーを書かない**: 雛形は必ずダミー値のまま commit する。
- **`chmod 600 iroiro.toml`** を推奨（他ユーザー読取防止）。
- **共有環境では `--api-key` を使わない**: シェル履歴から漏洩する。

## 5. スコープ

### 5.1 含む

- `iroiro.toml` ローダー（`iroiro/config.py` に追加）
- `translate` コマンドへの `--config PATH` フラグ追加
- 既存6フラグ（`--api-base` 等）の `Optional[...] = None` 化
- `iroiro.toml.example` の作成（git 管理対象）
- `.gitignore` に `iroiro.toml` 追加
- ドキュメント更新（usage.md / design.md / development.md / README / AGENTS.md）

### 5.2 含まない（Non-goals）

- **親ディレクトリ遡り探索**: しない（§4.3 参照）。
- **環境変数サポート**: しない（Q3 で却下）。
- **`pyproject.toml [tool.iroiro]` サポート**: しない（Q1=B/C で却下）。
- **グローバル設定（`~/.config/iroiro/config.toml` 等）**: しない。
- **`skip_records` / `reject_phrases` の toml 化**: しない（v0.4 以降で検討）。
- **`iroiro.toml` のスキーマバージョニング**: しない（必要になれば `version` キー追加）。
- **暗号化・権限管理**: しない（`.env` と同等の「自己責任」運用）。

## 6. テスト戦略

新規 `tests/test_config.py`（仮称・ユニット中心）+ `tests/test_cli.py`（既存）への追加。

### 6.1 ローダーのユニットテスト（`tests/test_config.py`）

| ID | 内容 |
|---|---|
| T88 | `load_config(None)` — cwd に `iroiro.toml` 無し → `{}`（空 dict） |
| T89 | `load_config(None)` — cwd に `iroiro.toml` 有り・全項目記述 → 全項目反映 |
| T90 | `load_config(None)` — 一部項目のみ記述 → その項目だけ・残りは含まれない（呼出側でデフォルト） |
| T91 | `load_config(Path("custom.toml"))` — 明示パス読込 |
| T92 | `load_config(Path("missing.toml"))` — 存在しない → `IroiroError`（メッセージにパス含む） |
| T93 | 無効 TOML（シンタックスエラー） → `IroiroError`・メッセージに詳細含む |
| T94 | `[iroiro]` テーブル無し（`[other]` だけ） → `{}`（空 dict・警告なし） |
| T95 | `[iroiro]` がテーブルでない（`iroiro = "x"`） → `IroiroError` |
| T96 | 型エラー（`timeout = "abc"`） → `IroiroError` |
| T97 | 値域エラー（`timeout = -1`） → `IroiroError` |
| T98 | 未知キー + 既知キー混在 → **警告ログを出力しつつ既知キーだけ反映**（未知キーは無視・`{}` ではない） |
| T99 | bool を数値フィールドに（`timeout = true`） → `IroiroError`（`bool ⊂ int` 事故防止） |
| T100 | 文字列フィールドに int（`api_base = 123`） → `IroiroError` |
| T101 | `api_base = ""`（空文字） → `IroiroError`（値域エラー） |
| T102 | `max_chars = 0` → **正当値として受理**（0 = 全件スキップの意味） |

> fixture は `tests/fixtures/iroiro_*.toml` に置く。`tmp_path` を使って
> 実際の cwd に依存しない形でテストする（`monkeypatch.chdir(tmp_path)`）。

### 6.2 CLI 統合テスト（`tests/test_cli.py` に追加）

| ID | 内容 |
|---|---|
| T103 | `iroiro.toml` 無し cwd + フラグ無し → 内蔵デフォルト使用（v0.1 互換・回帰保証） |
| T104 | `iroiro.toml` 有り + フラグ無し → toml 値が `RunConfig` に反映される |
| T105 | `iroiro.toml` 有り + `--api-base X` 明示 → フラグが優先（toml の `api_base` は無視） |
| T106 | `--config custom.toml` → 指定パスが読まれる（cwd の `iroiro.toml` は無視） |
| T107 | `--config missing.toml` → exit code 2・エラーメッセージ |
| T108 | toml に `max_chars = 4000` + CLI `--max-chars 0` 明示 → **CLI の `0` が勝つ**（falsy で埋もれない） |
| T109 | toml に `api_key = "secret"` + CLI `--api-key ""` 明示 → **CLI の空文字が勝つ** |

> T103-T109 は `CliRunner` と `monkeypatch` で dry-run（`--dry-run`）で検証可能。
> LLM は呼ばないので確実。

### 6.3 既存テストの後方互換性確認

`uv run pytest` 全件 green を保証。特に:
- `tests/test_cli.py` の既存フラグ動作テスト（`--api-base` 等を明示渡しているもの）は
  `Optional` 化しても動くはず（値を明示渡せば `None` ではないので）。

## 7. 実装計画（Work Package）

### 7.1 WP 構成

| WP | Goal | Files | 並列可 |
|---|---|---|---|
| WP-1 | テスト + fixture | `tests/test_config.py`（新）, `tests/test_cli.py`（追）, `tests/fixtures/iroiro_*.toml`（新） | 〇（先行・契約固定） |
| WP-2 | ローダー + CLI 改修 | `iroiro/config.py`, `iroiro/cli.py`, `iroiro.toml.example`（新）, `.gitignore` | ×（WP-1 の関数シグネチャ契約必要） |
| WP-3 | docs + handoff | `docs/usage.md`, `docs/design.md`, `docs/development.md`, `README.md`, `AGENTS.md`, `docs/handoff/003-config-file.md`（新） | 〇（草案は WP-2 と並行・最終確認は後） |

**直列**: WP-1 → WP-2 → WP-3 最終確認。
**並行可**: WP-1 と WP-3 草案（実装非依存部）。

### 7.2 WP-1: テスト実装（先行）

**Allowed paths**: `tests/test_config.py`, `tests/test_cli.py`, `tests/fixtures/`
**Forbidden paths**: `iroiro/`, `pyproject.toml`, `.gitignore`, `docs/`, `README.md`, `AGENTS.md`

**関数契約**（WP-2 が実装する側）:

```python
# iroiro/config.py に追加
def load_config(explicit_path: Path | None) -> dict[str, object]:
    """iroiro.toml を読んで [iroiro] セクションの dict を返す。

    Args:
        explicit_path: --config で明示指定されたパス。None なら cwd の iroiro.toml を探す。

    Returns:
        [iroiro] テーブルの dict。ファイル無し・[iroiro] セクション無しは {} を返す。
        返される値は全て **型検証・値域検証済み**（呼出側はキャスト不要）。

    Raises:
        IroiroError: ファイル無し（--config 明示時のみ）・パースエラー・
            型エラー・値域エラー・[iroiro] がテーブルでない。
    """
```

**検証ルール**（WP-1 と WP-2 で一致させる契約・§4.5 参照）:

- 戻り値の `dict` に含まれる値は全て **型検証・値域検証済み**。
- `bool` は `int` フィールドに渡しても型エラー（Python `bool ⊂ int` 事故防止）。
- `api_base`/`model`: `str`・非空。
- `api_key`: `str`・空文字許可。
- `timeout`: `float`・`> 0`。
- `concurrency`: `int`・`>= 1`。
- `max_chars`: `int`・`>= 0`（0 は正当値 = 全件スキップ）。
- 未知キー混在時: 警告ログを出すが **例外送出しない**・既知キーは返り値に含める。

### 7.3 WP-2: ローダー + CLI 改修

**Allowed paths**: `iroiro/config.py`, `iroiro/cli.py`, `iroiro.toml.example`, `.gitignore`
**Forbidden paths**: `tests/`, `pyproject.toml`, `README.md`, `docs/`, `AGENTS.md`

実装内容:

1. `iroiro/config.py` に `load_config()` 追加。
2. `iroiro/cli.py`:
   - `translate()` に `--config PATH` フラグ追加（型 `Path | None = None`）。
   - 既存6フラグを `Optional[type] = None` に変更（`--api-base` 等の名前はそのまま）。
   - **フラグの `help=` テキスト** を書き換え: Typer の Optional 化で `[default: None]`
     になってしまうため、ユーザーが迷わないよう「未指定時は `iroiro.toml` → 内蔵
     デフォルトの順で解決」と明記。例:
     ```python
     api_base: str | None = typer.Option(
         None, "--api-base",
         help="OpenAI 互換 API のベース URL（未指定時は iroiro.toml → 内蔵デフォルト）",
     )
     ```
   - `_resolve()` helper を追加（§4.4 参照）・全6項目に適用。
   - マージ後の値で `ApiConfig` を構築（既存コードと同じ）。
3. `iroiro.toml.example` を新規作成（全項目コメントアウト版 + 例 + §4.6.1 セキュリティ注意書き）。
4. `.gitignore` に `iroiro.toml` を追加（`*.translated.xml` 群の近く・コメント付き）。

### 7.4 WP-3: ドキュメント

**Allowed paths**: `docs/usage.md`, `docs/design.md`, `docs/development.md`, `README.md`, `AGENTS.md`, `docs/handoff/003-config-file.md`
**Forbidden paths**: `iroiro/`, `tests/`, `pyproject.toml`, `.gitignore`

更新内容:

- **`docs/usage.md`**: 「設定ファイル」節を新設。`iroiro.toml` の書き方・優先順位・
  `iroiro.toml.example` の使い方・`--config` の説明・§4.6.1 セキュリティ注意事項。
- **`docs/design.md`**: 設定読込の設計判断（§4.1-4.5 を要約）。なぜ `pyproject.toml`
  でなく `iroiro.toml` か（個人情報混入回避）・なぜ親遡りしないか・なぜ `bool` を拒否するか。
- **`docs/development.md`**: モジュール構成に `load_config` 追加。
- **`README.md`**: 「クイックスタート」に1行追加（`iroiro.toml` でデフォルト変更可・詳細は usage.md）。
- **`AGENTS.md`**: 「触ってはいけないもの」表に `iroiro.toml`（実体）を **gitignore 運用**
  としてのみ追記（ユーザー向け usage docs にはしない・AI agent 向け gitignore 指導のみ）。
- **`docs/handoff/003-config-file.md`**: 新規・標準テンプレート使用。

## 8. ドキュメント影響

- README.md: 軽微（1行追加）
- docs/usage.md: 中規模（新節）
- docs/design.md: 中規模（設計判断追記）
- docs/development.md: 軽微（モジュール表追記）
- AGENTS.md: 軽微（表1行追記）

言語ポリシー: 日本語（既存の方針維持）。

## 9. 引き継ぎ影響

`docs/handoff/003-config-file.md` を新規作成。v0.2.1 までの機能（skip-records・
post-processing 強化）に加えて、v0.3 の `iroiro.toml` 機能を記載。

## 10. 言語ポリシー影響

- `iroiro.toml` 内キー: `snake_case`（英語識別子）。
- `iroiro.toml` 内コメント: 日本語可（ユーザー向け・TOML 仕様上 OK）。
- エラーメッセージ: 英語（既存方針維持・`config file not found: ...` 等）。
- ドキュメント・コメント・handoff: 日本語（既存方針維持）。

## 11. リスク

### 11.1 後方互換性破壊

- **リスク低**: CLI フラグを `Optional = None` 化しても、既存ユーザーが明示的に
  フラグを渡している場合はその値が使われる。省略時のみ toml を探す（見つからなければ v0.1 同様）。
- **回帰保証**: T98 で明示的に保証。

### 11.2 既存テストの破壊

- **リスク中**: `tests/test_cli.py` の既存テストが `translate(input=..., api_base=...)`
  のようにキーワード引数で呼んでいる場合、`Optional` 化で影響なし。`CliRunner.invoke()`
  経由の場合もフラグ文字列は変わらないので影響なし。
- **対策**: WP-2 完了後に全テスト green を必ず確認。

### 11.3 Typer の Optional フラグ落とし穴

- Typer は `Optional[type] = None` にするとヘルプ表示で `[default: None]` になる。
  ユーザーが「デフォルトは何？」と迷う可能性。
- **対策**: 各フラグの `help=` に「未指定時は `iroiro.toml` → 内蔵デフォルトの順」
  と明記。

### 11.4 toml ファイルの誤配置

- ユーザーが `iroiro.toml` を cwd ではなく「XML と同じディレクトリ」に置く誤解が想定される。
- **対策**: docs/usage.md で「cwd（コマンドを実行するディレクトリ）」と明記。

### 11.5 WP-1 / WP-2 の検証契約不一致（Codex 指摘）

- WP-1 tests 先行で「`max_chars = 0` は正当か」「bool は int 扱いか」「未知キー時の挙動」
  について WP-2 と見解がズレると、テスト通過後に実装が破壊されるリスク。
- **対策**: §7.2 で検証ルールを明文化し、WP-1・WP-2 とも同じ契約を参照する。
  PM は WP-2 完了後に「WP-1 の期待と WP-2 の実装が一致しているか」を diff 検査で確認。

## 12. 受入基準

- [ ] `uv run pytest` 全件 green（既存122件 + 新規22件 = 144件想定）。
- [ ] `uv run ruff check iroiro/ tests/` クリーン。
- [ ] `uv run mypy iroiro` クリーン。
- [ ] `uv run iroiro translate --help` に `--config` フラグが表示される。
- [ ] `iroiro.toml.example` が存在し、全項目コメントアウト済み。
- [ ] `.gitignore` に `iroiro.toml` が含まれる（`iroiro.toml.example` は含まれない）。
- [ ] `iroiro.toml`（実体）を作って `uv run iroiro translate sample.xml --dry-run`
  で値が反映されることを手動確認。
- [ ] Codex CLI 最終 diff レビュー: approve または approve-with-notes。
- [ ] QA レビュー: pass または pass-with-notes。

## 13. レビューゲート（normal）

- [x] ユーザーと本計画 v0.3 の合意（Q1/Q2/Q3 確定）
- [ ] Codex CLI: プランレビュー v0.3
- [ ] （必要なら）改訂
- [ ] WP-1 実装（テスト・フィクスチャ）
- [ ] WP-2 実装（`iroiro/` 本体・`iroiro.toml.example`・`.gitignore`）
- [ ] WP-3 実装（docs・handoff）
- [ ] テスト全件実行
- [ ] PM combined diff 検査
- [ ] Codex CLI: 最終 diff レビュー
- [ ] QA 最終レビュー
- [ ] Final report

## 14. 代替案と却下理由

- **`pyproject.toml [tool.iroiro]`**: Q1=B でユーザー却下。LLM のエンドポイント・
  API キーは環境依存の個人情報・ローカルネット情報なのでプロジェクト共有ファイルに
  入れたくない。
- **環境変数（`IROIRO_API_BASE` 等）**: Q3 でユーザー却下。「toml と CLI の2経路で十分」。
- **親ディレクトリ遡り探索**: 複雑性と「知らぬ間に親の `iroiro.toml` が読まれる」
  混乱を避けるため却下（将来必要になれば追加）。
- **JSON / YAML 設定ファイル**: Python 3.12 は `tomllib` を標準搭載（追加依存なし）。
  JSON はコメントが書けない。YAML は追加依存が必要。TOML が最適。
- **`iroiro config init` コマンド**: `iroiro.toml.example` を copy すれば済むので
  v0.3 では不要。
- **`skip_records` / `reject_phrases` の toml 化**: スコープ膨張を避けるため v0.4 以降。

## 15. GaOTTT memory writeback（計画確定後）

計画が Codex approve されたら、以下を GaOTTT に保存:

- v0.3 の設計判断: `iroiro.toml` 専用方式採用・理由（個人情報のプロジェクト混入回避）。
- 優先順位: CLI フラグ（明示）＞ `iroiro.toml` ＞ 内蔵デフォルト。
- 検索位置: cwd のみ・親遡りしない（v0.3）。
- TOML キー命名: `snake_case`（Python 内部統一）。
- git 管理方針: `iroiro.toml.example`（管理）と `iroiro.toml`（.gitignore）の2ファイル運用。
