# 設計判断

iroiro-translator の設計概要と主要な判断についての解説。実装の経緯・却下代替案は
[実装計画](plans/001-initial.md) を参照。

---

## アーキテクチャ概要

### データフロー

```
input.xml (bytes)
    │
    ▼ detect BOM/CRLF/encoding → FileFormat として記憶
    ▼ parse (lxml, XXE/entity hardening 付き)
list[StringEntry]  ──► ProgressWriter (asyncio.Lock + 原子書き込み)
    │
    ▼ filter: is_translation_needed? → translate / skip
    ▼ Translator (openai SDK, async + Semaphore)
list[StringEntry (translated/skipped/failed)]
    │
    ▼ serialize: same tree, swap only <Dest>.text → bytes
    ▼ re-apply BOM + CRLF normalization + 空要素展開
output.xml (bytes)
```

### モジュール構成

| モジュール | 役割 |
|---|---|
| `iroiro/cli.py` | `typer` ベースの CLI エントリ。`translate` サブコマンド |
| `iroiro/config.py` | `RunConfig` dataclass・`load_config`（`iroiro.toml` ローダー・v0.3） |
| `iroiro/models.py` | `StringEntry`, `FileFormat` dataclass |
| `iroiro/xml_io.py` | `parse_xml` / `serialize_xml`（BOM/CRLF/宣言保持） |
| `iroiro/escape.py` | `extract_tokens` / `tokens_match`（プレースホルダ保護） |
| `iroiro/translator.py` | `Translator` / `ApiConfig` / `is_translation_needed`（OpenAI 互換クライアント） |
| `iroiro/progress.py` | `ProgressWriter` / `ProgressData` / `compute_input_hash`（並行安全な再開機能） |
| `iroiro/logging.py` | `rich` ベースの進捗表示ヘルパ |
| `iroiro/errors.py` | `IroiroError` 共通例外 |

詳細は [実装計画 §5.3](plans/001-initial.md) を参照。

---

## XML 安全性の設計

iroiro は xTranslator との **相互運用性** を最優先する。出力 XML が xTranslator でそのまま
再読み込みできるよう、以下を保証する。

### 「構造的等価 + フォーマット保存」ポリシー

**バイト完全一致**は要求しない（lxml シリアライザの細部に振り回されないため）。代わりに以下を保証:

- **構造的等価**: `parse → serialize → parse` で同一の木構造・同じ `.text`・同じ属性が得られる。
- **バイトレベルで保持** する項目:
  - XML 宣言 `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>`（ダブルクォートに正規化）
  - BOM の有無
  - 改行コード（CRLF / LF / CR）
  - インデント空白（`remove_blank_text=False`）
  - 空要素の `<X></X>` 形式
  - `List="0"` 等の属性

上記以外の細かい差分（実体参照表現・属性クォート等）は許容。xTranslator が読めればよい。

### BOM / CRLF / `standalone="yes"` 宣言の保持

入力 XML の先頭3バイトが `EF BB BF` なら BOM 付き、最初の改行バイト列で CRLF/LF/CR を判定、
XML 宣言の `encoding=` 属性を読む。これらを `FileFormat` dataclass に記憶し、
serialize 時に再付与する。

### 二重エスケープ防止（lxml 任せ）

**アプリ側で XML エスケープ/アンエスケープは絶対にしない**。lxml が parse 時に XML エスケープを
解除し、serialize 時に再エスケープする。これにより `&amp;lt;` のような二重エスケープを防ぐ。
LLM には生文字列（lxml が parse した時点でアンエスケープ済）を渡し、LLM から受け取った生文字列を
そのまま `.text` にセットする。

### 空要素 `<X></X>` 形式の保持

xTranslator 形式では空要素を `<Dest></Dest>` のように開始/終了タグで表現する。
2段階戦略でこれを保証:

1. **木構造アプローチ（第一戦略）**: `elem.text = ""` をセット。lxml 6.x は `<X></X>` 形式で出力する。
2. **regex フォールバック（第二戦略）**: `<TAG/>` を `<TAG></TAG>` に展開。

### XXE / entity hardening

XML パーサに以下を設定し、XXE / billion laughs / 外部ネットワークアクセスを防止:

- `load_dtd=False` — DTD 読み込み拒否
- `no_network=True` — 外部ネットワークアクセス拒否
- `resolve_entities=False` — entity 展開無効化

> ※ lxml 6.x では `no_load_dtd` は不正キーワード、`load_dtd=False` が正しい。

