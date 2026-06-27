# iroiro-translator 初期実装計画 (001-initial) — v0.6

- 作成日: 2026-06-28
- 更新日: 2026-06-28 (v0.6: Codex レビュー#5 反映)
- 状態: ユーザー合意済み → Codex CLI 再レビュー待ち
- リスク分類: **normal**
- 完了状態: not-started

## 変更履歴

- v0.1: 初版
- v0.2-v0.5: Codex レビュー#1-#4 反映。
- **v0.6**: Codex レビュー#5（reject, residual1+NB4, **new blocking: none**）反映
  - **`FileFormat` に `has_cdata` / `has_comment` を追加**: CDATA は生バイトスキャン、コメントは `_Comment` ノード検出（lxml 6.0.2 実機検証済み）
  - **§5.5.3 の誤記修正**: `root.iter()` は `_Comment` ノードを含む（CDATA は含まない）
  - **§5.5.3 / §5.5.4 / §6.2 を木構造アプローチ＋CDATA/comment 事前検出に統一**
  - **WP-1 Inputs と §8 step 1 を v0.5 参照に更新**
  - **regex タグ名のコロン非サポートを明記**（xTranslator は素朴な識別子のみ）
  - **テスト T52 を `test_xml_io.py` に移動**、T52b（コメント検出）・T52c（CDATA raw bytes 検出）追加

---

## 1. 目標

Skyrim MOD の xTranslator 形式 XML (`SSTXMLRessources` v2) を入力とし、
`<Content>/<String>` ごとに `<Source>` の英文を LLM で日本語訳し、
`<Dest>` に書き戻した XML を出力する **バッチCLI** を作る。

- 入力: `sample/JobsofSkyrim_english_japanese.xml` のような XML
- 出力: 同形式の XML（`<Dest>` のみ差し替え、**BOM/CRLF/宣言も保持**）
- 副産物: 進捗ファイル（再開用）

## 2. 背景・現状（サンプル実査）

- README と sample XML のみ。実装コードなし。
- サンプル実査で判明した事実:
  - **679** `<String>` エントリ、**4568行**
  - エンコーディング: **UTF-8 with BOM**（先頭 `EF BB BF`）
  - 改行コード: **CRLF**
  - XML宣言: `standalone="yes"`
  - **116件** の `<alias=NAME>` / `<Alias=NAME>` プレースホルダ（`&lt;...&gt;` にエスケープされて格納）
  - **大部分は `Source == Dest` の未翻訳** だが、一部 **既に日本語** の Source も混在（例: 「棺」「ネックレス」「魔法の指輪」）
  - `<REC>` の prefix で文脈・長さが異なる（`BOOK:` は長文、`ARMO:FULL` は1単語、`MGEF:FULL` は効果名など）

## 3. ユーザー決定事項（ブレスト合意）

1. 翻訳LLM: **OpenAI 互換 API でローカルLLM（Gemma4 12B / llama.cpp server）**
2. 実行スタイル: **バッチCLI + 再開機能**
3. 用語集: 欲しいが **v0.1 では未実装**（v0.2機能以降）
4. スタック: **Python + uv**

## 4. スコープ

### 4.1 目標（v0.1）

- `SSTXMLRessources` v2 XML の読み込み・書き出し（**BOM/CRLF/宣言 保持**）
- OpenAI 互換 API による英→日翻訳
- **Source言語判定**: 日本語文字（ひらがな/カタカナ/漢字）を含まないSourceを翻訳対象、空/空白/日本語混入はスキップ
- **プレースホルダ保護**: `<alias=...>` / `<Alias=...>` / `<br>` / `%{...}` / `\n` / `\r` / `#`
- `--resume` による再開機能（**並行安全な ProgressWriter**）
- 並列実行（`--concurrency`、デフォルト1）
- 進捗表示・失敗リスト出力
- dry-run モード
- HTTP タイムアウト設定（`--timeout`）

### 4.2 非目標（v0.1）

- 用語集（v0.2機能以降）
- 英→日以外の対訳方向
- Web/TUI フロントエンド
- `SSTXMLRessources` v3 / `Interface/*.txt` 等の他形式
- レートリミット自動調整（`--concurrency` の手動指定のみ）
- **長文の自動分割**（v0.1 では `--max-chars` 超過時にスキップ。分割は将来機能）
- 人間レビュー用の差分ビューア

## 5. 提案アーキテクチャ

### 5.1 データフロー

```
input.xml (bytes)
   │
   ▼ detect BOM/CRLF/encoding → remember
   ▼ parse (lxml, strip barely)
list[StringEntry]  ──► ProgressWriter (asyncio.Lock + atomic write)
   │
   ▼ filter: is_translation_needed? → translate
   ▼ translator (openai SDK, async + Semaphore)
list[StringEntry (translated)]
   │
   ▼ serialize: same tree, swap only <Dest>.text → bytes
   ▼ re-apply BOM + CRLF normalization
output.xml (bytes)
```

### 5.2 主要データ構造

```python
@dataclass(slots=True)
class StringEntry:
    index: int                       # XML内出現順（0始まり）。安定したID
    edid: str                        # <EDID>
    rec: str                         # <REC> (例: "MGEF:FULL")
    source: str                      # <Source> の生文字列（XMLアンエスケープ済、lxmlが parse 時に処理）
    original_dest: str               # <Dest> の元の生文字列
    new_dest: str | None             # 新しい訳文。None=未処理またはスキップ
    state: Literal["pending", "translated", "skipped", "failed"]
```

注意: `original_dest` と `new_dest` を分離することで、失敗時に元の `<Dest>` を保持できる（NB指摘#4対応）。

### 5.3 モジュール構成

```
iroiro-translator/
├── README.md
├── pyproject.toml
├── .python-version
├── iroiro/
│   ├── __init__.py
│   ├── __main__.py             # python -m iroiro
│   ├── cli.py                  # typer entry
│   ├── config.py               # ApiConfig / RunConfig (dataclass)
│   ├── models.py               # StringEntry, FileFormat
│   ├── xml_io.py               # parse/serialize (lxml, BOM/CRLF保存)
│   ├── escape.py               # プレースホルダ検出・検証
│   ├── translator.py           # OpenAI互換クライアント + プロンプト
│   ├── progress.py             # ProgressWriter (asyncio.Lock付き)
│   └── logging.py              # 進捗表示 (rich)
├── tests/
│   ├── conftest.py
│   ├── fixtures/
│   │   ├── tiny.xml            # 数件、alias/br/%{...}/空文字含む
│   │   ├── tiny_crlf_bom.xml   # BOM+CRLFの実物コピー
│   │   ├── japanese_source.xml # 既に日本語Sourceを含む
│   │   ├── long_source.xml     # max-chars超過
│   │   └── sample_subset.xml   # sampleから抽出
│   ├── test_xml_io.py
│   ├── test_escape.py
│   ├── test_progress.py
│   ├── test_translator.py      # モックLLM
│   └── test_cli.py             # end-to-end
├── sample/
└── docs/
    ├── plans/001-initial.md     ← この文書
    └── handoff/
```

### 5.4 CLI インターフェース（v0.1）

```
iroiro translate INPUT.xml
  [-o, --output PATH]        # 省略時: <input>.translated.xml
  [--api-base URL]           # default: http://localhost:8081/v1 (llama.cpp)
  [--api-key KEY]            # default: "iroiro"
  [--model NAME]             # default: ggml-org/gemma-4-12B-it-GGUF:Q4_K_M
  [--concurrency N]          # default: 1
  [--max-chars N]            # default: 4000（超過時スキップ）
  [--timeout SEC]            # default: 120 (1リクエスト読み出し上限)
  [--resume]                 # progress.json があれば再開
  [--dry-run]                # LLM呼ばず処理件数のみ表示
  [-v, --verbose]
```

### 5.5 XML処理（`xml_io.py`）— BOM/CRLF保存戦略

#### 5.5.1 読み込み

```python
@dataclass(slots=True)
class FileFormat:
    has_bom: bool
    newline: Literal["\r\n", "\n", "\r"]
    encoding: str            # 実質 "UTF-8" 固定想定
    has_cdata: bool          # v0.6: 生バイトスキャンで検出
    has_comment: bool        # v0.6: root.iter() で _Comment 検出

def parse_xml(path: Path) -> tuple[list[StringEntry], FileFormat, etree._Element, dict[str, str]]:
    raw = path.read_bytes()
    fmt = detect_format(raw)              # BOM/CRLF/encoding/has_cdata（生バイト）
    parser = etree.XMLParser(
        remove_blank_text=False,
        strip_cdata=False,
        load_dtd=False,          # XXE 対策: DTD 読み込み拒否
        no_network=True,         # 外部ネットワークアクセス拒否
        resolve_entities=False,  # entity 展開無効化（billion laughs 対策）
    )
    root = etree.fromstring(raw, parser=parser)
    # コメント検出（v0.6）: root.iter() は _Comment ノードを含む
    fmt.has_comment = any(isinstance(n, etree._Comment) for n in root.iter())
    # <Params> を読み、<Content>/<String> を列挙して index 振る
    # returns (entries, fmt, root, params_meta)
    ...
```

- `remove_blank_text=False`: 空白テキストノードを保持（xTranslator 互換のため）。
- `strip_cdata=False`: CDATA セクションがあれば保持（v0.1 では出現しない想定だが安全側）。
- **XXE/entity hardening**: `load_dtd=False`, `no_network=True`, `resolve_entities=False` を設定し、DTD 読み込み・外部ネットワークアクセス・entity 展開を無効化（billion laughs / XXE 対策）。※ lxml 6.x では `no_load_dtd` は不正キーワード、`load_dtd=False` が正しい。
- `raw` バイト列から `FileFormat` を先に抽出。

#### 5.5.2 検出ルール（v0.6: CDATA/comment 検出追加）

- BOM: 先頭3バイトが `EF BB BF` → `has_bom=True`
- 改行: 最初の改行バイト列で判定（`\r\n` → CRLF、`\n` → LF、`\r` 単独 → CR）
- encoding: XML宣言の `encoding=` 属性を読む。なければ UTF-8。
- **CDATA**: `b'<![CDATA[' in raw`（生バイトスキャン）。`root.iter()` ではCDATAは見えないため。
- **コメント**: `any(isinstance(n, etree._Comment) for n in root.iter())`。`_Comment` ノードとして取得可能（lxml 6.0.2 実機検証済み）。

#### 5.5.3 書き出し

```python
def serialize_xml(
    entries: list[StringEntry],
    root: etree._Element,
    fmt: FileFormat,
) -> bytes:
    # 0. 事前検証: CDATA と XMLコメント は v0.1 では非サポート（v0.6）。
    #    fmt.has_cdata / fmt.has_comment は parse_xml で検出済み。
    if fmt.has_cdata or fmt.has_comment:
        raise IroiroError(
            f"Input XML contains {'CDATA' if fmt.has_cdata else ''} "
            f"{'and ' if fmt.has_cdata and fmt.has_comment else ''}"
            f"{'comments' if fmt.has_comment else ''}. "
            "v0.1 does not support these (regex post-process would corrupt them)."
        )
    # 1. root 配下の各 <String>/<Dest>.text を new_dest or original_dest で差し替え
    #    ※ .text には生文字列を入れる。lxml がエスケープは担当。
    # 2. 空要素の展開（木構造アプローチ、v0.5）:
    #    for elem in root.iter():
    #        if len(elem) == 0 and elem.text is None and not isinstance(elem, etree._Comment):
    #            elem.text = ""   # lxml 6.x は <X></X> 形式で出力（実機検証済み）
    #    ※ root.iter() は _Comment ノードを含むので isinstance チェックで除外（v0.6）
    # 3. etree.tostring(
    #        root,
    #        xml_declaration=True,
    #        encoding=fmt.encoding,
    #        standalone=True,
    #    )
    #    ※ lxml は short_empty_elements 引数をサポートしない
    # 4. （フォールバック regex）step 2 でカバーできない場合:
    #    out = re.sub(
    #        rb'<([A-Za-z][A-Za-z0-9_\-\.]*)(\s[^<>]*?)?/>',
    #        rb'<\1\2></\1>',
    #        out,
    #    )
    #    ※ step 0 で CDATA/comment を排除済みなので安全
    # 5. bytes に対して改行コード正規化（一旦 LF に統一→指定 newline に変換）
    # 6. BOM 付与
```

重要:
- **絶対にアプリ側でXMLエスケープしない**（二重エスケープ防止）。
- 改行正規化は「LFに一旦統一→指定newlineに変換」で二重化を防止（`\r\n` → `\r\r\n` 回避）。
- **空要素展開**（v0.5+v0.6）: 2段階戦略。
  - **第一**: 木構造レベルで `elem.text = ""` をセット。lxml 6.x はこれを `<X></X>` 形式で出力する（実機検証済み）。
  - **第二（フォールバック）**: step 4 の regex。step 0 で CDATA/comment 入力を排除済みなので安全。
  - **v0.6 修正**: `root.iter()` は `_Comment` ノードを含むため、`isinstance(elem, etree._Comment)` で除外する。CDATA ノードは `iter()` に含まれないが、step 0 で入力排除するので触らない。
- **CDATA / コメント は v0.1 では非サポート**: xTranslator 形式では出現しない（サンプル実査で確認）。入力にあったら `IroiroError` で停止。
- **regex タグ名**: `[A-Za-z][A-Za-z0-9_\-\.]*`。コロン `:` は v0.1 では非サポート（名前空間無し）。xTranslator のタグ名は素朴な識別子なので十分。

#### 5.5.4 ラウンドトリップ保証（v0.5: 構造的等価 + フォーマット保存）

- **「byte完全一致」は要求しない**。lxml のシリアライザ細部（実体参照表現、属性クォート等）に振り回されない。
- **「構造的等価」を保証**: `parse → serialize → parse` で同一の木構造・同じ `.text`・同じ属性が得られること。
- ただし以下は**バイトレベルで保持**を要求:
  - XML宣言 `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>`
  - BOM の有無
  - 改行コード（CRLF/LF）
  - インデント空白（`remove_blank_text=False`）
  - 空要素の `<X></X>` 形式（§5.5.3 step 2 の木構造アプローチ + step 4 regex フォールバック）
  - `List="0"` 等の属性
- 上記以外の細かい差分は許容。xTranslator が読めればよい。
- **v0.1 制約**: CDATA セクション と XML コメント は入力に存在しない前提。`fmt.has_cdata` / `fmt.has_comment`（v0.6）で検出した場合は `IroiroError` で停止。

### 5.6 エスケープ・プレースホルダ（`escape.py`）

**設計原則**: アプリ側でXMLエスケープ/アンエスケープはしない。lxmlに任せる。
LLM へは生文字列（lxml が parse した時点でアンエスケープ済）を渡し、LLM から受け取った生文字列をそのまま `.text` にセットする。

#### 5.6.1 保護対象トークン（汎用定義）

```
PROTECTED_TOKENS_RE = re.compile(
    r"""
    <[A-Za-z]+=[A-Za-z0-9_\-]+>   # <alias=NAME>, <Alias=NAME>, <alias=quest-giver> (ハイフン許容、v0.3)
    | <br\s*/?>                     # <br>, <br/>
    | %\{[^}]+\}                    # %{name}
    | \\[nr]                        # \n, \r (リテラル)
    | \#                            # # (Skyrim 色コード等)
    """,
    re.VERBOSE,
)
```

注記: alias 名に含まれる文字は `[A-Za-z0-9_\-]`（英数字・アンダースコア・ハイフン）。**ドット `.` とコロン `:` は v0.1 では非サポート**。サンプル実査では出現しない。必要になれば v0.2機能以降で拡張。

#### 5.6.2 関数シグネチャ（v0.3: `fallback_to_source` 削除）

```python
def extract_tokens(text: str) -> list[str]:
    """出現順にトークンを抽出（重複含む）"""

def tokens_match(source_tokens: list[str], dest_tokens: list[str]) -> tuple[bool, str]:
    """順序は問わないが、各トークンの出現回数が一致することを検証。
    不一致時は理由を返す。"""
```

#### 5.6.3 検証ポリシー（v0.3: 単一セマンティクス）

- 原文のトークン列を抽出。
- LLM 訳文のトークン列を抽出。
- **順序は問わない**（日本語では語順が変わるため）。**各トークンの出現回数が一致** することを検証。
- **不一致時の挙動（全モジュールで統一）**:
  - 警告ログを出力
  - `state = "failed"`
  - `new_dest = original_dest`（元の `<Dest>` を保持）
  - **`source` で上書きしない**（`original_dest == source` の場合は実質同じだが、`original_dest != source` のケースを保護）

### 5.7 翻訳（`translator.py`）

#### 5.7.1 Source言語判定（v0.3: 空/空白スキップ + non-ASCII 英語許容）

```python
def is_translation_needed(source: str) -> bool:
    """翻訳が必要か。
    - 空 または 空白のみ → False（スキップ、original_dest 保持）
    - ひらがな・カタカナ・漢字（CJK統合漢字）を含む → False（スキップ）
    - それ以外（ASCIIのみ、または non-ASCII でも日本語以外：café, "Hello", Wait… 等）→ True
    """

def contains_japanese(text: str) -> bool:
    """ひらがな(U+3040-309F), カタカナ(U+30A0-30FF), CJK統合漢字(U+4E00-9FFF) を含むか。
    ※ CJK Extension B/C/D 等 (U+20000-) は v0.1 では非サポート。"""
```

- スキップ時: `state=skipped`、`new_dest = original_dest`。
- v0.3 改修点:
  - **空/空白Source をスキップ**（LLMに空文字を送らない、`<Dest>` 保護）
  - **non-ASCII 英語を翻訳対象化**（curly quotes `" "`、アクセント `café`、ellipsis `…` 等を含む英語も翻訳）

#### 5.7.2 長文スキップ

- `len(source) > max_chars`（デフォルト 4000）の場合: `state=skipped`、警告ログ。
- v0.1 では **分割しない**。分割は将来機能。

#### 5.7.3 プロンプト

- System:
  > "Skyrim MOD の英文を日本語に翻訳する。固有名詞・ `<alias=...>` 等のプレースホルダ・ `<br>`・改行文字・ `#` 記号は **そのまま維持** すること。簡潔で自然な日本語。**訳文のみ** 出力し、説明・マークダウン・ラベル・複数行は禁止。"
- User: `<REC>` 型からカテゴリヒント（例: `MGEF:FULL` → "魔法の効果名。1〜4語程度。"）+ 原文。

#### 5.7.4 出力 post-processing（明確化）

LLM が守らないケースを想定したクリーニング。**保守的** に適用:

1. 末尾改行・前後ホワイトスペース: トリム。
2. **最初の行のみ採用**: 複数行返却時は最初の行。残は破棄＋警告。
3. 一般的なノイズパターンの削除:
   - 行頭 `訳文:`, `Translation:`, `日本語:`, `Result:`, `Output:` 等のラベル
   - ` ``` ` フェンス
   - 行頭 ` - `, ` * `, ` 1. ` 等のリストマーカー
4. **トークン整合性チェック**: 不一致なら `state=failed`、`new_dest=original_dest`（§5.6.3 の単一セマンティクス）。
5. **前後の `"`, `'` は削除しない**（意味のある場合があるため）。

#### 5.7.5 リトライ・フォールバック

- リトライ: **最大3回試行（初回＋リトライ2回）**・指数バックオフ（`[1s, 2s]`・試行間）。`openai.APIError`, `httpx.TimeoutException`, `httpx.NetworkError` を対象。
- 最終失敗: `state=failed`、`new_dest = original_dest`（元の `<Dest>` を保持）。`--overwrite-on-fail` フラグは v0.1 では**提供しない**（安全側）。

#### 5.7.6 HTTP クライアント

- `openai.AsyncOpenAI(base_url=..., api_key=..., timeout=httpx.Timeout(connect=10, read=args.timeout, write=10, pool=10))`
- `Semaphore(concurrency)` で同時リクエスト制限。

### 5.8 再開機能（`progress.py`）— 並行安全（v0.3: シグネチャ修正）

```python
class ProgressWriter:
    def __init__(
        self,
        progress_path: Path,      # <input>.iroiro-progress.json のパス
        input_path: Path,         # 入力 XML のパス（メタ情報として記録）
        input_hash: str,
        api_base: str,
        model: str,
    ):
        self._path = progress_path
        self._lock = asyncio.Lock()
        self._data = {
            "input_path": str(input_path),       # v0.3: input XML のパスを正しく記録
            "input_hash": input_hash,
            "api_base": api_base,
            "model": model,
            "entries": {},      # str(index) -> dest
            "failed": [],
        }

    async def mark_done(self, index: int, dest: str) -> None:
        async with self._lock:
            self._data["entries"][str(index)] = dest
            await self._flush()

    async def mark_failed(self, index: int) -> None:
        async with self._lock:
            self._data["failed"].append(index)
            await self._flush()

    async def _flush(self) -> None:
        """原子的書き込み: tmp -> os.replace。ロック内で呼ぶ。"""
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2))
        os.replace(tmp, self._path)

    def load_existing(self) -> ProgressData | None:
        """progress.json が無ければ None。
        JSON decode error / hash 不一致 は ValueError を上げて停止。
        v0.5: §6.5 と型を整合（ProgressData | None）。"""
```
```

- ファイル: `<input>.iroiro-progress.json`
- `--resume` 時:
  - 既存 `entries` の index はスキップ（`state=translated`、`new_dest=loaded`）。
  - 既存 `failed` の index は再試行しない（`state=failed`、`new_dest=original_dest`）。
  - `input_hash` 不一致 → 停止。
  - **JSON decode error → 停止**（v0.3）。ユーザーにファイル削除を促すメッセージを出す。自動修復しない。

### 5.9 失敗時の `<Dest>` 保護

- `state=failed` → `new_dest = original_dest`
- `state=skipped` → `new_dest = original_dest`
- これにより、**元のXMLの `<Dest>` が過去に人間が修正済みでも破壊しない**。

## 6. 関数シグネチャ契約（WP並列/直列の境界）

以下を固定することで、テストと実装の結合面を安定化。

### 6.1 `models.py`

```python
@dataclass(slots=True)
class StringEntry: ...        # 5.2 参照

@dataclass(slots=True)
class FileFormat: ...         # 5.5.1 参照
```

### 6.2 `xml_io.py`（v0.6: `params_meta` 削除、`_Element` 統一、`FileFormat.has_cdata/has_comment` 追加）

```python
def parse_xml(path: Path) -> tuple[list[StringEntry], FileFormat, etree._Element, dict[str, str]]:
    """Returns (entries, fmt, root, params_meta)。
    root は etree.fromstring() の戻り値（_Element）。差し替え用に保持。
    params_meta は <Params> のメタ情報（README/handoff 用）。serialize には不要。
    fmt.has_cdata / fmt.has_comment は事前検出済み（v0.6）。"""

def serialize_xml(
    entries: list[StringEntry],
    root: etree._Element,
    fmt: FileFormat,
) -> bytes:
    """BOM/CRLF/宣言 を保持したバイト列を返す。
    空要素 `<X/>` を木構造アプローチ（elem.text=""）+ regex フォールバックで `<X></X>` に展開。
    fmt.has_cdata / fmt.has_comment の場合は IroiroError で停止（v0.6）。"""
```

### 6.3 `escape.py`

```python
PROTECTED_TOKENS_RE: re.Pattern[str]
def extract_tokens(text: str) -> list[str]: ...
def tokens_match(source_tokens: list[str], dest_tokens: list[str]) -> tuple[bool, str]: ...
```

### 6.4 `translator.py`

```python
@dataclass(slots=True)
class ApiConfig:
    base_url: str
    api_key: str
    model: str
    timeout: float
    concurrency: int
    max_chars: int

class Translator:
    def __init__(self, cfg: ApiConfig): ...
    async def translate_entry(self, source: str, rec: str) -> str: ...
    async def aclose(self) -> None: ...
```

### 6.5 `progress.py`（v0.4: `ProgressData` 導入）

```python
@dataclass(slots=True)
class ProgressData:
    entries: dict[int, str]    # index -> dest
    failed: list[int]
    input_hash: str
    api_base: str
    model: str

class ProgressWriter:
    def __init__(
        self,
        progress_path: Path,
        input_path: Path,
        input_hash: str,
        api_base: str,
        model: str,
    ): ...
    async def mark_done(self, index: int, dest: str) -> None: ...
    async def mark_failed(self, index: int) -> None: ...
    def load_existing(self) -> ProgressData | None:
        """progress.json が無ければ None。
        JSON decode error / hash 不一致 は ValueError を上げて停止。"""

def compute_input_hash(path: Path) -> str:
    """SHA256。path のバイト列をハッシュ。"""
```

### 6.6 `config.py`

```python
@dataclass(slots=True)
class RunConfig:
    input_path: Path
    output_path: Path
    api: ApiConfig
    resume: bool
    dry_run: bool
    verbose: bool
```

### 6.7 `cli.py`

```python
def main() -> None: ...      # typer entry, `translate` サブコマンド
```

## 7. テスト戦略

Codex 指摘の10項目に対応。各テストの責務を明記。

### 7.1 `test_xml_io.py`

- T1: `tiny_crlf_bom.xml` を parse→serialize して **構造的等価 + フォーマット保存**（宣言/BOM/CRLF/空要素形式が保持され、再 parse で同一木構造）。
- T2: `<Dest>` のみ変更した場合、**他は構造的に等価**（宣言/BOM/CRLF/空要素形式は不変）。
- T3: BOM 付き→BOM 付き、BOM 無し→BOM 無し。
- T4: CRLF→CRLF、LF→LF、混在→最初の改行コードで統一。
- T5: `standalone="yes"` 宣言保持。
- T6: 空白テキストノード保持。
- T7: `List="0"` 等の属性保持。
- T8: `<Dest>` に alias トークン `<alias=NAME>` を含む場合の正しい出力（**二重エスケープされない**）。
- T9: 空の `<Source>` / `<Dest>` の処理。
- T10: 巨大ファイル（サンプル679件）のメモリ・時間（緩い上限）。
- **T47 (v0.4)**: 空要素 `<Dest></Dest>` が `<Dest/>` に自己閉じ化されないこと（regex post-process で展開される）。
- **T48 (v0.4)**: 既にエスケープされたアンパサンド `<Source>A &amp; B</Source>` の往復（二重エスケープされない）。
- **T49 (v0.4)**: round-trip の「構造的等価」検証（`parse → serialize → parse` で同一木構造・`.text`・属性）。
- **T52 (v0.6)**: 入力 XML に CDATA セクション または XMLコメントが含まれる場合 → `IroiroError` で停止。
- **T52b (v0.6)**: コメント単体 `<!-- xxx -->` を含む入力 → `_Comment` ノード検出で停止。
- **T52c (v0.6)**: CDATA 単体 `<![CDATA[xxx]]>` を含む入力 → 生バイトスキャンで検出して停止。
- **T53 (v0.5)**: 空要素 + 属性 `<Dest List="0"/>` が `<Dest List="0"></Dest>` に正しく展開されること。

### 7.2 `test_escape.py`

- T11: `<alias=questgiver>` 抽出。
- T12: `<Alias=Questgiver>` 大文字小文字混在。
- T13: 1行に複数トークン `<alias=a> と <alias=b>`。
- T14: 隣接日本語 `<alias=client>に届ける`。
- T15: `<br>`, `%{name}`, `\n`, `#` の各抽出。
- T16: トークン順序違いはOK（`tokens_match` True）。
- T17: トークン欠落はNG（`tokens_match` False）。
- T18: トークン回数不一致はNG。
- **T45 (v0.4)**: ハイフン含む alias `<alias=quest-giver>` → 許容・抽出される（`test_escape.py` に配置）。

### 7.3 `test_progress.py`

- T19: `mark_done` → ファイル更新 → 再読込で同一。
- T20: 原子的書き込み: `tmp` が残らない（成功時）。
- T21: `input_hash` 不一致で `ValueError`。
- T22: **`--concurrency 4` で100エントリを同時 `mark_done`** → 件数完全、データ破損なし（NB#6/指摘#4対応）。
- T23: `failed` リストの追記。
- T24: progress.json 破損時の挙動（v0.3: JSON decode error → 停止＋ユーザー通知）。
- T25: temp ファイル残存時のクリーンアップ。
- **T46 (v0.4)**: ProgressWriter の `input_path` メタ情報が入力XMLのパスを指すこと（progress path でない）。
- **T50 (v0.4)**: `failed` index を含む progress.json を `--resume` で読み込み、それらの `<Dest>` が `original_dest` を保持すること。

### 7.4 `test_translator.py`

モックは `httpx.MockTransport` を `openai.AsyncOpenAI(http_client=...)` に注入。

- T26: 正常系（訳文のみ返却）。
- T27: `訳文: ほげ` → ラベル削除。
- T28: ` ```\nほげ\n``` ` → フェンス削除。
- T29: 複数行 → 最初の行のみ。
- T30: トークン欠落 → `state=failed`、`new_dest=original_dest`（§5.6.3 単一セマンティクス）。
- T31: HTTP 500×2 → 200（リトライ成功）。
- T32: HTTP 500×3 → `state=failed`。
- T33: タイムアウト → リトライ → 失敗。
- T34: 長文スキップ（max_chars 超過）。
- T41: 日本語混入Sourceはスキップ（ひらがな/カタカナ/漢字）。
- **T41b (v0.4)**: 空 `<Source></Source>` → スキップ、`new_dest=original_dest`。
- **T42 (v0.4)**: 空白のみ `<Source>   </Source>` → スキップ。
- **T43 (v0.4)**: non-ASCII 英語 `café`, `"Hello"`, `Wait…` → 翻訳対象（True）。
- **T44 (v0.4)**: トークン不一致 → `state=failed`、`new_dest=original_dest`（単一セマンティクス）。
- **T51 (v0.4)**: `original_dest != source` のエントリでトークン不一致 → `new_dest = original_dest`（`source` で上書きしないことの証明）。

### 7.5 `test_cli.py`（E2E）

- T36: `tiny.xml` → 出力 XML を再 parse して期待通り。
- T37: `--dry-run` → 出力ファイル無し、件数表示。
- T38: `--resume` → progress.json を読んで続き。
- T39: 失敗含むケース → `<Dest>` は元のまま。
- T40: 出力 XML を xTranslator 相互運用性チェック（簡易: 宣言/BOM/CRLF/aliasエスケープが正しい）。

### 7.6 実行コマンド

```
uv sync
uv run pytest                       # 全テスト
uv run pytest -k "xml_io"           # 個別
uv run ruff check
uv run mypy iroiro
```

## 8. 実装計画・Work Packages

**直列実行**（Codex指摘#7並列リスク対応）。テスト契約を関数シグネチャレベルで固定したが、XML安全テストは実装の前提条件となるため、先にテストを書いて実装の妥当性を検証する。

### WP-1-tests

- Goal: テストとフィクスチャを先に実装し、実装の受け入れ基準を固定。
- Owner: implementer
- Allowed: `tests/**`
- Forbidden: `iroiro/**`, `pyproject.toml`, `README.md`, `.gitignore`, `.python-version`
- Inputs: 本計画書 v0.6、関数シグネチャ契約（§6）
- Outputs:
  - `tests/conftest.py`
  - `tests/fixtures/{tiny,tiny_crlf_bom,japanese_source,long_source,sample_subset}.xml`
  - `tests/test_{xml_io,escape,progress,translator,cli}.py`
- Dependencies: 本計画書承認
- 並列: なし（直列の第1段）
- Merge基準: `uv run pytest` が WP-2 完了後に全 green、`ruff`/`mypy` クリーン
- 注意: WP-1 単体では `iroiro/` パッケージが無いため import error になるのは正常。WP-2 完了後に green になる。
- Risk: low

### WP-2-core

- Goal: `iroiro/` パッケージ本体と `pyproject.toml`、`.python-version`、`.gitignore` 追記。
- Owner: implementer
- Allowed: `iroiro/**`, `pyproject.toml`, `.python-version`, `.gitignore`
- Forbidden: `tests/**`, `README.md`, `docs/**`
- Inputs: 本計画書、WP-1 のテスト契約
- Outputs: 実装コード一式
- Dependencies: WP-1 完了
- 並列: なし（直列の第2段）
- Merge基準: WP-1 のテスト全 green、`ruff`/`mypy` クリーン、サンプルXML round-trip 成功
- Risk: medium

### WP-3-docs

- Goal: README・handoff。
- Owner: implementer（PMが一部直接編集する場合あり）
- Allowed: `README.md`, `docs/**`
- Forbidden: `iroiro/**`, `tests/**`, `pyproject.toml`
- Inputs: 確定した実装
- Outputs: README、`docs/handoff/001-initial.md`
- 並列: なし（直列の第3段、ただしドラフト作成は WP-2 と並行可）
- Merge基準: 実装と一致していること
- Risk: low

### 段取り

1. 計画承認 → Codex CLI 再レビュー（本 v0.6 で）
2. **WP-1** 実装（テスト・フィクスチャ）
3. **WP-2** 実装（`iroiro/` パッケージ）
4. PM 統合検査: `git diff`、テスト全件実行、combined diff 点検、サンプル round-trip
5. **WP-3** README・handoff
6. 最終 Codex CLI diff review → QA review → final report

## 9. 主要リスクと対策

| リスク | 影響 | 対策 |
|---|---|---|
| XML破損で xTranslator が読めない | 致命的 | 「構造的等価 + フォーマット保存」テスト（T1, T2, T49）、BOM/CRLF/宣言/空要素保存（§5.5） |
| **二重エスケープ**（`&amp;lt;` 化） | 致命的 | アプリ側でエスケープしない、lxml任せ（§5.5.3）、テスト T8 |
| **プレースホルダ欠落**（`<alias=...>` 消失） | 高 | 汎用トークン検出（§5.6）、回数検証 T16-18、フォールバック |
| LLM出力のノイズ（説明・マークダウン・ラベル） | 高 | post-processing ルール（§5.7.4）、テスト T27-29 |
| progress.json 並行書き込み競合 | 高 | `ProgressWriter` + `asyncio.Lock`、テスト T22 |
| 長文BOOKでコンテキスト超過 | 中 | v0.1 ではスキップ（§5.7.2） |
| progress.json 破損 | 中 | 原子的書き込み（`tmp`+`os.replace`）、`input_hash` 検証 T21 |
| ローカルLLM応答遅延・不安定 | 中 | リトライ・指数バックオフ、タイムアウト T31-33 |
| **既存の日本語Sourceを過翻訳** | 中 | `is_translation_needed`（§5.7.1）、件数レポート |
| Source==Dest 判定ミス | 低 | Source言語判定で回避、全件強制翻訳しない |

## 10. ドキュメント影響

- `README.md`: 現状は構想のみ。**要更新**:
  - インストール（`uv sync` / `uv tool install`）
  - 使い方（CLI フラグ一覧、設定例）
  - **BOM/CRLF/宣言 保持動作** の明記
  - **失敗時の `<Dest>` 保護ポリシー** の明記
  - **長文スキップ** (`--max-chars`) の明記
  - トラブルシュート（llama.cpp model alias 不一致、タイムアウト、ノイズ出力）
- `docs/plans/001-initial.md`: 本文書。
- `docs/handoff/001-initial.md`: 完了時に作成。
- `LICENSE`: 変更不要。
- `.gitignore`: Python/uv 標準 + `*.translated.xml` + `*.iroiro-progress.json`（WP-2 で実装）。

## 11. ハンドオフ影響

- v0.1 完了時に `docs/handoff/001-initial.md` を作成。
- 主要項目:
  - 変更内容・検証結果
  - **既知の xTranslator 相互運用性制限**（byte-level 保存の範囲）
  - **サンプルXML round-trip 成功** の記録
  - **failed/skipped の意味** の明記
  - ロールバック手順（出力XML削除＋progress.json削除）
  - 次ステップ（用語集 v0.2、長文分割）

## 12. 言語ポリシー

- ドキュメント・ハンドオフ・コメントの **説明文** は **日本語**。
- 技術識別子（関数名・CLIフラグ・API名・XMLタグ・ファイルパス）・コマンド・エラーメッセージは **英語のまま**。
- ユーザー向けメッセージ（CLI出力）は **日本語優先**、技術用語は適宜英語併記。

## 13. 環境依存パラメータ（ユーザー確定）

| パラメータ | デフォルト値 | 上書き |
|---|---|---|
| LLMエンドポイント | `http://localhost:8081/v1` (llama.cpp server) | `--api-base` |
| モデル名 | `ggml-org/gemma-4-12B-it-GGUF:Q4_K_M` | `--model` |
| APIキー | `iroiro`（ダミー・llama.cpp は検証しない） | `--api-key` |

注記（READMEに明記）:
- llama.cpp server が受け取る `model` パラメータは起動時の `--alias` / `--host` 依存で変わる。`--model` で適宜調整。
- APIキーは llama.cpp の OpenAI 互換サーバーでは検証されないが、`Authorization: Bearer` ヘッダとしては送信する。

## 14. レビューゲート（normal）

- [x] ユーザーと本計画 v0.1 の合意
- [x] Codex CLI: プランレビュー v0.1 → **reject** → v0.2 で修正
- [x] ユーザーと v0.2 の合意
- [x] Codex CLI: プランレビュー v0.2 → **reject ("small cleanup")** → v0.3 で修正
- [x] ユーザーと v0.3 の合意（v0.2 包括合意に基づき minor cleanup は PM 責任で反映）
- [x] Codex CLI: プランレビュー v0.3 → **reject ("small cleanup")** → v0.4 で修正
- [x] ユーザーと v0.4 の合意（minor cleanup 継続、PM 責任で反映）
- [x] Codex CLI: プランレビュー v0.4 → **reject** → v0.5 で修正
- [x] ユーザーと v0.5 の合意（minor cleanup 継続、PM 責任で反映）
- [x] Codex CLI: プランレビュー v0.5 → **reject (new blocking: none)** → v0.6 で修正
- [x] ユーザーと v0.6 の合意（minor cleanup 継続、PM 責任で反映）
- [x] Codex CLI: プランレビュー v0.6 → **approve-with-notes**（editorial 3点のみ残、実装非ブロック）
- [ ] WP-1 実装（テスト・フィクスチャ） ← イマ
- [ ] WP-2 実装（`iroiro/` パッケージ）
- [ ] テスト全件実行
- [ ] PM combined diff 検査
- [ ] WP-3 docs/handoff
- [ ] Codex CLI: 最終 diff レビュー
- [ ] QA 最終レビュー
- [ ] Final report

## 15. 代替案と却下理由

- **同期 openai クライアント**: 実装は簡単だがローカルLLMの遅延で並列価値が高い → async 採用。
- **ElementTree（標準ライブラリ）**: `standalone="yes"` の保持が面倒 → lxml 採用。
- **csv/TSV 中間形式**: XML直接編集よりシンプルだが、形式の正確な再現が難しい → XML直接編集。
- **用語集 v0.1 組み込み**: ユーザー指示により見送り。
- **長文の自動分割**: 複雑性が高く、v0.1 では `--max-chars` 超過時スキップに見送り。
- **アプリ側でのXMLエスケープ**: lxml が担当するため不要・危険（二重エスケープ）。
- **WP-1/WP-2 並列実行**: 関数シグネチャ契約で固定したが、XML安全テストが実装前提となるため直列化（Codex指摘#7尊重）。

## 16. Codex v0.1 レビューへの対応一覧

| 指摘 | 種別 | v0.2 での対応 |
|---|---|---|
| 1. XMLエスケープがunsafe（二重エスケープ） | blocking | §5.5.3「アプリ側でエスケープしない」、§5.6「lxml任せ」、テスト T8 |
| 2. プレースホルダ不完全 | blocking | §5.6 汎用トークン定義（`<alias=>` 含む）、テスト T11-15 |
| 3. フォーマット保存が不十分 | blocking | §5.5 BOM/CRLF保存戦略、テスト T1-7, T10 |
| 4. progress並行書き込み競合 | blocking | §5.8 `ProgressWriter` + `asyncio.Lock`、テスト T22 |
| 5. 長文挙動が曖昧 | blocking | §5.7.2 v0.1 ではスキップ、テスト T34 |
| NB1. 既存日本語Sourceの過翻訳 | non-blocking | §5.7.1 `is_translation_needed`、件数レポート |
| NB2. StringEntry の dest 分離 | non-blocking | §5.2 `original_dest` / `new_dest` 分離 |
| NB3. post-processing 明確化 | non-blocking | §5.7.4 ルール明示 |
| NB4. 失敗時のDest保護 | non-blocking | §5.9 `new_dest = original_dest` |
| NB5. HTTPタイムアウト | non-blocking | §5.7.6 `--timeout` フラグ |
| Missing tests 1-10 | tests | §7 に T1-40 として網羅 |
| WP並列リスク | WP | §8 直列化、§6 シグネチャ契約 |

## 17. Codex v0.2 レビューへの対応一覧（v0.3）

| 指摘 | 種別 | v0.3 での対応 |
|---|---|---|
| Residual #2 partial: トークン不一致フォールバック矛盾 | blocking | §5.6.2 `fallback_to_source` 削除、§5.6.3 単一セマンティクス（`state=failed`+`new_dest=original_dest`）、§5.7.4 と T44 整合 |
| Residual #3 partial: byte-identical 過剰 | blocking | §5.5.4 「構造的等価」に緩和、`short_empty_elements=False` 明示、T47/T49 追加 |
| New B1: 空/空白Source をLLMに送ってしまう | blocking | §5.7.1 `is_translation_needed` で空/空白はスキップ、T41/T42 追加 |
| New B2: トークン不一致セマンティクス矛盾 | blocking | 上記 Residual #2 と同じ対応 |
| NB1: ProgressWriter `input_path` バグ | non-blocking | §5.8 / §6.5 `progress_path` / `input_path` 分離、T46 追加 |
| NB2: T24 progress.json 破損時 | non-blocking | §5.8 JSON decode error → 停止（新規作成しない） |
| NB3: `parse_xml` 戻り型不整合 | non-blocking | §6.2 `_Element` に統一 |
| NB4: ASCII-only 限界（curly quotes/café/ellipsis） | non-blocking | §5.7.1 「日本語文字を含むか」判定に変更、T43 追加 |
| Test gaps: 空Source・トークン mismatch 境界・non-ASCII英語・空タグ・エスケープ済アンパサンド・ハイフンalias | tests | T41-T49 追加 |

## 18. Codex v0.3 レビューへの対応一覧（v0.4）

| 指摘 | 種別 | v0.4 での対応 |
|---|---|---|
| New B1: lxml 未サポートの `short_empty_elements=False` を使っていた | blocking | §5.5.3 regex post-process で `<TAG/>` を `<TAG></TAG>` に展開。lxml API 誤認を修正 |
| New B2: §4.1/§5.1 が未だ ASCII-only 表記 | blocking | 「日本語文字を含むか」に統一 |
| New B3: §5.5.3 と §6.2 の `serialize_xml` シグネチャが不一致（`params_meta`） | blocking | §5.5.3 から `params_meta` 削除、§6.2 と整合 |
| Residual#2 partial: T30 が「フォールバック(source)」のまま | blocking | T30 を `state=failed`+`new_dest=original_dest` に修正 |
| Residual#3 partial: T1/T2/§9 が「バイト完全一致」のまま | blocking | 「構造的等価 + フォーマット保存」に修正 |
| NB1: WP-1 Inputs と §8 step 1 が v0.2 参照 | non-blocking | v0.3 参照に更新 |
| NB2: T45 が `test_translator.py` にある（escape 系） | non-blocking | `test_escape.py` に移動 |
| NB3: `load_existing()` 戻り値が曖昧 | non-blocking | `ProgressData` dataclass 導入、`ProgressData \| None` に明確化 |
| Test gaps: original_dest≠source・CJK Extension・resume failed・実装可能な空要素戦略 | tests | T50/T51 追加、`contains_japanese` 対象ブロック明記、T47 を regex post-process 検証に |

## 19. Codex v0.4 レビューへの対応一覧（v0.5）

| 指摘 | 種別 | v0.5 での対応 |
|---|---|---|
| New B1: regex post-process が CDATA/comment 内を破壊しうる | blocking | §5.5.3 step 0 で `_has_cdata_or_comment(root)` を検出 → `IroiroError` で停止。第一戦略を木構造アプローチ（`elem.text=""`）に変更し、regex はフォールバックに。テスト T52 追加 |
| New B2: §5.8 と §6.5 の `load_existing` 戻り型が矛盾 | blocking | §5.8 を `ProgressData \| None` に統一 |
| NB1: WP-1 Inputs と §8 step 1 が v0.3 参照 | non-blocking | v0.4 参照に更新 |
| NB2: regex タグ名が `[A-Za-z][A-Za-z0-9_]*` のみ | non-blocking | `[A-Za-z][A-Za-z0-9_\-\.]*` に拡張（名前空間対応の念のため） |
| NB3: `<br/>` が `<br></br>` になる懸念 | non-blocking | v0.1 ではXML要素としての `<br/>` は出現しない（サンプル実査）。文字列としての `<br>` プレースホルダとは別物。将来機能で対応 |
| Test gaps: CDATA 安全性・属性付き空要素 | tests | T52（CDATA/comment 入力 → エラー）、T53（属性付き空要素の展開）追加 |

## 20. Codex v0.5 レビューへの対応一覧（v0.6）

| 指摘 | 種別 | v0.6 での対応 |
|---|---|---|
| Residual B1 partial: CDATA 検出が `root.iter()` で不可能 | blocking | `FileFormat.has_cdata`/`has_comment` 追加。CDATA は `b'<![CDATA[' in raw`（生バイト）、コメントは `isinstance(n, etree._Comment)`（`iter()` 経由）。lxml 6.0.2 実機検証済み |
| NB1: §5.5.3 の「`root.iter()` はコメントを含まない」は誤り | non-blocking | 修正: `root.iter()` は `_Comment` を含む。`isinstance(elem, etree._Comment)` で除外 |
| NB2: WP-1 Inputs と §8 step 1 が v0.4 参照 | non-blocking | v0.5 参照に更新 |
| NB3: §6.2 `serialize_xml` docstring が v0.4 戦略のまま | non-blocking | 木構造アプローチ＋regex フォールバック＋`FileFormat.has_cdata/has_comment` 検出に更新 |
| NB4: regex コロン非サポートの明記 | non-blocking | 「コロン `:` は v0.1 では非サポート（名前空間無し）」を明記 |
| Test gaps: T52 配置・CDATA raw bytes 検出・コメント検出 | tests | T52 を `test_xml_io.py` に移動、T52b（コメント検出）・T52c（CDATA raw bytes 検出）追加 |
