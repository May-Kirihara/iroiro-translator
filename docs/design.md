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
| `iroiro/config.py` | `RunConfig` dataclass |
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
| `failed` | LLM リトライ最終失敗 / トークン不一致 | 元の `<Dest>` |

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
- **JSON decode error**: 自動修復せず停止。ユーザーにファイル削除を促す。

---

## 制限事項

- **用語集**: v0.2 以降で対応予定（PR 歓迎）
- **対訳方向**: 英→日のみ。他の方向は未対応
- **対応形式**: `SSTXMLRessources` v2 のみ。v3 / `Interface/*.txt` 等の他形式は将来対応
- **長文の自動分割**: 未対応。`--max-chars` 超過時はスキップ
- **CDATA / XML コメント**: 入力に含まれる場合はエラー停止（v0.1 では非サポート）
- **alias 名の文字種**: `[A-Za-z0-9_\-]` のみ。ドット `.` / コロン `:` は非サポート
