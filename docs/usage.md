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
| `--config` | PATH | なし | `iroiro.toml` 設定ファイルのパス（未指定時は cwd の `iroiro.toml` を探す）（v0.3） |
| `--api-base` | TEXT | `http://localhost:8081/v1` | OpenAI 互換 API のベース URL（llama.cpp server） |
| `--api-key` | TEXT | `iroiro` | API キー（llama.cpp では検証されない。`Authorization: Bearer` ヘッダとしては送信する） |
| `--model` | TEXT | `ggml-org/gemma-4-12B-it-GGUF:Q4_K_M` | モデル名 |
| `--concurrency` | INTEGER | `1` | 同時リクエスト数 |
| `--max-chars` | INTEGER | `4000` | 1エントリの最大文字数。超過時はスキップ（v0.1 では分割しない） |
| `--timeout` | FLOAT | `120.0` | 1リクエストの読み出しタイムアウト（秒） |
| `--resume` | FLAG | `False` | `progress.json` があれば再開 |
| `--retry-failed` / `--no-retry-failed` | FLAG | `False` | resume 時に `failed` エントリを再翻訳対象に戻す（未指定時は `iroiro.toml` → 内蔵デフォルト）（v0.4） |
| `--dry-run` | FLAG | `False` | LLM を呼ばず処理件数のみ表示 |
| `--no-skip-default-records` | FLAG | `False` | デフォルトの12件スキップを無効化（全 REC 型を翻訳対象にする）（v0.2） |
| `--skip-records` | TEXT | `""` | 追加スキップ REC 型（カンマ区切り・例: `"LCTN:FULL,ACTI:FULL"`）（v0.2） |
| `-v`, `--verbose` | FLAG | `False` | 詳細ログ（DEBUG レベル） |
| `--help` | — | — | ヘルプを表示して終了 |

> **既定値の根拠**: ローカル LLM（llama.cpp server / Gemma 4 12B）を前提に調整している。
> `--api-key` は llama.cpp の OpenAI 互換サーバーでは検証されないが、HTTP ヘッダとしては送信されるため
> 任意の非空文字列を指定する（既定の `iroiro` はダミー）。

> **解決順序（v0.3 / v0.4）**: `--api-base` / `--api-key` / `--model` / `--concurrency` /
> `--max-chars` / `--timeout` の6フラグ（v0.3）と `--retry-failed` / `--no-retry-failed`（v0.4）は、
> **CLI フラグ（明示指定時）＞ `iroiro.toml` ＞ 内蔵デフォルト**
> （上表の値）の順で解決されます。各フラグを省略したとき `iroiro.toml` の値が使われます。
> 詳細は下記の「設定ファイル（v0.3）」節を参照。

---

## 設定ファイル（v0.3）

CLI フラグを毎回打つ代わりに、`iroiro.toml` に LLM エンドポイント・API キー・モデル名・
タイムアウト・並列数・`max_chars` のデフォルト値を書いておけます。LLM サーバーを頻繁に切り替える
利用者（llama.cpp / LM Studio / Ollama 等）の負担を減らすための機能です。

> v0.3 は後方互換です。`iroiro.toml` を置かなければ v0.2.1 以前と同じ挙動（CLI フラグ ＞ 内蔵
> デフォルト）のまま動きます。

### 書き方

TOML 形式・単一の `[iroiro]` テーブルに `snake_case`（小文字＋アンダースコア）でキーを書きます。
**全項目省略可能** で、書かなかった項目は内蔵デフォルトに落ちます。

```toml
[iroiro]
api_base    = "http://localhost:8081/v1"
api_key     = "iroiro"
model       = "ggml-org/gemma-4-12B-it-GGUF:Q4_K_M"
timeout     = 120.0
concurrency = 1
max_chars   = 4000
retry_failed = false   # v0.4 追加・省略時は false 扱い（後方互換）
```

### 優先順位

```
強 ← CLI フラグ（明示指定時）  ＞  iroiro.toml  ＞  内蔵デフォルト  → 弱
```

- CLI フラグを明示した値が **最優先** です。
- フラグ省略時は `iroiro.toml` の値が使われます。
- 両方とも無い項目は内蔵デフォルト（CLI フラグ一覧表の値）に落ちます。

> **falsy な明示値の扱い**: `--max-chars 0` や `--api-key ""` のような「偽になりがちな明示値」も、
> 正しく CLI 指定として優先されます（内部で `is None` 判定を使うため）。`iroiro.toml` の値で
> 上書きされる心配はありません。

### 検索位置

- **`--config PATH` で明示指定時**: そのファイル **のみ** 読みます。存在しない場合は即時エラー
  （exit code 2）。