---

## プレースホルダ保護

Skyrim MOD の `<Source>` には翻訳時に **そのまま維持すべきトークン** が含まれる。
iroiro は原文と LLM 訳文の **各トークンの出現回数が一致するか** を検証する。

### 保護対象トークン

```
<alias=NAME>, <Alias=NAME>, <alias=quest-giver>   # alias 名は [A-Za-z0-9_\-]（ハイフン許容）
<br>, <br/>, <br />                                 # 改行プレースホルダ
%{name}                                             # Skyrim 変数
\n, \r                                              # リテラル2文字の改行
#                                                   # Skyrim 色コード等
```

> ドット `.` とコロン `:` を含む alias 名は v0.1 では非サポート。サンプル実査で出現しないため。

### 検証ポリシー

- **順序は問わない**（日本語では語順が変わるため）
- **各トークンの出現回数（multiset）が一致** することを検証
- **不一致時**: 警告ログ → `state = "failed"` → `new_dest = original_dest`（元の `<Dest>` を保持）

---

## 失敗時の `<Dest>` 保護ポリシー

iroiro は翻訳対象の MOD XML を破壊しない設計。翻訳失敗・スキップ時は **元の `<Dest>` をそのまま保持** し、
`<Source>` の内容で `<Dest>` を上書きすることはない。これにより、過去に人間が手直しした `<Dest>` や、
すでに適切な日本語訳が入っている `<Dest>` を間違って英語で上書きする事故を防ぐ。

処理状態と `<Dest>` の対応:

| `state` | 条件 | 出力 XML の `<Dest>` |
|---|---|---|
| `translated` | LLM 翻訳成功・トークン整合性 OK | 新しい訳文 |
| `skipped` | 空 / 空白 / 日本語混入 / 長文超過 | 元の `<Dest>` |
| `failed` | LLM リトライ最終失敗 / トークン不一致 / 空文字列応答（v0.2.1） / メタ返答（v0.2.1） | 元の `<Dest>` |

---

## post-processing 後の品質検査（v0.2.1）

LLM が post-processing（strip・フェンス削除・最初の行のみ採用・ラベル削除・リストマーカー削除）
を経た後でも、訳文として不適切な場合は `state = "failed"` として元の `<Dest>` を保持する。
トークン不一致と同じ経路（`IroiroError` → `state=failed` → `new_dest=original_dest`）。

### 空文字列チェック（ルール6）

post-processing 後が空文字列（または空白のみ）の場合、LLM が空応答を返したとみなし失敗にする。
安全側の挙動。

### メタ返答チェック（ルール7）

LLM が「指示を受けた応答」（了解しました／翻訳します／以下の通りです 等）を返した場合を検出する。
`REJECT_PHRASES`（厳選ブラックリスト）に対し `text.strip()` が **完全一致** または
**行頭一致**（`startswith`）するかで判定する。

- **除外しない言葉**: `分かりました`、`はい`、`いいえ`、`すみません`、`ありがとうございます` 等
  （NPC セリフとして自然なため）。誤検出を防ぐため意図的にブラックリストを絞っている。
- 将来拡張: ユーザーが新たに発見したパターンは `--reject-phrases` CLI フラグで追加可能（v0.3 以降）。

---

## 長文スキップ

`<Source>` の文字数が `--max-chars`（既定 `4000`）を超える場合、そのエントリはスキップされる
（警告ログを出力）。v0.1 では **自動分割しない**。分割は将来機能。

---

## CDATA / XML コメント非サポート

入力 XML に CDATA セクション（`<![CDATA[...]]>`）または XML コメント（`<!-- ... -->`）が
含まれる場合、iroiro はエラーを送出して停止する（v0.1 では非サポート）。

理由は内部の正規表則ポスト処理（空要素展開のフォールバック）がこれらを破壊する可能性があるための
安全措置。xTranslator 形式の正規ファイルでは出現しない（ユーザー提供の MOD XML 実査で確認済み）。

検出方法:

- **CDATA**: 生バイト列に `b"<![CDATA["` を含むか（`root.iter()` では見えないため）
- **コメント**: `root.iter()` に `_Comment` ノードを含むか（lxml 6.0.2 実機検証済み）

---

## ProgressWriter の並行安全性

巨大 MOD で `--concurrency` を上げた際に `progress.json` が破損しないよう、以下で保護する:

