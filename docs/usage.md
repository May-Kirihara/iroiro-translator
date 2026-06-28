# 詳細な使い方

iroiro の CLI フラグ全一覧・設定例・トラブルシュート。設計の背景は [設計判断](design.md) を参照。

---

## CLI フラグ一覧

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
| `--no-skip-default-records` | FLAG | `False` | デフォルトの12件スキップを無効化（全 REC 型を翻訳対象にする）（v0.2） |
| `--skip-records` | TEXT | `""` | 追加スキップ REC 型（カンマ区切り・例: `"LCTN:FULL,ACTI:FULL"`）（v0.2） |
| `-v`, `--verbose` | FLAG | `False` | 詳細ログ（DEBUG レベル） |
| `--help` | — | — | ヘルプを表示して終了 |

> **既定値の根拠**: ローカル LLM（llama.cpp server / Gemma 4 12B）を前提に調整している。
> `--api-key` は llama.cpp の OpenAI 互換サーバーでは検証されないが、HTTP ヘッダとしては送信されるため
> 任意の非空文字列を指定する（既定の `iroiro` はダミー）。

---

## グローバルインストール（任意）

`uv tool install` でプロジェクトの仮想環境に依存せず `iroiro` コマンドを使えるようにする:

```bash
uv tool install .
```

インストール後は任意のディレクトリから `iroiro translate INPUT.xml` を実行できる。
プロジェクト開発時は `uv run iroiro ...` を使うのが基本。

---

## dry-run で処理件数を事前確認

LLM サーバーを起動せずに、入力 XML をパースして処理件数の集計だけを行う。実際の翻訳対象件数を
事前に把握できる:

```bash
# sample XML は第三者著作物のため git 管理外。お手持ちの MOD XML で実行してください
uv run iroiro translate path/to/your_mod.xml --dry-run
```

出力例:

```
INFO  Parsing input: path/to/your_mod.xml
INFO  Parsed 679 <String> entries (BOM=True, newline='\r\n', encoding=UTF-8)
総エントリ数: 679
翻訳対象: 31
スキップ（REC 型）: 6
スキップ（空/日本語混入）: 642
スキップ（長文超過）: 0
--dry-run: LLM を呼ばず終了します
```

---

## 翻訳の実行

別ターミナルでローカル LLM サーバーを起動後（設定例は後述）:

```bash
uv run iroiro translate path/to/your_mod.xml
```

完了時のサマリ:

```
完了: translated=31, failed=0, skipped=648 / total=679
出力: path/to/your_mod.translated.xml
進捗: path/to/your_mod.xml.iroiro-progress.json
```

---

## 再開

途中で止まった場合、`--resume` で進捗ファイルから続きを実行できる:

```bash
uv run iroiro translate path/to/your_mod.xml --resume
```

`--resume` 時の挙動:

- 既存 `entries` の index はスキップ（`state=translated`、訳文を再利用）
- 既存 `failed` の index は再試行せず保持（`state=failed`、元の `<Dest>` を保持）
- `input_hash`（SHA256）が不一致 → 停止（入力 XML を変更した場合）
- `skip_records_fingerprint` が不一致 → 停止（`--no-skip-default-records` / `--skip-records` を変更した場合）（v0.2）
- JSON decode error → 停止（ユーザーにファイル削除を促す）

---

## 翻訳スキップ REC 型（v0.2）

Skyrim MOD の XML（`SSTXMLRessources` v2）で、`<REC>` が **内部管理用** レコード型の `<String>` は
翻訳すると MOD が誤動作する可能性があるため、デフォルトで **12件の REC 型** をスキップ対象にする。

### デフォルトスキップリスト（12件）

| REC | 用途 |
|---|---|
| `HDPT:FULL` | Head Part name（頭部パーツ名） |
| `FURN:FULL` | Furniture name（家具名） |
| `CLAS:FULL` | Class name（クラス名） |
| `DOOR:FULL` | Door name（ドア名） |
| `FACT:FULL` | Faction name（派閥名） |
| `CLFM:FULL` | Color Form name（色フォーム名） |
| `TREE:FULL` | Tree name（木名） |
| `MGEF:FULL` | Magic Effect name（魔法効果名） |
| `RACE:FULL` | Race name（種族名） |
| `EXPL:FULL` | Explosion name（爆発名） |
| `HAZD:FULL` | Hazard name（危険物名） |
| `BPTD:BPTN` | Body Part Data name（ボディパーツ名） |

スキップされたエントリの `<Dest>` は元の値を保持し、`<Source>` で上書きされない（他のスキップ・失敗ケースと同じ挙動）。

### 制御方法

デフォルト動作（フラグ無し）は上記12件をスキップする。以下の3パターンで制御可能:

#### 1. デフォルト + 追加スキップ

`--skip-records` でデフォルト12件に追加してスキップ（OR）:

```bash
# デフォルト12件 + LCTN:FULL と ACTI:FULL を追加スキップ
uv run iroiro translate INPUT.xml --skip-records "LCTN:FULL,ACTI:FULL"
```

#### 2. デフォルト無効化 + 全 REC 型を翻訳

`--no-skip-default-records` 単独で、全 REC 型を翻訳対象にする（v0.1 互換動作）:

```bash
uv run iroiro translate INPUT.xml --no-skip-default-records
```

