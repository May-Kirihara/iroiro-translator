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
| `--config` | PATH | なし | `iroiro.toml` 設定ファイルのパス（未指定時は cwd の `iroiro.toml` を探す・**v0.5 では `iroiro.toml` が必須**）（v0.3） |
| `--api-base` | TEXT | `http://localhost:8081/v1` | OpenAI 互換 API のベース URL（llama.cpp server） |
| `--api-key` | TEXT | `iroiro` | API キー（llama.cpp では検証されない。`Authorization: Bearer` ヘッダとしては送信する） |
| `--model` | TEXT | `ggml-org/gemma-4-12B-it-GGUF:Q4_K_M` | モデル名 |
| `--concurrency` | INTEGER | `1` | 同時リクエスト数 |
| `--max-chars` | INTEGER | `4000` | 1エントリの最大文字数。超過時はスキップ（v0.1 では分割しない） |
| `--timeout` | FLOAT | `120.0` | 1リクエストの読み出しタイムアウト（秒） |
| `--resume` | FLAG | `False` | `progress.json` があれば再開 |
| `--retry-failed` / `--no-retry-failed` | FLAG | `False` | resume 時に `failed` エントリを再翻訳対象に戻す（未指定時は `iroiro.toml` → 内蔵デフォルト）（v0.4） |
| `--dry-run` | FLAG | `False` | LLM を呼ばず処理件数のみ表示 |
| `--skip-records` | TEXT | `None` | 翻訳スキップ REC 型（カンマ区切り・例: `"HDPT:FULL,FACT:FULL"`）。**3 状態**（v0.6）: 省略=`iroiro.toml` の `skip_records` を使用 / `""`=明示的空 set（全件翻訳）/ 非空文字列=toml を完全置換（v0.2・v0.6 でセマンティクス変更） |
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