- **`asyncio.Lock`**: `mark_done` / `mark_failed` を直列化し、共有 dict の競合を防止。
- **原子的書き込み**: `tmp` ファイルに書き出し後 `os.replace` で本ファイルを置換。
  クラッシュ時に本ファイルが破損しない（残存 `tmp` は次回実行時に上書きされる）。
- **`input_hash` 検証**: 入力 XML を変更した後に `--resume` すると SHA256 が合わずに停止する。
  安全側の挙動。メッセージに従い進捗ファイルを削除して再実行する。
- **`skip_records_fingerprint` 検証**（v0.2）: `--no-skip-default-records` / `--skip-records` を
  変更した後に `--resume` すると fingerprint が合わずに停止する。`input_hash` と同じパターン。
- **JSON decode error**: 自動修復せず停止。ユーザーにファイル削除を促す。

---

## 翻訳スキップ REC 型（v0.2）

Skyrim MOD の XML で `<REC>` が **内部管理用** レコード型の `<String>` を翻訳すると、
MOD が誤動作する（内部IDとして使われている名前が変わってしまう等）。これを防ぐため、
デフォルトで12件の REC 型を翻訳スキップする。

### デフォルトスキップリスト

```
HDPT:FULL  FURN:FULL  CLAS:FULL  DOOR:FULL  FACT:FULL  CLFM:FULL
TREE:FULL  MGEF:FULL  RACE:FULL  EXPL:FULL  HAZD:FULL  BPTD:BPTN
```

これらは `iroiro/translator.py` の `DEFAULT_SKIP_RECORDS`（`frozenset[str]`）として組み込みで持つ。
根拠はユーザーによる実機検証で「これらの REC 型は内部管理用に使われるため翻訳非推奨」と判明したため
（詳細は `docs/notes/translate-skip-records.md` 参照）。

### `MGEF:FULL` / `RACE:FULL` の取り扱い注意

魔法効果名（`MGEF:FULL`）と種族名（`RACE:FULL`）は、翻訳を **希望する** ユーザーも多い。
デフォルトではスキップするが、以下の方法で個別制御可能:

- **`--no-skip-default-records` 単独**: 全 REC 型を翻訳対象にする（v0.1 互換動作）
- **`--no-skip-default-records --skip-records "HDPT:FULL,..."`**: デフォルト12件のうち
  翻訳したくない REC 型のみを再指定（`MGEF:FULL` / `RACE:FULL` 以外の10件を再指定すれば、
  これら2件のみ翻訳される）

### `is_translation_needed` の拡張設計

v0.1 は `is_translation_needed(source) -> bool` で source 文字列のみ判定していた（空/空白/日本語混入）。
v0.2 は signature を拡張し:

```python
def is_translation_needed(
    source: str,
    rec: str = "",
    skip_records: frozenset[str] | None = None,
) -> bool
```

判定順序:

1. `rec` が `skip_records` に含まれる → `False`（REC 型スキップ）
2. 空/空白 → `False`
3. 日本語混入 → `False`
4. それ以外 → `True`

`skip_records=None` の場合は `DEFAULT_SKIP_RECORDS` を使用。`rec=""` の場合は REC 型スキップが
適用されず、v0.1 の `is_translation_needed(source)` と同じ挙動（後方互換性）。

**重要**: `Translator.translate_entry` は **`is_translation_needed` を呼ばない**（v0.2 設計判断）。
REC 型スキップ・言語スキップ・長文スキップは **CLI 側でのみ** 判定し、結果を `StringEntry.state` /
`skip_reason` に記録する。これにより `Translator` 単体テスト（`MGEF:FULL` 等の rec を直接渡す
テスト）が REC スキップ設定に影響されずに動作する。

### dry-run 集計の排他性

REC skip と言語 skip が **重複カウントされない** よう、dry-run 集計は以下の順序で行う:

1. まず `pending` から `rec in skip_records` で REC skip を抽出
2. 残り（`non_rec_pending`）で言語判定（`is_translation_needed`）・長文判定を行う

これにより「REC skip + 言語 skip = 総エントリ数」が常に成り立つ。

### `progress.json` の `skip_records_fingerprint` 検証

スキップリストは入力 XML と独立に変更可能なので、`progress.json` に fingerprint を保存し、
`--resume` 時に検証する（`input_hash` と同じパターン）:

- fingerprint は `compute_skip_records_fingerprint(skip_records)` で計算
- **空集合は `""` を返す特例**（v0.1 形式 `progress.json` との互換性のため）
- 非空は `SHA256("\n".join(sorted(skip_records)))` の hex
- 不一致時は `ValueError` で停止し、ユーザーに `progress.json` の削除を促す

v0.1 で作成された `progress.json`（fingerprint フィールド無し = `""`）は:
- `--no-skip-default-records` 指定時（空 set = `""`）→ resume 成功
- デフォルト動作（`DEFAULT_SKIP_RECORDS` = 非`""`）→ fingerprint 不一致で停止（安全側）

---

## 設定ファイル読込の設計（v0.3）

v0.3 で `iroiro.toml` によるデフォルト値の外部化を追加した。設計判断と却下代替案の経緯は
[実装計画 003 §4 / §14](plans/003-config-file.md) を参照。

### なぜ `pyproject.toml [tool.iroiro]` でなく `iroiro.toml` 専用か

LLM のエンドポイント・API キーは **環境依存の個人情報・ローカルネット情報** なので、プロジェクト共有
ファイル（`pyproject.toml`）に混入させたくない。`.env` と同じ運用（雛形は管理・実体は `.gitignore`）
とするため、専用ファイル `iroiro.toml` を採用した。

### なぜ親ディレクトリ遡りをしないか

git の `.git` 探索のような「親ディレクトリを遡って `iroiro.toml` を探す」動作は導入しない。
**「知らぬ間に親ディレクトリの `iroiro.toml` が読まれる」** 混乱を避けるため（KISS）。探索は cwd
直下のみ。将来必要になれば追加する。

### なぜ `bool` を拒否するか

Python では `bool` は `int` の部分型（`isinstance(True, int) == True`）。`timeout = true` のような
書き間違いを数値として受け入れてしまう事故を防ぐため、数値フィールドでは **`isinstance(v, bool)`
なら型エラーとして拒否** する。

### なぜ `max_chars = 0` を正当値にしたか

`0` は「全件スキップ」の意味で実用上必要（一時的に翻訳を止めたい等）。`len(source) > 0` が常に真の
ため、`max_chars = 0` は全エントリをスキップ判定にする。`>= 0` を正当値とし、`-1` 等の負数のみ拒否。

### なぜ `is None` 判定か（`or` 演算子でない）

優先順位マージで `or` 演算子を使うと、`0` や `""` を falsy 扱いして **埋もれてしまう**:

- `--max-chars 0`（明示的に 0 = 全件スキップを指定）が `iroiro.toml` の値で上書きされる
- `--api-key ""`（明示的に空文字を指定）が `iroiro.toml` の値で上書きされる

これらを正しく扱うため、**`is None` チェック** で「明示的に渡されたか」を判定する（`cli.py` の
`_resolve()` helper）。Typer の `Optional[type] = None` パターンと組み合わせることで、フラグ省略時は
`None`・明示時は値（`0` や `""` 含む）が渡る。

### 単一 `[iroiro]` テーブルの理由

6項目は1テーブルで十分であり、サブテーブル分割（`[iroiro.api]` / `[iroiro.translation]` 等）は
過剰。将来項目が増えて構成し直しが必要になれば再編する（v0.3 では必要なし）。

### 未知キーは警告して続行

`[iroiro]` に未知のキーがあっても **例外送出せず警告ログのみ** で続行する（既知キーは反映）。
前方互換（将来バージョンのキーが混ざっても停止しない）のため。

---

## retry_failed 設計判断（v0.4）

v0.4 で `--resume` 時の `failed` エントリ再試行機能を追加した。設計判断と却下代替案の経緯は
[実装計画 004 §4 / §14](plans/004-retry-failed.md) を参照。

### なぜデフォルト `False` か

後方互換と「決定論的エラー」と「一時的エラー」の区別のため:

- **決定論的エラー**（token mismatch・空応答・メタ返答等）: 同じ入力・同じモデルなら再試行しても同じ結果
- **一時的エラー**（ネットワーク・LLM の揮らぎ・`--ctx-size` 不足等）: 環境を変えれば通る可能性

`retry_failed = true` を明示しない限り再試行しないことで、決定論的エラーを無駄に再試行するコストを
回避する（v0.1 からの「`failed` は確定扱い」方針をデフォルトで維持）。ユーザーが一時的エラーと判断した
時だけ opt-in する設計（計画書 §2 / §11.1）。

### なぜ全 failed を一括か