- **`--config` 無指定時**: コマンドを実行したディレクトリ（cwd）の `iroiro.toml` を探します。
  存在すれば読み、存在しなければ何もしません（後方互換・警告も出ません）。
- **親ディレクトリへの遡りはしません**（git の `.git` 探索のような動作は v0.3 では未対応）。

> ※ `iroiro.toml` を「入力 XML と同じディレクトリ」に置く誤解が多いですが、探索されるのは
> **コマンドを実行したディレクトリ（cwd）** です。

### 導入手順

雛形 `iroiro.toml.example` を `iroiro.toml` にコピーし、値を編集します。

```bash
cp iroiro.toml.example iroiro.toml
# エディタで iroiro.toml を開き、コメントを外して値を編集する
```

`iroiro.toml` は `.gitignore` 対象（個人の環境依存情報のため commit しない）。
`iroiro.toml.example` の方は git 管理対象（ダミー値のみ・実キーは書かない）。

### 各項目の意味

| キー | 型 | 値域 | 意味 |
|---|---|---|---|
| `api_base` | 文字列 | 非空 | OpenAI 互換 API のベース URL（例: `http://localhost:8081/v1`） |
| `api_key` | 文字列 | `""` 許可 | API キー。llama.cpp は検証しないので空でも動く（OpenAI 互換サーバーでは認証失敗する場合あり） |
| `model` | 文字列 | 非空 | OpenAI クライアントに渡すモデル名 |
| `timeout` | 数値 | `> 0` | 1リクエストの読み出しタイムアウト（秒）。整数（`120`）も可・内部的に浮動小数点に正規化 |
| `concurrency` | 整数 | `>= 1` | 同時リクエスト数 |
| `max_chars` | 整数 | `>= 0` | 1エントリの最大文字数。超過時はスキップ。**`0` は正当値（= 全件スキップ）** なので注意 |
| `retry_failed` | 真偽値 | `true` / `false` | resume 時に `failed` エントリを再翻訳対象に戻すか。デフォルト `false`（後方互換・v0.4 追加）。詳細は下記「[failed の再試行（v0.4）](#failed-の再試行v04)」節を参照 |

> **`max_chars = 0` に注意**: `0` は「全エントリをスキップ」の意味になります（`len(source) > 0` が
> 常に真のため）。意図せず全件スキップにならないよう、基本的には `1` 以上を指定してください。

> **`bool` は拒否**: `timeout = true` のような書き間違いはエラーになります（Python で `bool` が
> `int` の部分型である事故を防ぐため）。数値項目には必ず数値を指定してください。

### 未知のキーの扱い

`[iroiro]` に未知のキー（将来バージョン用等）があっても **警告ログを出して続行** します
（前方互換のため）。既知のキーは通常どおり反映されます。

### セキュリティ注意事項

- **API キーは `iroiro.toml` に書く方が安全**: CLI フラグ `--api-key XXX` は shell history・
  `ps` 出力・`HISTFILE` に残ります。本番環境では `iroiro.toml`（`.gitignore` 対象）を使ってください。
- **`chmod 600 iroiro.toml` を推奨**: 共有サーバーで他ユーザーに読まれないようにするため。
- **`iroiro.toml.example` に実キーを書かない**: 雛形はダミー値のまま commit してください
  （`.gitignore` 対象でなく commit されるファイルのため）。
- **共有環境では `--api-key` を使わない**: シェル履歴から漏洩するリスクがあります。

### エラーメッセージ例

設定ファイルの問題は全て `Error:` 付きで表示され、exit code 2 で停止します。

| 状況 | メッセージ例 |
|---|---|
| `--config PATH` が存在しない | `Error: config file not found: PATH` |
| TOML のシンタックスエラー | `Error: invalid TOML in iroiro.toml: <詳細>` |
| `[iroiro]` がテーブルでない | `Error: [iroiro] must be a table, got <型> in <パス>` |
| 型不一致（`timeout = "abc"` 等） | `Error: <キー> must be <期待型>, got <実際型> in <パス>` |
| 値域エラー（`timeout = -1` 等） | `Error: <キー> must be > 0, got <値> in <パス>` |

> cwd に `iroiro.toml` が存在しない場合は **エラーにならず** 何も出力しません（後方互換）。

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
- 既存 `failed` の index は再試行せず保持（`state=failed`、元の `<Dest>` を保持）※ デフォルト動作・後述の `--retry-failed` で変更可能
- `input_hash`（SHA256）が不一致 → 停止（入力 XML を変更した場合）
- `skip_records_fingerprint` が不一致 → 停止（`--no-skip-default-records` / `--skip-records` を変更した場合）（v0.2）
- JSON decode error → 停止（ユーザーにファイル削除を促す）

### failed の再試行（v0.4）

デフォルトでは `--resume` 時に `failed` エントリはそのまま保持され、再翻訳されません（v0.3 までと同じ挙動・後方互換）。
LLM の一時的エラー（ネットワーク・`--ctx-size` 不足・モデルの揺らぎ等）で `failed` になったエントリを
再翻訳対象に戻すには `--retry-failed` を使います。

#### 使い方

```bash
# 1回限りの再試行
iroiro translate INPUT.xml --resume --retry-failed

# 常に再試行（iroiro.toml に retry_failed = true と書く）
iroiro translate INPUT.xml --resume

# 今回だけ再試行しない（toml が true でも）
iroiro translate INPUT.xml --resume --no-retry-failed
```

#### 優先順位

CLI フラグ（`--retry-failed` / `--no-retry-failed`）＞ `iroiro.toml` ＞ 内蔵デフォルト `False`

`iroiro.toml` に `retry_failed = true` と書いておけば、毎回 `--retry-failed` を打つ必要がありません。
CLI フラグは `iroiro.toml` より常に優先されるので、`--no-retry-failed` で一時的に無効化することも可能です。

#### `--retry-failed` 単独（`--resume` 無し）の挙動

`retry_failed` が有効な状態（CLI の `--retry-failed` または `iroiro.toml` の `retry_failed = true`）
で `--resume` を付けずに実行すると、警告ログが出て **通常実行** になります（exit 2 にはなりません）。
`--resume` 無しでは `progress.json` が読み込まれないため、`failed` を `pending` に戻す対象もありません。
ユーザーが `--resume` 忘れに気づけるよう WARNING レベルで出力します。

```bash
# CLI フラグで指定した場合も toml で retry_failed = true の場合も、同じ WARNING が出ます
$ iroiro translate INPUT.xml --retry-failed
WARNING  --retry-failed が指定されましたが --resume が無いため、failed エントリの再試行は行われません（通常実行になります）
```

#### 不変性（entries ∩ failed = ∅）

retry で成功した index は `progress.json` の `failed` リストから削除され、`entries` に移動します。
**同じ index が両方に存在することはありません**。これにより「Resuming: X translated, Y failed」
メッセージと `progress.json` の内容が常に整合します。

失敗した index は `failed` に append されますが、重複チェックがあるため **同じ index が複数回
append されることはありません**（retry ループで「再試行 → 再失敗」を繰り返しても 1回だけ）。

#### 使用シナリオ

- **LLM サーバーの一時的エラー・ネットワークエラー** で `failed` になった場合 → 環境を変えずに再試行で通る可能性あり
- **llama.cpp の `--ctx-size` 等の LLM 側設定を変えた後** の再実行 → コンテキスト長不足で空応答だったエントリが通る可能性あり
- **※ 決定論的エラー**（token mismatch 等）の場合も再試行されますが、**同じ結果になる可能性が高い** 点に注意。
  無駄な LLM 呼出を避けるため、`failed` の原因が決定論的であれば再試行しないのが無難です

#### 出力 XML の `<Dest>` 扱い

retry で `pending` に戻ったエントリは **翻訳が終わるまで元の `<Dest>`（`original_dest`）を保持** します
（失敗時の `<Dest>` 保護ポリシーと同じ・詳細は [設計判断](design.md) 参照）。翻訳が成功すれば新しい訳文が
`<Dest>` に入り、再失敗時は元の `<Dest>` が保持されます。`<Source>` で `<Dest>` を上書きすることはありません。

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

### エントリが `failed` になる（空応答・メタ返答）

v0.2.1 以降、LLM が post-processing 後も **空文字列** を返した場合、または
**「指示を受けた応答」**（`了解しました`／`翻訳します`／`以下の通りです` 等）を返した場合は
そのエントリを `state=failed` として元の `<Dest>` を保持する（安全側）。

警告ログに `empty response after post-processing` または
`meta response (conversational filler) detected` と出るので確認すること。

> ※ `分かりました`／`はい`／`すみません` 等の NPC セリフとして自然な言葉は
> `failed` にはならない（誤検出防止のため除外している）。

> ⚠️ **過検出の可能性**: ブラックリストは **行頭一致（`startswith`）** で判定するため、
> 「翻訳しますか？」等の NPC セリフが弾かれる可能性があります。実運用で問題になった場合は
> `--reject-phrases` CLI フラグ（v0.3 以降）で調整可能、または issue でご報告ください。

多数のエントリがこの理由で `failed` になる場合は、モデルの品質不足かプロンプト設定の問題。
`--concurrency 1` で安定化するか、より指示追従性の高いモデルへの切り替えを検討する。

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