> **⚠️ v0.5 の破壊的変更**: `system_prompt` / `reject_phrases` / `[iroiro.rec_hints]` の
> **LLM 挙動中核 3 項目** は v0.5 で新規追加され、上の解決順序には **乗りません**。これらは
> **`iroiro.toml` のみ** で指定し、CLI フラグでの上書きは非対応です（長文を shell history に残す
> リスクを避けるため）。また `iroiro.toml` 自体が `--dry-run` を含む全操作で **必須** になりました。
> 詳細は下記の「[`iroiro.toml` 必須化と移行（v0.5）](#iroirotoml-必須化と移行v05)」節と
> 「[LLM プロンプトのカスタマイズ（v0.5）](#llm-プロンプトのカスタマイズv05)」節を参照。

> **⚠️ v0.6 の破壊的変更**: `skip_records`（翻訳スキップ REC 型リスト）が `iroiro.toml` の
> **必須項目** になりました（`DEFAULT_SKIP_RECORDS` 定数をコードから完全削除し toml 化・
> v0.5 と同じ哲学）。これに伴い CLI フラグも変更: `--no-skip-default-records` は **廃止**、
> `--skip-records` は **完全置換セマンティクス**（toml を上書き）に変更されました。
> 既存の `iroiro.toml` を流用する場合は `skip_records`（14 件）を **手動追記** してください。
> 詳細は下記の「[skip_records の toml 必須化と移行（v0.6）](#skip_records-の-toml-必須化と移行v06)」節と
> 「[翻訳スキップ REC 型（v0.2 / v0.6）](#翻訳スキップ-rec-型v02--v06)」節を参照。

---

## 設定ファイル（v0.3）

CLI フラグを毎回打つ代わりに、`iroiro.toml` に LLM エンドポイント・API キー・モデル名・
タイムアウト・並列数・`max_chars` のデフォルト値を書いておけます。LLM サーバーを頻繁に切り替える
利用者（llama.cpp / LM Studio / Ollama 等）の負担を減らすための機能です。

> v0.3 は後方互換でしたが、**v0.5 で `iroiro.toml` が必須化** されました（LLM 挙動中核の完全
> toml 化のため）。v0.4 以前の `iroiro.toml` 無しで動く挙動は v0.5 で廃止されています。
> 詳細は「[`iroiro.toml` 必須化と移行（v0.5）](#iroirotoml-必須化と移行v05)」節を参照。

### 書き方

TOML 形式・単一の `[iroiro]` テーブルに `snake_case`（小文字＋アンダースコア）でキーを書きます。

v0.5 ではキーは **2 群** に分かれます:

- **接続設定（省略可・6項目）**: `api_base` / `api_key` / `model` / `timeout` / `concurrency` / `max_chars`（＋ `retry_failed`）。書かなかった項目は CLI フラグ指定時はそちら優先、未指定時は内蔵デフォルトに落ちます。
- **LLM 挙動中核（必須・3項目・v0.5 新規）**: `system_prompt` / `reject_phrases` / `[iroiro.rec_hints]`。`iroiro.toml` に必ず書く必要があります（CLI フラグでの上書き非対応・省略時はエラーで停止）。

v0.6 ではさらに **`skip_records`（必須・1項目）** が追加されます:

- **翻訳スキップ REC 型（必須・v0.6 新規）**: `skip_records`。`iroiro.toml` に必ず書く必要があります（CLI `--skip-records` で完全置換可能・省略時は toml の値を使用）。

```toml
[iroiro]
# === 接続設定（省略可・CLI フラグ ＞ iroiro.toml ＞ 内蔵デフォルト）===
api_base    = "http://localhost:8081/v1"
api_key     = "iroiro"
model       = "ggml-org/gemma-4-12B-it-GGUF:Q4_K_M"
timeout     = 120.0
concurrency = 1
max_chars   = 4000
retry_failed = false   # v0.4 追加・省略時は false 扱い

# === 翻訳スキップ REC 型（必須・v0.6 新規・全文は iroiro.toml.example を参照）===
skip_records = [
  "HDPT:FULL", "FURN:FULL", "CLAS:FULL", "DOOR:FULL",
  "FACT:FULL", "CLFM:FULL", "TREE:FULL", "MGEF:FULL",
  "RACE:FULL", "EXPL:FULL", "HAZD:FULL", "BPTD:BPTN",
  "FLST:FULL", "KYWD:FULL",
]

# === LLM 挙動中核（必須・v0.5 新規・全文は iroiro.toml.example を参照）===
system_prompt = """
Skyrim MOD の英文を日本語に翻訳する。
固有名詞・ <alias=...> 等のプレースホルダ・ <br>・改行文字・ # 記号は
**そのまま維持** すること。
簡潔で自然な日本語。**訳文のみ** 出力し、
説明・マークダウン・ラベル・複数行は禁止。
"""

reject_phrases = [
  "了解", "了解しました", "翻訳します", "以下の通りです",
  # ...（21語全文は iroiro.toml.example を参照）
]

# 別テーブルとして記述（[iroiro] の外・ quoted REC key 必須）:
[iroiro.rec_hints]
"MGEF:DESC" = "魔法効果の説明文。自然な日本語の文章。"
"BOOK:DESC" = "書籍の本文。物語風の自然な日本語。"
"INFO:NAM1" = "NPC の会話本文。自然な会話文。"
# ...（v0.6 拡充版の全種は iroiro.toml.example を参照）
```

> **重要（TOML 構文）**: `[iroiro.rec_hints]` 配下のキーは `MGEF:FULL` のように `:` を含むため、
> **必ず quoted key**（`"MGEF:FULL"` のように `"` で囲む）で書いてください。TOML 1.0 の
> bare key は `:` を許容しないため、quoted でないと parse error になります。

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
  v0.4 までは「存在しなければ何もしない（後方互換）」でしたが、**v0.5 では存在しないと
  `Error: iroiro.toml not found in <cwd>.` で停止** します（必須化）。
- **親ディレクトリへの遡りはしません**（git の `.git` 探索のような動作は未対応）。

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

#### 翻訳スキップ REC 型（v0.6 新規・必須）

以下の 1 項目は v0.6 で追加された **必須** 項目です。`iroiro.toml` に必ず指定してください（省略時はエラーで停止・`[iroiro] skip_records is required`）。CLI `--skip-records` で完全置換可能です。カスタマイズ方法は「[翻訳スキップ REC 型（v0.2 / v0.6）](#翻訳スキップ-rec-型v02--v06)」節を参照。

| キー | 型 | 値域 | 意味 |
|---|---|---|---|
| `skip_records` | リスト（文字列） | 各要素が非空 `str`・`bool` 拒否 | 翻訳スキップ対象の REC 型（`REC:FIELD` 形式）のリスト。各要素は `strip().upper()` で大文字正規化・重複は自動で `frozenset` 化して除去。空リスト `[]` は許可（全件翻訳・`compute_skip_records_fingerprint` の空集合特例と整合）。v0.6 で `DEFAULT_SKIP_RECORDS` 定数がコードから完全削除され toml 必須化（案 α・v0.5 と同じ哲学） |

> **`bool` は拒否**: `skip_records = [True]` のような書き間違いはエラーになります（Python で
> `bool` が `int`/汎用型の事故を防ぐため・`reject_phrases` と対称な厳格型検証）。

> **v0.6 のデフォルト 14 件**: `iroiro.toml.example` には NG ガイド §9.1 Conservative
> Preset 準拠（EDID 抜き）の 14 件が記載済み。`cp` でそのまま使えます。

#### LLM 挙動中核（v0.5 新規・必須）

以下の 3 項目は v0.5 で追加された **必須** 項目です。`iroiro.toml` に必ず指定してください（CLI フラグでの上書き非対応）。カスタマイズ方法は「[LLM プロンプトのカスタマイズ（v0.5）](#llm-プロンプトのカスタマイズv05)」節を参照。

| キー | 型 | 値域 | 意味 |
|---|---|---|---|
| `system_prompt` | 文字列 | 非空（strip 後も非空） | LLM へのシステムメッセージ全文（翻訳方針）。TOML の multiline string（`"""..."""`）で記述。`""` / `"   "` は拒否 |
| `reject_phrases` | リスト（文字列） | 各要素が非空 `str`・`bool` 拒否 | LLM メタ返答（指示受け取り・作業宣言）のブラックリスト。`startswith` で判定。空リスト `[]` は許可（メタ返答チェック無効化）・重複は自動で `frozenset` 化して除去 |
| `[iroiro.rec_hints]` | テーブル | 各キー非空・各値が非空 `str`・`bool` 拒否 | `<REC>` 別ヒント辞書。**テーブル自体は必須**（行が無いとエラー）・中身が空 `{}` は許可（REC ヒント無効化）。REC キーは `:` を含むため **必ず quoted key**（`"MGEF:FULL"`） |

> **`bool` は拒否**: `reject_phrases = [True]` や `"MGEF:FULL" = true` のような書き間違いは
> エラーになります（Python で `bool` が `int`/汎用型の事故を防ぐため・全要素で厳格型検証）。
> 既存の数値フィールドが `bool` を拒否するのと対称な「厳格型検証」思想です。

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
| cwd に `iroiro.toml` が無い（v0.5） | `Error: iroiro.toml not found in <cwd>.  -> Run: cp iroiro.toml.example iroiro.toml  -> Or specify: --config /path/to/iroiro.toml`（実際のコードは `->` の前にスペース 2 個） |
| TOML のシンタックスエラー | `Error: invalid TOML in iroiro.toml: <詳細>` |
| `[iroiro]` セクション自体が無い（v0.5） | `Error: [iroiro] section is required in <パス>` |
| `[iroiro]` がテーブルでない | `Error: [iroiro] must be a table, got <型> in <パス>` |
| `system_prompt` 欠損（v0.5） | `Error: [iroiro] system_prompt is required in <パス>` |
| `reject_phrases` 欠損（v0.5） | `Error: [iroiro] reject_phrases is required in <パス>` |
| `[iroiro.rec_hints]` 欠損（v0.5） | `Error: [iroiro.rec_hints] table is required in <パス>` |
| `skip_records` 欠損（v0.6） | `Error: [iroiro] skip_records is required in <パス>` |
| 型不一致（`timeout = "abc"` 等） | `Error: <キー> must be <期待型>, got <実際型> in <パス>` |
| 値域エラー（`timeout = -1` 等） | `Error: <キー> must be > 0, got <値> in <パス>` |
| `[iroiro.rec_hints]` の値が bool（v0.5） | `Error: rec_hints[<key>] must be non-empty str in <パス>`（`bool` / `int` 等の非 `str` 値） |

> v0.4 までは cwd に `iroiro.toml` が存在しなくてもエラーになませんでしたが、**v0.5 では
> 必須化されたため `Error: iroiro.toml not found` で停止** します（上記メッセージ参照）。

---

## `iroiro.toml` 必須化と移行（v0.5）

v0.5 で LLM 挙動中核（`system_prompt` / `reject_phrases` / `[iroiro.rec_hints]`）をコードから
完全削除し `iroiro.toml` に移行した（案 α）。これに伴い **`iroiro.toml` 自体が全操作（`--dry-run` 含む）
で必須** になりました。v0.4 までの「`iroiro.toml` 無しで内蔵デフォルトで動く」挙動は廃止されています。

### 影響範囲（破壊的変更）

v0.4 まで以下の操作が動いていた場面が、v0.5 では **エラーで停止** します:

```bash
uv run iroiro translate INPUT.xml --dry-run                       # iroiro.toml 無し → エラー
uv run iroiro translate INPUT.xml --api-base http://... --api-key x  # iroiro.toml 無し → エラー
uv run iroiro translate INPUT.xml --config custom.toml             # custom.toml に 3 新項目が無い → エラー
```

エラーメッセージは親切に「何をすればいいか」を表示します:

```
Error: iroiro.toml not found in <cwd>.
  -> Run: cp iroiro.toml.example iroiro.toml
  -> Or specify: --config /path/to/iroiro.toml
```

### 移行手順 — 新規ユーザー

```bash
# 1回だけ（雛形をコピー・v0.5 デフォルト値が全て入っている）
cp iroiro.toml.example iroiro.toml
# 必要なら編集（api_key / model / system_prompt 等）

# 以降は今まで通り
uv run iroiro translate INPUT.xml --dry-run
uv run iroiro translate INPUT.xml --resume
```

`iroiro.toml.example` には v0.5 の全デフォルト（`system_prompt` 全文・`reject_phrases` 21語・
`rec_hints` 18種）が入っているため、`cp` 直後は v0.4 までの挙動と同じ結果が得られます。

### 移行手順 — 既存ユーザー（v0.4 以下からのアップグレード）

**重要**: 既存の `iroiro.toml` を流用する場合は **3 新項目を手動で追記** してください。
`cp iroiro.toml.example iroiro.toml` で上書きすると、既存の API 設定（エンドポイント・API キー等）が
消えてしまいます。

既存の `iroiro.toml` の `[iroiro]` セクション内に以下を追記します（全文は `iroiro.toml.example` の
該当節をコピペしてください）:

```toml
# [iroiro] セクション内に追記:
system_prompt  = """..."""                    # 必須・multiline string（全文は example を参照）
reject_phrases = ["了解", "翻訳します"]        # 必須・list[str]（21語全文は example を参照）

# [iroiro] の外（別テーブル）に追記・ quoted REC key 必須:
[iroiro.rec_hints]
"MGEF:FULL" = "魔法の効果名。1〜4語程度の簡潔な表現。"
"BOOK:DESC" = "書籍の本文。物語風の自然な日本語。"
# ...（18種全文は example を参照）
```

追加し忘れると以下のエラーで停止します:

```
Error: [iroiro] system_prompt is required in iroiro.toml
```

### TOML 構文の注意

- **`system_prompt`** は TOML の multiline string（`"""..."""`）で書きます。`"""` で始まり `"""`
  で閉じるまでが1つの文字列になります。
- **`[iroiro.rec_hints]`** 配下のキーは `MGEF:FULL` のように `:` を含むため、**必ず quoted key**
  （`"MGEF:FULL"` のように `"` で囲む）で書いてください。TOML 1.0 の bare key は `[A-Za-z0-9_-]`
  のみ許容するため、`:` を含むと parse error になります。
- **`reject_phrases`** は `list[str]`。空リスト `[]` も許可（メタ返答チェック無効化）。重複は自動で
  除去されます。

---

## skip_records の toml 必須化と移行（v0.6）

v0.6 で `DEFAULT_SKIP_RECORDS` 定数を `iroiro/translator.py` から **完全削除** し、
`iroiro.toml` の `[iroiro] skip_records`（必須）に移行した（案 α 徹底版・v0.5 の LLM 挙動中核
toml 化と同じ哲学）。これに伴い skip リストを 12 件 → **14 件**（`FLST:FULL` / `KYWD:FULL` 追加）
に拡充し、`[iroiro.rec_hints]` も 3 ゲーム（Skyrim / Fallout4 / Starfield）共通の翻訳候補レコードを
網羅するよう拡充した。

### 影響範囲（破壊的変更）

v0.5 まで以下の操作が動いていた場面が、v0.6 では **エラーで停止** します:

```bash
# 1. iroiro.toml に skip_records が無い → エラー（v0.5 までの toml をそのまま使うと発生）
uv run iroiro translate INPUT.xml --dry-run
# Error: [iroiro] skip_records is required in iroiro.toml

# 2. v0.5 までの progress.json を --resume すると WARNING が出る（resume は継続・v0.6.1 で緩和）
uv run iroiro translate INPUT.xml --resume
# WARNING: skip_records fingerprint mismatch: ... Resuming with the current skip_records.
# （v0.6 までは停止していましたが v0.6.1 で WARNING のみに緩和されました）

# 3. --no-skip-default-records フラグが未知オプションに（廃止）
uv run iroiro translate INPUT.xml --no-skip-default-records
# No such option: --no-skip-default-records
```

### 移行手順 — 新規ユーザー

```bash
# 1回だけ（雛形をコピー・v0.6 の skip_records 14件 + 拡充 rec_hints が全て入っている）
cp iroiro.toml.example iroiro.toml
# 必要なら編集（api_key / model / skip_records / rec_hints 等）

# 以降は今まで通り
uv run iroiro translate INPUT.xml --dry-run
uv run iroiro translate INPUT.xml --resume
```

`iroiro.toml.example` には v0.6 の全デフォルト（`skip_records` 14 件・拡充済み `rec_hints`・
v0.5 の `system_prompt` / `reject_phrases`）が入っているため、`cp` 直後は動きます。

### 移行手順 — 既存ユーザー（v0.5 以下からのアップグレード）

**重要**: 既存の `iroiro.toml` を流用する場合は **`skip_records`（14 件）を手動で追記**
してください。`cp iroiro.toml.example iroiro.toml` で上書きすると、既存の API 設定
（エンドポイント・API キー等）やカスタマイズした `system_prompt` / `rec_hints` が消えてしまいます。

既存の `iroiro.toml` の `[iroiro]` セクション内に以下を追記します:

```toml
# [iroiro] セクション内に追記（v0.6 必須）:
skip_records = [
  "HDPT:FULL", "FURN:FULL", "CLAS:FULL", "DOOR:FULL",
  "FACT:FULL", "CLFM:FULL", "TREE:FULL", "MGEF:FULL",
  "RACE:FULL", "EXPL:FULL", "HAZD:FULL", "BPTD:BPTN",
  "FLST:FULL", "KYWD:FULL",
]
```

追加し忘れると以下のエラーで停止します:

```
Error: [iroiro] skip_records is required in iroiro.toml
```

### `--no-skip-default-records` 廃止と代替手段

v0.6 で `DEFAULT_SKIP_RECORDS` 定数がコードから消えたため、「default を無効化」の意味を
成さない `--no-skip-default-records` フラグは **廃止** されました（未知オプションとして弾かれる）。
「全件翻訳」したい場合は以下のいずれかを使います:

```bash
# (a) CLI で --skip-records "" を指定（1回限り・toml を完全置換して空 set に）
uv run iroiro translate INPUT.xml --skip-records ""

# (b) iroiro.toml で skip_records = [] を指定（恒久的に全件翻訳）
# [iroiro]
# skip_records = []
```

### `--skip-records` のセマンティクス変更（完全置換）

v0.5 までは「デフォルト12件 + CLI 指定」の **追加** セマンティクスでしたが、v0.6 では
toml の `skip_records` を **完全置換** するセマンティクスに変更しました（v0.5 の CLI は toml を
上書きパターンと整合）。`str | None = None` パターンで **3 状態** を区別します:

| `--skip-records` 指定 | 意味 |
|---|---|
| 省略 | `iroiro.toml` の `skip_records` を使用（デフォルト動作） |
| `--skip-records ""` | 明示的に空 set（全件翻訳） |
| `--skip-records "HDPT:FULL,FACT:FULL"` | toml を完全置換（指定した set のみスキップ） |

> **v0.5 以前との非互換**: v0.5 で `--skip-records "LCTN:FULL"` は「デフォルト12件 + LCTN:FULL」
> （13件スキップ）を意味しましたが、v0.6 では「LCTN:FULL のみ」（1件スキップ）を意味します。
> 移行時はご注意ください。

### `progress.json` の fingerprint 不整合（v0.6.1 で WARNING に緩和）

v0.5 までの `progress.json` は `skip_records_fingerprint` に 12 件の fingerprint を持っています。
v0.6 で 14 件に変わるため、`--resume` 時に fingerprint が不一致になりますが、**v0.6.1 からは
停止せず WARNING ログを出力して resume を継続します**（`input_hash` 不一致とは異なる挙動）。
skip_records が変わっても `progress.json` の entries と実際の処理結果の整合性は崩れないため、
resume 継続性を優先しました（ユーザー実機フィードバック）:

```
WARNING: skip_records fingerprint mismatch: progress.json has '...',
current skip_records is '...'. Resuming with the current skip_records.
To reprocess all entries, remove <progress.json path>.
```

**全件再処理したい場合**（例: 新しい 14 件リストでスキップ対象を見直したい等）のみ、
手動で `progress.json` を削除して再実行してください:

```bash
rm path/to/your_mod.xml.iroiro-progress.json
```

### 3 ゲーム対応（Skyrim / Fallout4 / Starfield）

v0.6 の主目的の一つ。skip リスト 14 件と `[iroiro.rec_hints]` は NG ガイド §3 / §4 / §9.1 に基づき
3 ゲーム共通の「内部管理用 / 翻訳候補」レコードを網羅しています:

- **skip リスト 14 件**: 3 ゲーム共通の内部管理用レコード（`FLST:FULL` / `KYWD:FULL` は v0.6 追加・
  FormID List / Keyword は Fallout4 / Starfield でも内部管理用）
- **`rec_hints` 拡充**: NG ガイド §4「Usually Safe Translation Targets」に基づき、
  `AMMO:FULL`（弾薬）/ `MISC:FULL`（雑貨）/ `WRLD:FULL`（ワールドスペース）/
  `INFO:NAM1`（NPC 会話本文）等の Fallout4 / Starfield で出現するレコードを追加

> **ゲーム選択機能はスコープ外**: `--game skyrim|fallout4|starfield` のようなゲーム選択機能や、
> Conservative / Translation-Friendly / Starfield-Friendly のプリセット切り替え機能は v0.6 では
> **提供しない**（ユーザー承認済み・将来機能）。3 ゲーム共通のデフォルトで運用し、必要に応じて
> `iroiro.toml` の `skip_records` / `rec_hints` を個別編集してください。

### `PERK` / `AVIF` の保守的運用について

`PERK:FULL` / `PERK:DESC` / `AVIF:FULL` は NG ガイド内で扱いが揺れています:
- §4「Usually Safe Translation Targets」では safe target（翻訳候補）→ iroiro のデフォルト `rec_hints` に採用
- §5「Review-Needed List」/ §9.1「Conservative Preset review-needed」では review-needed

iroiro は review-needed 状態を持たないため、本デフォルトでは §4 に従い翻訳候補としています。
**保守的運用**（翻訳によるゲームへの影響を最小化したい場合）では、`skip_records` にこれらを追加して
スキップすることを検討してください:

```toml
# 保守的運用の例（PERK / AVIF もスキップ）:
skip_records = [
  "HDPT:FULL", "FURN:FULL", "CLAS:FULL", "DOOR:FULL",
  "FACT:FULL", "CLFM:FULL", "TREE:FULL", "MGEF:FULL",
  "RACE:FULL", "EXPL:FULL", "HAZD:FULL", "BPTD:BPTN",
  "FLST:FULL", "KYWD:FULL",
  "PERK:FULL", "AVIF:FULL",  # ← 追加（review-needed 扱い）
]
```

### `INFO:RNAM` が既存 toml に残っていてもエラーではない

v0.5 までの `iroiro.toml.example` には `INFO:RNAM` が含まれていましたが、v0.6 では NG ガイド §4 の
標準である `INFO:NAM1`（NPC 会話本文）に置換しました。**既存ユーザーのカスタム `iroiro.toml` に
`INFO:RNAM` が残っていてもエラーにはなりません**（未知 REC キーは WARNING 無しで許可・v0.5 仕様）。
ただし意味的に重複するため、必要に応じて `INFO:NAM1` に置き換えることを推奨します。

---

## LLM プロンプトのカスタマイズ（v0.5）

v0.5 で LLM 挙動の中核 3 要素が `iroiro.toml` から編集可能になりました。翻訳方針の試行錯誤・
モデル差し替え時のチューニング・未知 Skyrim REC 型への対応がコード編集なしで可能です。

### `system_prompt` — 翻訳方針のカスタマイズ

LLM へ送る system メッセージ全文です。TOML の multiline string で記述します:

```toml
[iroiro]
system_prompt = """
Skyrim MOD の英文を日本語に翻訳する。
固有名詞・ <alias=...> 等のプレースホルダ・ <br>・改行文字・ # 記号は
**そのまま維持** すること。
簡潔で自然な日本語。**訳文のみ** 出力し、
説明・マークダウン・ラベル・複数行は禁止。
"""
```

編集後の反映確認は `--verbose` で system メッセージを観察するか、LLM の応答品質の変化で判断します。

### `reject_phrases` — メタ返答判定のカスタマイズ

LLM が「指示を受けた応答」（`了解しました`／`翻訳します`／`以下の通りです` 等）を返した場合に
`failed` 扱いするためのブラックリストです。`text.strip()` が **完全一致** または **行頭一致**
（`startswith`）するかで判定します。

```toml
[iroiro]
# デフォルト（21語）から削ることも、独自の語句を追加することも自由
reject_phrases = [
  "了解", "了解しました", "了解いたしました",
  "翻訳します", "以下の通りです",
]
```

- **空リスト `[]`** を指定するとメタ返答チェックを無効化できます（誤検出が多い場合等）。
- NPC セリフとして自然な「分かりました」「はい」「すみません」等は **デフォルトには含まれない**
  （誤検出防止のため）。追加する場合は誤検出に注意してください。
- 重複要素は自動で `frozenset` 化して除去されます。

### `[iroiro.rec_hints]` — REC 型別ヒントのカスタマイズ

`<REC>` 型（`MGEF:FULL` / `BOOK:DESC` 等）ごとに、user メッセージに追加するヒント文字列を指定します。
LLM が REC 型の文脈（魔法の効果名・書籍本文・NPC セリフ 等）を理解しやすくなります。

```toml
[iroiro.rec_hints]
"MGEF:DESC" = "魔法効果の説明文。自然な日本語の文章。"
"BOOK:DESC" = "書籍の本文。物語風の自然な日本語。"
"INFO:NAM1" = "NPC の会話本文。自然な会話文。"
```

> **v0.6 で拡充**: `iroiro.toml.example` の `[iroiro.rec_hints]` は NG ガイド §4「Usually Safe
> Translation Targets」に基づき 3 ゲーム（Skyrim / Fallout4 / Starfield）共通の翻訳候補レコードを
> 網羅するよう拡充されました。`MGEF:FULL` / `FACT:FULL` / `RACE:FULL` / `CLAS:FULL` は
> `skip_records` と重複するため rec_hints から除外されています（skip されるため・計画書 §7.2）。
> 全種は `iroiro.toml.example` を参照してください。

- **必ず quoted key**（`"MGEF:FULL"`）で書く（`:` は TOML bare key に使えないため）。
- **空テーブル**（`[iroiro.rec_hints]` ヘッダのみ・中身 `{}`）は許可（REC ヒント無効化）。
- **未知の REC キー**（`"FOO:BAR"` 等・将来の Skyrim REC 型）も WARNING 無しで許可されます。
- ヒントが無い REC 型の場合は source 文のみが user メッセージとして送られます（従来同等）。

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

> **v0.5 の注意**: `--dry-run` も `iroiro.toml` が必須です（設定検証が走るため）。事前に
> `cp iroiro.toml.example iroiro.toml` を実行しておいてください。詳細は
> 「[`iroiro.toml` 必須化と移行（v0.5）](#iroirotoml-必須化と移行v05)」節を参照。

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
- `skip_records_fingerprint` が不一致 → **WARNING ログのみ（resume 継続・exit code 0）**（`skip_records` / `--skip-records` を変更した場合）（v0.2・v0.6 で fingerprint 値が 12件→14件に変更・**v0.6.1 で停止→WARNING に緩和**）
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

## 翻訳スキップ REC 型（v0.2 / v0.6）

Skyrim / Fallout4 / Starfield MOD の XML（`SSTXMLRessources` v2）で、`<REC>` が **内部管理用**
レコード型の `<String>` は翻訳すると MOD が誤動作する可能性があるため、デフォルトで **14件の REC 型**
をスキップ対象にする（v0.2 で導入・v0.6 で 12件 → 14件に拡充 + toml 必須化）。

### デフォルトスキップリスト（14件・v0.6）

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
| `FLST:FULL` | FormID List name（フォーム ID リスト名・v0.6 追加） |
| `KYWD:FULL` | Keyword name（キーワード名・v0.6 追加） |

根拠は NG ガイド §3 Common Skip List / §9.1 Conservative Preset（**EDID を除く**・EDID は全レコード型
フィールド名として現れるため `REC:FIELD` 形式の skip リストには不向き）。

スキップされたエントリの `<Dest>` は元の値を保持し、`<Source>` で上書きされない（他のスキップ・失敗ケースと同じ挙動）。

### 制御方法（v0.6 の完全置換セマンティクス）

v0.6 では `skip_records` は `iroiro.toml` 必須（CLI `--skip-records` で完全置換可能）。
`--skip-records` は **3 状態** を区別します（`str | None = None` パターン・v0.5 の `retry_failed` と同形式）:

#### 1. toml の skip_records を使用（デフォルト動作・`--skip-records` 省略）

```bash
# iroiro.toml の skip_records（デフォルト14件）をそのまま使用
uv run iroiro translate INPUT.xml
```

#### 2. 全件翻訳（`--skip-records ""` で明示的空 set）

`--no-skip-default-records` 廃止後の「全件翻訳」CLI 手段。toml の `skip_records` を空 set で完全置換:

```bash
uv run iroiro translate INPUT.xml --skip-records ""
```

または `iroiro.toml` で恒久的に全件翻訳:

```toml
[iroiro]
skip_records = []   # 空リスト（全件翻訳）
```

#### 3. 特定 REC 型のみスキップ（`--skip-records "..."` で完全置換）

toml の `skip_records` を指定した set で **完全置換**（v0.5 までの「追加」セマンティクスから変更）:

```bash
# MGEF:FULL だけをスキップ（toml の14件は無視され、{MGEF:FULL} に完全置換）
uv run iroiro translate INPUT.xml --skip-records "MGEF:FULL"

# 複数指定（カンマ区切り）
uv run iroiro translate INPUT.xml --skip-records "HDPT:FULL,FACT:FULL"
```

#### `MGEF:FULL` と `RACE:FULL` だけを翻訳したい場合

これらはデフォルトスキップリストに入っているが、翻訳を **希望する** ユーザーも多い。
v0.6 の完全置換セマンティクスでは、これら2件を **除外した** 12 件を `--skip-records` で再指定
します（toml の14件を完全置換）:

```bash
uv run iroiro translate INPUT.xml \
  --skip-records "HDPT:FULL,FURN:FULL,CLAS:FULL,DOOR:FULL,FACT:FULL,CLFM:FULL,TREE:FULL,EXPL:FULL,HAZD:FULL,BPTD:BPTN,FLST:FULL,KYWD:FULL"
```

または `iroiro.toml` の `skip_records` から `MGEF:FULL` / `RACE:FULL` を削除（恒久的）。

### 仕様の細かい点

- `--skip-records` は **カンマ区切り**。各要素は前後空白を許容し、空要素は無視される。
- 大文字小文字は区別しない（`hdpt:full` は `HDPT:FULL` に正規化される）。
- 重複指定は自動で排除される（`frozenset` 化）。
- `skip_records_fingerprint`（SHA256 of sorted canonical）が `progress.json` に保存され、
  `--resume` 時に検証される。`skip_records` を変更した場合は **WARNING ログのみ出力して resume を継続**
  （v0.6.1 で緩和・`input_hash` とは異なり停止しない・skip_records が変わっても entries と処理結果の
  整合性は崩れないため）。v0.6 までは `ValueError` で停止していた。
- **v0.5 までの `progress.json` を v0.6 以降で resume すると fingerprint 不一致の WARNING が出ますが
  resume は継続します**（12件 → 14件の変更のため）。全件再処理したい場合のみ `progress.json` を削除して
  再実行してください。
- 空集合（`--skip-records ""` または `skip_records = []`）の fingerprint は `""` を返す特例
  （v0.1 形式 `progress.json` との互換性のため）。

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
> `iroiro.toml` の `reject_phrases`（v0.5）で調整可能、または issue でご報告ください。
> カスタマイズ方法は「[LLM プロンプトのカスタマイズ（v0.5）](#llm-プロンプトのカスタマイズv05)」節を参照。

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