選択的リトライ（`--retry-failed 1,5,10` 等）はスコープ外とした。全 `failed` 一括で十分実用的で、
特定 index だけ再試行したい場合は `progress.json` を手動編集すれば代替可能。
将来必要になれば `--retry-failed-only INDEX` 等で拡張できる（計画書 §5.2 / §14）。

### なぜ `mark_done()` で failed をクリアするか

**不変性「`entries ∩ failed = ∅`」を保証するため**。retry で成功した index が `failed` に残っていると、
`progress.json` の内容と起動時の「Resuming: X translated, Y failed」メッセージが整合しなくなる。
成功時（`mark_done`）に同 index が `failed` にあれば削除することで、常に一貫した状態を保つ
（計画書 §4.6）。これは v0.1 では潜在バグだったが、retry 機能の導入で顕在化するため明示的に保証する。

### なぜ `mark_failed()` に重複チェックを入れたか

retry ループ（再試行 → 再失敗 → 再試行…）で **同じ index が複数回 append されるのを防ぐため**。
重複チェックを入れないと、`progress.json` の `failed` リストが同じ index で膨張し、JSON 尺度・
可読性・「Resuming」メッセージの集計正確性に悪影響が出る（計画書 §4.6 / §11.3）。

> `if index not in failed` の線形探索は O(N) だが、`failed` リストは通常数十件程度なので実用上問題なし。
> 数千件になったら `set` への持ち替えを検討する（将来課題・計画書 §11.5）。

### なぜ `RunConfig`（`ApiConfig` でなく）に置いたか

`retry_failed` は LLM 呼出パラメータ（`base_url` / `api_key` / `model` / `timeout` 等）でなく、
**実行制御フラグ**（`resume` / `dry_run` / `verbose` / `skip_records` と同種）だから。
`ApiConfig` は `Translator` に渡される LLM 接続設定で、`retry_failed` は CLI の実行フロー制御に属する。
両者を混ぜないことで `Translator` のテスト容易性も保たれる（`Translator` は `retry_failed` を知らない）。

### なぜ `bool | None = None` パターンか

Typer の `--flag/--no-flag` 構文で **3状態**（`True` / `False` / 未指定）を区別するため。
`bool = False`（2状態）では「`--no-retry-failed` を明示した」と「何も指定しなかった」を区別できず、
`iroiro.toml` の `retry_failed = true` を上書きできなくなってしまう（T126/T127 の肝）。
`None` を「未指定」とし、v0.3 の `_resolve()` helper で `is None` 判定する（`or` 演算子は falsy 事故を
起こすので使わない・詳細は「設定ファイル読込の設計（v0.3）」を参照）。

### なぜ `_validate_bool` は厳格 bool か

`retry_failed = 1` のような書き間違いを暗黙に受け入れると、`if retry_failed:` で truthy 扱いされて
**意図せず** 全 `failed` エントリが再試行対象になる事故に繋がるため。Python では `bool ⊂ int`
（`isinstance(True, int) == True`）だが `isinstance(1, bool) == False` なので、`1` / `0` は
`IroiroError` で拒否される。他の数値フィールド（`timeout` / `concurrency` / `max_chars`）が `bool` を
拒否するのと対称的な「厳格 bool」思想（計画書 §4.4 / T113）。

### なぜ `--retry-failed` 単独（`--resume` 無し）を exit 2 にしないか

`--resume` 無しでは `progress.json` が読み込まれないため、`failed` を `pending` に戻す対象もありません。
無意味な指定ですが、**exit 2 にする程のエラーではない** と判断しました。WARNING ログを出して通常実行を
継続することで、ユーザーが `--resume` 忘れに気づけるようにしています（計画書 §11.4 / T129）。

---

## 制限事項

- **用語集**: 未対応（PR 歓迎）
- **対訳方向**: 英→日のみ。他の方向は未対応
- **対応形式**: `SSTXMLRessources` v2 のみ。v3 / `Interface/*.txt` 等の他形式は将来対応
- **長文の自動分割**: 未対応。`--max-chars` 超過時はスキップ
- **CDATA / XML コメント**: 入力に含まれる場合はエラー停止（v0.1 では非サポート）
- **alias 名の文字種**: `[A-Za-z0-9_\-]` のみ。ドット `.` / コロン `:` は非サポート
- **スキップリストのファイル読み込み**: `--skip-records-file PATH` 等は未対応。
  需要が出たら追加（v0.2 は `--skip-records TEXT` のカンマ区切りのみ）
