# 開発者向け

iroiro-translator の開発環境・テスト・モジュール構成・ロードマップ。設計の背景は
[設計判断](design.md) を、実装の経緯は [実装計画](plans/001-initial.md) を参照。

---

## 開発環境セットアップ

### 必要環境

- **Python 3.12+**（`.python-version` 参照）
- **[uv](https://docs.astral.sh/uv/)** — Python パッケージ・環境管理

### セットアップ

```bash
git clone <repository-url> iroiro-translator
cd iroiro-translator
uv sync           # dev extras（pytest / ruff / mypy）を含めて依存関係を同期
```

`uv sync` は `uv.lock` に基づいて `.venv/` を構築する。以降のコマンドは `uv run` 経由で
仮想環境内のツールを呼び出す。

---

## テスト・品質チェック

### テスト全実行

```bash
uv run pytest                          # 109 テスト（v0.1: 73 + v0.2: 36）
uv run pytest -k "xml_io"              # 個別実行（キーワード指定）
uv run pytest --tb=no -q               # 簡易出力
```

テストは `httpx.MockTransport` ベースのモック LLM を使用するため、ネットワーク接続不要で実行できる。
テストケース ID（T1-T55）と実装計画 §7 の対応は [実装計画](plans/001-initial.md#7-テスト戦略) を参照。

### リント・型チェック

```bash
uv run ruff check iroiro/ tests/       # リント（E/F/W/I/B/UP ルール）
uv run mypy iroiro                     # 型検査（iroiro/ のみ・strict ではない）
```

- ruff 設定: `pyproject.toml` の `[tool.ruff]` / `[tool.ruff.lint]` 参照
- mypy 設定: `pyproject.toml` の `[tool.mypy]` 参照。段階的型導入（`iroiro/` のみ検査）

---

## モジュール構成

```
iroiro/
├── __init__.py        # パッケージ初期化・__version__
├── __main__.py        # python -m iroiro エントリポイント
├── cli.py             # typer ベースの CLI。translate サブコマンド
├── config.py          # RunConfig dataclass
├── errors.py          # IroiroError 共通例外
├── escape.py          # プレースホルダ検出（extract_tokens）/ 整合性検証（tokens_match）
├── logging.py         # rich ベースの進捗表示ヘルパ
├── models.py          # StringEntry / FileFormat dataclass
├── progress.py        # ProgressWriter（asyncio.Lock + 原子書き込み）/ ProgressData
├── translator.py      # Translator / ApiConfig / is_translation_needed（OpenAI 互換クライアント）
└── xml_io.py          # parse_xml / serialize_xml（BOM/CRLF/宣言保持）
```

各モジュールの責務は [実装計画 §5.3](plans/001-initial.md) を参照。コードを読む推奨順序:

1. `iroiro/cli.py` — 全体フロー（parse → resume → dry-run → translate → serialize）
2. `iroiro/models.py` — `StringEntry` / `FileFormat` の dataclass
3. `iroiro/xml_io.py` — BOM/CRLF/宣言保持戦略の中核。最も注意深くレビューすべき箇所
4. `iroiro/escape.py` + `iroiro/translator.py` — プレースホルダ保護と LLM クライアント
5. `iroiro/progress.py` — 並行安全な再開機能

---

## テスト戦略の概要

3層構造で網羅する:

### 1. ユニットテスト（`tests/test_*.py`）

各モジュール単位のテスト。`httpx.MockTransport` を `openai.AsyncOpenAI(http_client=...)` に
注入することで、LLM への実リクエストを送らずにプロトコル・post-processing・エラーハンドリングを検証。

| テストファイル | 対象 |
|---|---|
| `tests/test_xml_io.py` | XML I/O 周辺（T1-T10, T47-T53, T68）。round-trip・BOM/CRLF/宣言保持・CDATA/comment 検出・空要素展開 |
| `tests/test_escape.py` | プレースホルダ検出・整合性検証（T11-T18, T45） |
| `tests/test_progress.py` | 並行安全な progress.json 読み書き（T19-T25, T46, T50, T77-T80, T83） |
| `tests/test_translator.py` | 翻訳エンジン・post-processing・リトライ（T26-T34, T41-T44, T51, T56-T63, T71-T76, T81/T81b） |
| `tests/test_cli.py` | E2E（T36-T40, T64-T67, T69-T70, T82）。`CliRunner` 経由で `translate` サブコマンドを検証 |

### 2. フィクスチャ（`tests/fixtures/`）

XML I/O の検証用に小さなサンプル XML を同梱（実データ由来でない自作フィクスチャ）:

- `tiny.xml` — 数件、alias / `<br>` / `%{...}` / 空文字 含む
- `tiny_crlf_bom.xml` — BOM + CRLF の実物コピー
- `japanese_source.xml` — 既に日本語の Source を含む
- `long_source.xml` — `max-chars` 超過
- `with_comment.xml` / `with_cdata.xml` — コメント・CDATA 検出用
- `skip_records.xml` — HDPT/WEAP/MGEF/RACE/BPTD/ACTI/空/日本語 の8エントリを含むテスト用 XML（BOM + CRLF + `standalone="yes"`）

### 3. E2E（実 LLM）

実 LLM による E2E は CI 上では実施せず、ユーザー環境での手動検証に委ねる。
v0.1 では Gemma 4 12B / llama.cpp server で 679 エントリの実データ検証を完了済み
（[引き継ぎメモ](handoff/001-initial.md) 参照）。

---

## 貢献

プルリクエストを歓迎する。

### 進め方

1. Issue で方針を相談（大きな変更は特に）
2. フォーク → ブランチ作成 → 実装
3. `uv run pytest` / `uv run ruff check` / `uv run mypy iroiro` が全てクリーンであることを確認
4. テストを **weakning / skip しない**（正当な理由がある場合のみ `@pytest.mark.skipif`）
5. PR 作成（1 PR = 1 論理的変更）

### コーディング規約

- **日本語** でコメント・docstring・説明文を書く
- **英語** で技術識別子（関数名・CLI フラグ・API名・XMLタグ・ファイルパス）を書く
- ruff ルール: `E` / `F` / `W` / `I` / `B` / `UP`（`pyproject.toml` 参照）
- mypy は strict ではないが `iroiro/` は型チェック必須
- アプリ側での XML エスケープは絶対にしない（lxml 任せ・二重エスケープ防止）

---

## コミット運営

Conventional Commits 風のプレフィックスを使用:

| プレフィックス | 用途 |
|---|---|
| `feat:` | 新機能 |
| `fix:` | バグ修正 |
| `chore:` | ビルド・依存・設定等の雑務 |
| `docs:` | ドキュメント変更 |
| `refactor:` | リファクタリング（機能変更なし） |
| `test:` | テスト追加・修正 |
| `perf:` | パフォーマンス改善 |

例: `feat: 用語集機能を追加`, `fix: 空要素展開の regex が属性付きタグを取りこぼす問題を修正`

---

## ロードマップ

v0.1 は英→日バッチ翻訳の安定版。以降は以下を予定（PR 歓迎）:

### v0.2（✅ 完了）

- **翻訳スキップ REC 型** — `DEFAULT_SKIP_RECORDS`（12件）+ `--no-skip-default-records` / `--skip-records` CLI フラグ。詳細は [docs/plans/002-skip-records.md](plans/002-skip-records.md) と [docs/handoff/002-skip-records.md](handoff/002-skip-records.md)。

### v0.3 以降（予定）

- 用語集機能（JSON/YAML形式・人間メンテ可能）
- 長文 BOOK の自動分割
- 実 LLM での品質レビュー用 diff 出力
- SSTXMLRessources v3 / Interface/*.txt 対応