#### 3. デフォルト無効化 + 特定 REC 型のみスキップ

`--no-skip-default-records` + `--skip-records` の組合せで、デフォルトを無効化した上で
特定 REC 型のみスキップ:

```bash
# MGEF:FULL（魔法効果名）だけをスキップし、他は全て翻訳
uv run iroiro translate INPUT.xml --no-skip-default-records --skip-records "MGEF:FULL"
```

#### `MGEF:FULL` と `RACE:FULL` だけを翻訳したい場合

これらはデフォルトスキップリストに入っているが、翻訳を **希望する** ユーザーも多い。
デフォルト12件のうち両者以外を再指定することで実現できる:

```bash
uv run iroiro translate INPUT.xml \
  --no-skip-default-records \
  --skip-records "HDPT:FULL,FURN:FULL,CLAS:FULL,DOOR:FULL,FACT:FULL,CLFM:FULL,TREE:FULL,EXPL:FULL,HAZD:FULL,BPTD:BPTN"
```

### 仕様の細かい点

- `--skip-records` は **カンマ区切り**。各要素は前後空白を許容し、空要素は無視される。
- 大文字小文字は区別しない（`hdpt:full` は `HDPT:FULL` に正規化される）。
- 重複指定は自動で排除される。
- `skip_records_fingerprint`（SHA256 of sorted canonical）が `progress.json` に保存され、
  `--resume` 時に検証される。`--no-skip-default-records` / `--skip-records` を変更した場合は
  `ValueError` で停止する（`input_hash` と同じパターン）。
- v0.1 で作成された `progress.json`（`skip_records_fingerprint` フィールド無し = `""` 扱い）は、
  `--no-skip-default-records` 指定時のみ resume 可能。デフォルト動作で resume すると
  fingerprint 不一致で停止する（安全側）。エラーメッセージに従い `progress.json` を削除して再実行すること。

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
uv run iroiro translate path/to/your_mod.xml
```

- 出力ファイル: `path/to/your_mod.translated.xml`
- 進捗ファイル: `path/to/your_mod.xml.iroiro-progress.json`

### 出力ファイル名の規則

| 種類 | 規則 | 例 |
|---|---|---|
| 出力 XML（既定） | `<input>.translated.xml` | `your_mod.xml` → `your_mod.translated.xml` |
| 出力 XML（明示） | `-o PATH` で指定 | `iroiro translate in.xml -o out.xml` |
| 進捗ファイル | `<input>.iroiro-progress.json` | `your_mod.xml.iroiro-progress.json` |

> 進捗ファイルの `<input>` は入力 XML の **フルファイル名**（拡張子含む）である点に注意。

### 他の OpenAI 互換サーバーを使う場合

```bash
# LM Studio (既定ポート 1234)
uv run iroiro translate INPUT.xml --api-base http://localhost:1234/v1 --model lm-studio-model

# Ollama (OpenAI 互換エンドポイント)
uv run iroiro translate INPUT.xml --api-base http://localhost:11434/v1 --model gemma
```

対応サーバー: [llama.cpp server](https://github.com/ggerganov/llama.cpp)（推奨） /
[LM Studio](https://lmstudio.ai/) / [Ollama](https://ollama.com/) /
[vLLM](https://github.com/vllm-project/vllm)

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

iroiro は post-processing で一般的なノイズ（`訳文:` ラベル、```` ``` ```` フェンス、リストマーカー、
複数行の2行目以降）を自動的にクリーニングする。それでも品質が悪い場合は `--concurrency 1`
（既定）で安定化を試す:

```bash
uv run iroiro translate INPUT.xml --concurrency 1
```

### 出力 XML が BOM / CRLF を保持していない

iroiro は入力 XML の BOM / 改行コード / `standalone="yes"` 宣言を自動的に保持する。
出力が期待と異なる場合は、入力ファイルのフォーマットを確認すること:

```bash
file path/to/your_mod.xml
# 期待: ... XML 1.0 document, UTF-8 Unicode (with BOM) text, with CRLF line terminators
```

### `progress.json` の hash 不一致エラー

入力 XML を変更した後に `--resume` すると、`input_hash`（SHA256）が合わずに停止する。
これは安全側の挙動。メッセージに従い進捗ファイルを削除して再実行する:

```bash
rm path/to/your_mod.xml.iroiro-progress.json
```

### トークン不一致で大量に `failed` になる

LLM が `<alias=...>` 等のプレースホルダを保持しない場合に発生する。失敗時は `<Dest>` 保護で
安全側（元の `<Dest>` を保持）に働くため、出力 XML が破損することはない。
モデルを変えるか、`--concurrency 1` で安定化を試す。

### 長文 BOOK エントリがスキップされる

`--max-chars`（既定 4000）超過の `<Source>` はスキップされる。v0.1 では自動分割しない。
長い書籍本文を持つ MOD では一部エントリが未翻訳で残る可能性がある。

### 出力・進捗ファイルを削除して完全に元に戻す

iroiro は入力 XML を破壊しない設計。生成物を削除すれば完全に元の状態に戻る:

```bash
rm path/to/your_mod.translated.xml
rm path/to/your_mod.xml.iroiro-progress.json
# 異常終了で .tmp が残った場合も削除
rm -f path/to/your_mod.xml.iroiro-progress.json.tmp
```
