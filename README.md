# iroiro-translator

Skyrim MOD の [xTranslator](https://www.nexusmods.com/skyrimspecialedition/mods/30918) 形式 XML
（`SSTXMLRessources` v2）の `<Source>` 英文を、OpenAI 互換 LLM で `<Dest>` に日本語翻訳する
**バッチ CLI** ツール。ローカル LLM（llama.cpp server / Gemma 系 12B 想定）を前提とする。

> 本ツールは出力 XML の **主要なバイトレベルフォーマット**（BOM / CRLF / `standalone="yes"` 宣言 /
> 空要素の `<X></X>` 形式 / インデント）を保持し、xTranslator がそのまま再読み込みできる相互運用性を保証する。
> ※ 属性の順序や実体参照の細部など、XML シリアライザ依存の差分は許容される（xTranslator 互換性に影響しない範囲）。

---

## 目次

- [プロジェクト概要](#プロジェクト概要)
- [主な機能](#主な機能)
- [必要環境](#必要環境)
- [インストール](#インストール)
- [使い方](#使い方)
- [設定例](#設定例)
- [安全性の説明](#安全性の説明)
- [トラブルシュート](#トラブルシュート)
- [制限事項](#制限事項)
- [ライセンス](#ライセンス)
- [貢献](#貢献)

---

## プロジェクト概要

`iroiro` は Skyrim MOD 翻訳で広く使われる xTranslator 形式の XML を、ローカル LLM で
英→日バッチ翻訳するコマンドラインツール。

入力 XML の `<Content>/<String>` ごとに `<Source>` の英文を LLM で日本語訳し、`<Dest>` に
書き戻した同形式の XML を出力する。すでに日本語が入っている `<Source>` や空文字は自動的に
スキップされ、巨大な MOD（数百〜数千エントリ）でも途中で止まったら `--resume` で続きから
再実行できる。

設計の詳細は [`docs/plans/001-initial.md`](docs/plans/001-initial.md) を参照。

---

## 主な機能

- **OpenAI 互換 API による英→日翻訳**（ローカル LLM 想定。llama.cpp server を推奨）
- **BOM / CRLF / `standalone="yes"` 宣言の完全保持** — xTranslator 互換
- **プレースホルダ保護** — `<alias=NAME>`, `<Alias=NAME>`, `<br>`, `%{...}`, `\n`, `\r`, `#` 等
  のトークンを検出し、訳文に過不足なく保持されていることを検証（不一致時は当該エントリを失敗扱い）
- **再開機能**（`--resume`） — 進捗ファイルから続きを実行
- **dry-run モード**（`--dry-run`） — LLM を呼ばず処理件数のみ表示
- **失敗時の `<Dest>` 保護** — 翻訳失敗・スキップ時は元の `<Dest>` を保持し、`<Source>` で上書きしない
- **並列実行**（`--concurrency`） — 同時リクエスト数を指定可能（デフォルトは安全側の `1`）
- **HTTP タイムアウト設定**（`--timeout`） — ローカル LLM の遅延に対応

---

## 必要環境

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** — Python パッケージ・環境管理
- **OpenAI 互換 LLM サーバー** — 以下のいずれか:
  - [llama.cpp server](https://github.com/ggerganov/llama.cpp)（推奨・既定のエンドポイント）
  - [LM Studio](https://lmstudio.ai/)
  - [Ollama](https://ollama.com/)（OpenAI 互換エンドポイントを有効化）
  - [vLLM](https://github.com/vllm-project/vllm)

---

## インストール

### 1. リポジトリをクローン

```bash
git clone <repository-url> iroiro-translator
cd iroiro-translator
```

### 2. 依存関係を同期

```bash
uv sync
```

`uv sync` は `uv.lock` に基づいて仮想環境を構築し、`iroiro` パッケージと依存ライブラリ
（`openai`, `httpx`, `lxml`, `typer`, `rich`）をインストールする。

### 3. （任意）グローバルインストール

`uv tool install` でプロジェクトの仮想環境に依存せず `iroiro` コマンドを使えるようにする:

```bash
uv tool install .
```

インストール後は任意のディレクトリから `iroiro translate INPUT.xml` を実行できる。

---

## 使い方

### 基本形

```bash
uv run iroiro translate INPUT.xml
```

または `uv tool install .` 済みなら:

```bash
iroiro translate INPUT.xml
```

### CLI フラグ一覧

`iroiro` は `translate` サブコマンドを持つ（multi-command モード）。

```
iroiro translate INPUT.xml [OPTIONS]
```

| フラグ | 型 | デフォルト | 説明 |
|---|---|---|---|
| `INPUT`（引数） | PATH（必須） | — | 入力 XML ファイルのパス |
| `-o`, `--output` | PATH | `<input>.translated.xml` | 出力 XML ファイルのパス |
| `--api-base` | TEXT | `http://localhost:8081/v1` | OpenAI 互換 API のベース URL（llama.cpp server） |
| `--api-key` | TEXT | `iroiro` | API キー（llama.cpp では検証されない。`Authorization: Bearer` ヘッダとしては送信する） |
| `--model` | TEXT | `ggml-org/gemma-4-12B-it-GGUF:Q4_K_M` | モデル名 |
| `--concurrency` | INTEGER | `1` | 同時リクエスト数 |
| `--max-chars` | INTEGER | `4000` | 1エントリの最大文字数。超過時はスキップ（v0.1 では分割しない） |
| `--timeout` | FLOAT | `120.0` | 1リクエストの読み出しタイムアウト（秒） |
| `--resume` | FLAG | `False` | `progress.json` があれば再開 |
| `--dry-run` | FLAG | `False` | LLM を呼ばず処理件数のみ表示 |
| `-v`, `--verbose` | FLAG | `False` | 詳細ログ（DEBUG レベル） |
| `--help` | — | — | ヘルプを表示して終了 |

> **既定値の根拠**: ローカル LLM（llama.cpp server / Gemma 4 12B）を前提に調整している。
> `--api-key` は llama.cpp の OpenAI 互換サーバーでは検証されないが、HTTP ヘッダとしては送信されるため
> 任意の非空文字列を指定する（既定の `iroiro` はダミー）。

### dry-run で処理件数を事前確認

```bash
uv run iroiro translate sample/JobsofSkyrim_english_japanese.xml --dry-run
```

出力例:

```
INFO  Parsing input: sample/JobsofSkyrim_english_japanese.xml
INFO  Parsed 679 <String> entries (BOM=True, newline='\r\n', encoding=UTF-8)
総エントリ数: 679
翻訳対象: 32
スキップ（空/日本語混入）: 647
スキップ（長文超過）: 0
--dry-run: LLM を呼ばず終了します
```

### 翻訳の実行

```bash
uv run iroiro translate sample/JobsofSkyrim_english_japanese.xml
```

### 再開

途中で止まった場合、`--resume` で進捗ファイルから続きを実行できる:

```bash
uv run iroiro translate sample/JobsofSkyrim_english_japanese.xml --resume
```

---

## 設定例

### llama.cpp server の起動

別ターミナルでローカル LLM サーバーを起動する。既定の `--api-base`（`http://localhost:8081/v1`）に
合わせるため `--port 8081` を指定:

```bash
./llama-server -m path/to/model.gguf --port 8081
```

- モデルは Gemma 系 12B（`gemma-4-12B-it-GGUF:Q4_K_M` 等）を推奨。
- GPU がない場合はスレッド数（`-t`）やコンテキスト長（`-c`）をハードウェアに合わせて調整。
- llama.cpp server が受ける `model` パラメータは起動オプション（`--alias` / `--host`）に依存して変わる。
  既定値で繋がらない場合は `--model` で実際のエイリアス名を指定すること。

### iroiro の実行

サーバー起動後、別ターミナルで:

```bash
uv run iroiro translate sample/JobsofSkyrim_english_japanese.xml
```

- 出力ファイル: `sample/JobsofSkyrim_english_japanese.translated.xml`
- 進捗ファイル: `sample/JobsofSkyrim_english_japanese.xml.iroiro-progress.json`

### 出力ファイル名の規則

| 種類 | 規則 | 例 |
|---|---|---|
| 出力 XML（既定） | `<input>.translated.xml` | `JobsofSkyrim_english_japanese.xml` → `JobsofSkyrim_english_japanese.translated.xml` |
| 出力 XML（明示） | `-o PATH` で指定 | `iroiro translate in.xml -o out.xml` |
| 進捗ファイル | `<input>.iroiro-progress.json` | `JobsofSkyrim_english_japanese.xml.iroiro-progress.json` |

> 進捗ファイルの `<input>` は入力 XML の **フルファイル名**（拡張子含む）である点に注意。

### 他の OpenAI 互換サーバーを使う場合

```bash
# LM Studio (既定ポート 1234)
uv run iroiro translate INPUT.xml --api-base http://localhost:1234/v1 --model lm-studio-model

# Ollama (OpenAI 互換エンドポイント)
uv run iroiro translate INPUT.xml --api-base http://localhost:11434/v1 --model gemma
```

---

## 安全性の説明

`iroiro` は翻訳対象の MOD XML を破壊しない設計になっている。

### 失敗時の `<Dest>` 保護ポリシー

翻訳に失敗したエントリ、またはスキップされたエントリは、**元の `<Dest>` をそのまま保持**する。
`<Source>` の内容で `<Dest>` を上書きすることはない。

これにより、過去に人間が手直しした `<Dest>` や、すでに適切な日本語訳が入っている `<Dest>` を
間違って英語で上書きする事故を防ぐ。

処理状態と `<Dest>` の対応:

| `state` | 条件 | 出力 XML の `<Dest>` |
|---|---|---|
| `translated` | LLM 翻訳成功・トークン整合性 OK | 新しい訳文 |
| `skipped` | 空 / 空白 / 日本語混入 / 長文超過 | 元の `<Dest>` |
| `failed` | LLM リトライ最終失敗 / トークン不一致 | 元の `<Dest>` |

### 長文スキップ

`<Source>` の文字数が `--max-chars`（既定 `4000`）を超える場合、そのエントリはスキップされる
（警告ログを出力）。v0.1 では **自動分割しない**。分割は将来機能。

### CDATA / XML コメント

入力 XML に CDATA セクション（`<![CDATA[...]]>`）または XML コメント（`<!-- ... -->`）が
含まれる場合、`iroiro` はエラーを送出して停止する（v0.1 では非サポート）。

これは内部の正規表現ポスト処理がこれらを破壊する可能性があるための安全措置。
xTranslator 形式の正規ファイルでは出現しない（サンプル実査で確認済み）。

---

## トラブルシュート

### `model` パラメータが不一致エラーになる

llama.cpp server が受ける `model` パラメータは、起動時の `--alias` / `--host` 設定に依存して変わる。
エラーメッセージに示されたモデル名を `--model` で指定する:

```bash
uv run iroiro translate INPUT.xml --model <actual-alias>
```

### タイムアウトする

ローカル LLM は推論に時間がかかる。`--timeout`（既定 `120` 秒）を増やす:

```bash
uv run iroiro translate INPUT.xml --timeout 300
```

### LLM が説明文やマークダウンを返す

`iroiro` は post-processing で一般的なノイズ（`訳文:` ラベル、` ``` ` フェンス、リストマーカー、
複数行の2行目以降）を自動的にクリーニングする。それでも品質が悪い場合は `--concurrency 1`
（既定）で安定化を試す:

```bash
uv run iroiro translate INPUT.xml --concurrency 1
```

### 出力 XML が BOM / CRLF を保持していない

`iroiro` は入力 XML の BOM / 改行コード / `standalone="yes"` 宣言を自動的に保持する。
出力が期待と異なる場合は、入力ファイルのフォーマットを確認すること:

```bash
file sample/JobsofSkyrim_english_japanese.xml
# 期待: ... XML 1.0 document, UTF-8 Unicode (with BOM) text, with CRLF line terminators
```

### `progress.json` の hash 不一致エラー

入力 XML を変更した後に `--resume` すると、`input_hash`（SHA256）が合わずに停止する。
これは安全側の挙動。メッセージに従い進捗ファイルを削除して再実行する:

```bash
rm sample/JobsofSkyrim_english_japanese.xml.iroiro-progress.json
```

---

## 制限事項

- **用語集**: v0.2 以降で対応予定（PR 歓迎）
- **対訳方向**: 英→日のみ。他の方向は未対応
- **対応形式**: `SSTXMLRessources` v2 のみ。v3 / `Interface/*.txt` 等の他形式は将来対応
- **長文の自動分割**: 未対応。`--max-chars` 超過時はスキップ
- **CDATA / XML コメント**: 入力に含まれる場合はエラー停止（v0.1 では非サポート）

---

## ライセンス

Apache License 2.0。詳細は [`LICENSE`](LICENSE) ファイルを参照。

---

## 貢献

プルリクエストを歓迎する。

### 開発の進め方

```bash
uv sync                         # 依存関係（dev 含む）を同期
uv run pytest                   # テスト全実行
uv run pytest -k "xml_io"       # 個別実行
uv run ruff check               # リント
uv run mypy iroiro              # 型検査
```

### テスト

テストは `uv run pytest` で実行する。フィクスチャ（`tests/fixtures/`）と
モック LLM（`httpx.MockTransport`）により、ネットワーク接続無しで実行できる。
