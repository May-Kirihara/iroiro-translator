# iroiro-translator v0.2 計画: 翻訳スキップ REC 型

- 作成日: 2026-06-28
- 更新日: 2026-06-28 (v3: Codex レビュー#2 反映)
- 状態: ユーザー合意済み → Codex CLI 再レビュー待ち
- リスク分類: **normal**（ユーザー動作変更あり・後方互換性影響）
- 完了状態: not-started

## 変更履歴

- v1: 初版
- v2: Codex レビュー#1（reject）反映。progress.json fingerprint・CLI 表現修正・Translator 内部呼び出し非明記・テスト追加等
- **v3**: Codex レビュー#2（reject）反映
  - **空集合 fingerprint を `""` と定義**（v0.1 progress.json との互換性）
  - **WP-1 スコープを T56-T82 に拡張**（test_progress.py 含む）
  - **WP-2 スコープに `iroiro/progress.py` を追加**（ProgressData/ProgressWriter 変更のため）
  - テスト追加: T81（`compute_skip_records_fingerprint(frozenset())` 単体）・T82（CLI レベルの --resume mismatch）

---

## 1. 目標

Skyrim MOD XML の `<REC>` 型が「内部管理用」のレコード（`HDPT:FULL` 等）の場合、
`<Source>` を LLM 翻訳せず **スキップ** する。デフォルトで12件の REC 型をスキップし、
`--no-skip-default-records` で無効化、`--skip-records` で追加可能にする。

- 入力: `SSTXMLRessources` v2 XML（v0.1 と同じ）
- 出力: 同形式 XML（該当 REC 型の `<Dest>` は元のまま保持）
- 影響: ユーザーが意図せず内部管理名を翻訳してしまう事故を未然に防止

## 2. 背景

### v0.1 の問題点

v0.1 の `is_translation_needed(source)` は `<Source>` の文字列のみで判定（空/空白/日本語混入）。
`<REC>` 型を考慮していないため、以下のケースで**誤翻訳**が起きる:

- `HDPT:FULL`（Head Part name）: 内部管理用だが、v0.1 は翻訳してしまう
- `RACE:FULL`（Race name）: 種族名は他MODとの連携で翻訳非推奨のケースがある

実機検証（v0.1 の sample データ）でも、ユーザーが「以下のレコードは内部管理用に使われるので
翻訳しないようにする」と指摘。これが v0.2 の発端（`docs/notes/translate-skip-records.md`）。

### ユーザー決定（ブレスト合意）

- **用語集機能は v0.3 以降に見送り**。v0.2 は「スキップ REC 型」のみに集中。
- **案B-2**: デフォルト12件をスキップ + `--no-skip-default-records` で無効化。
  - 案B-1（2種類分割）は複雑なので見送り
  - 案B-3（デフォルト無し）は安全側ではないので見送り

## 3. スコープ

### 3.1 目標（v0.2）

- `DEFAULT_SKIP_RECORDS` 定数（12件の REC 型）を追加
- `is_translation_needed(source, rec, skip_records)` に `rec` / `skip_records` 引数を追加
- CLI フラグ `--no-skip-default-records`（FLAG, default `False`）
- CLI フラグ `--skip-records TEXT`（カンマ区切りで追加）
- dry-run 出力に「スキップ（REC 型）」行を追加
- ドキュメント更新（README/usage/design/notes）

### 3.2 非目標（v0.2）

- 用語集機能（v0.3 以降）
- 長文 BOOK の自動分割（v0.3 以降）
- スキップリストのファイル読み込み（`--skip-records-file PATH`）— 需要が出たら追加
- REC 型ごとの個別プロンプト調整
- BPTD:BPTN 以外の `:FULL` 以外の REC 型の特別扱い

## 4. デフォルトスキップリスト

`docs/notes/translate-skip-records.md` の12件を組み込みで持つ:

```python
DEFAULT_SKIP_RECORDS: frozenset[str] = frozenset({
    "HDPT:FULL",  # Head Part name
    "FURN:FULL",  # Furniture name
    "CLAS:FULL",  # Class name
    "DOOR:FULL",  # Door name
    "FACT:FULL",  # Faction name
    "CLFM:FULL",  # Color Form name
    "TREE:FULL",  # Tree name
    "MGEF:FULL",  # Magic Effect name
    "RACE:FULL",  # Race name
    "EXPL:FULL",  # Explosion name
    "HAZD:FULL",  # Hazard name
    "BPTD:BPTN",  # Body Part Data name
})
```

注記: `MGEF:FULL` と `RACE:FULL` は翻訳を**希望する**ユーザーも多い。
デフォルトでスキップするが、`--no-skip-default-records` または
`--skip-records` で個別制御可能。ドキュメントで明記する。

## 5. 実装

### 5.1 `iroiro/translator.py`（または新設 `iroiro/rec_filter.py`）

```python
DEFAULT_SKIP_RECORDS: frozenset[str] = frozenset({
    "HDPT:FULL", "FURN:FULL", "CLAS:FULL", "DOOR:FULL",
    "FACT:FULL", "CLFM:FULL", "TREE:FULL", "MGEF:FULL",
    "RACE:FULL", "EXPL:FULL", "HAZD:FULL", "BPTD:BPTN",
})


def is_translation_needed(
    source: str,
    rec: str = "",
    skip_records: frozenset[str] | None = None,
) -> bool:
    """翻訳が必要か。

    Args:
        source: <Source> の生文字列。
        rec: <REC> の値（例: "HDPT:FULL"）。空文字列も可（後方互換性）。
        skip_records: スキップ対象 REC 型のセット。None の場合は
            DEFAULT_SKIP_RECORDS を使用。

    Returns:
        True=翻訳対象, False=スキップ。
    """
    if skip_records is None:
        skip_records = DEFAULT_SKIP_RECORDS
    if rec and rec in skip_records:
        return False
    # 既存の判定（空/空白/日本語混入）にフォールバック
    stripped = source.strip()
    if not stripped:
        return False
    if contains_japanese(stripped):
        return False
    return True
```

### 5.2 CLI フラグ（`iroiro/cli.py`）

```
iroiro translate INPUT.xml
  [--no-skip-default-records]   # FLAG, default False
                                # デフォルトの12件スキップを「無効化」
                                # （※ --skip-records とは独立）
  [--skip-records TEXT]         # default ""
                                # カンマ区切りで追加スキップ REC 型
                                # 例: --skip-records "LCTN:FULL,ACTI:FULL"
```

`RunConfig` に `skip_records: frozenset[str]` を追加:
- デフォルト動作（フラグ無し）: `skip_records = DEFAULT_SKIP_RECORDS`
- `--no-skip-default-records` 単独: `skip_records = frozenset()`（空＝全 REC 型を翻訳対象）
- `--skip-records "X,Y"` 単独: `skip_records = DEFAULT_SKIP_RECORDS | {X, Y}`
- **両方指定**: `--no-skip-default-records` が「デフォルトを無効化」した上で `--skip-records` を適用
  - 例: `--no-skip-default-records --skip-records "MGEF:FULL"` → `skip_records = {"MGEF:FULL"}`
  - これは「デフォルト12件はスキップしない、ただし MGEF:FULL だけはスキップ」というユースケース（魔法名をスキップしたいが他は翻訳したい）

重要: **`Translator.translate_entry` は内部で `is_translation_needed` を呼ばない**。
`is_translation_needed` は **CLI 側でのみ** 呼び出し、スキップ判定を行う。
これにより既存の `Translator` テスト（`MGEF:FULL` 等を rec に渡すテスト）に影響を与えない。

### 5.2b skip-records parser（`_parse_skip_records`）

```python
def _parse_skip_records(text: str) -> frozenset[str]:
    """--skip-records のカンマ区切りテキストを frozenset に変換。

    仕様:
    - カンマで分割
    - 各要素は strip（前後空白を許容）
    - 空文字列要素は無視（`"A,,B"` → `{A, B}`）
    - 重複は自動で排除（frozenset の性質）
    - 大文字小文字は区別しない（`hdpt:full` → `HDPT:FULL` に正規化）
        ※ REC 型は Skyrim 側で大文字で定義されているため
    """
    if not text.strip():
        return frozenset()
    parts = [p.strip().upper() for p in text.split(",")]
    return frozenset(p for p in parts if p)
```

### 5.3 dry-run 出力の拡張

現在:
```
総エントリ数: 679
翻訳対象: 32
スキップ（空/日本語混入）: 647
スキップ（長文超過）: 0
```

v0.2:
```
総エントリ数: 679
翻訳対象: X
スキップ（空/日本語混入）: Y
スキップ（REC 型）: Z
スキップ（長文超過）: 0
```

実行時に各 entry の skip 理由を記録し、集計する。`state` の値を拡張:
- `pending` / `translated` / `skipped` / `failed`（既存）
- skip 理由は別途 `skip_reason: Literal["empty", "japanese", "rec", "max_chars"] | None`

実装案1: `state` を細分化（`skipped_empty` / `skipped_rec` 等）— 既存テストに影響大
実装案2: `state` は維持、別途 `skip_reason` フィールド追加（推奨）— 既存テストへの影響小

**案2を採用**。`StringEntry` に `skip_reason: str | None = None` を追加。

### 5.4 progress.json との整合性（v2: skip_records_fingerprint 追加）

REC 型スキップは入力 XML とスキップリストに依存:
- 入力 XML の hash は既に progress.json に記録済み（変更検知可能）
- **スキップリストの fingerprint も progress.json に記録し、resume 時に検証**（v2）

#### 実装

`ProgressWriter.__init__` と `ProgressData` に `skip_records_fingerprint: str` を追加:
- **API shape（Codex レビュー#3 NB1 対応）**: `current skip_records fingerprint` は `ProgressWriter.__init__` の引数として受け取る（`input_hash` と同じパターン）。`load_existing` は現在の fingerprint を `self._skip_records_fingerprint` と比較する。

```python
def compute_skip_records_fingerprint(skip_records: frozenset[str]) -> str:
    """skip_records の SHA256（hex）。
    ソートしてから計算することで順序に依存しない。
    **空集合の場合は空文字列 ``""`` を返す**（v0.1 progress.json との互換性のため）。
    ※ SHA256(b"") = "e3b0c442..." と区別するため、空集合は特例扱い。
    """
    if not skip_records:
        return ""
    canonical = "\n".join(sorted(skip_records))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

`progress.json` に `"skip_records_fingerprint"` フィールドを保存。
`load_existing` で現在の `skip_records` の fingerprint と比較:
- 不一致 → `ValueError` で停止（input_hash と同じパターン）
- ユーザーに progress.json の削除を促すメッセージ

```python
existing_skip_fp = raw.get("skip_records_fingerprint", "")
current_skip_fp = compute_skip_records_fingerprint(current_skip_records)
if existing_skip_fp != current_skip_fp:
    raise ValueError(
        f"skip_records fingerprint mismatch: progress.json has {existing_skip_fp!r}, "
        f"current skip_records is {current_skip_fp!r}. "
        f"Please remove {self._path} if skip records have changed."
    )
```

#### 後方互換性

v0.1 で作成された progress.json には `skip_records_fingerprint` が無い。
その場合は「空文字列」として扱い、現在の設定が空 `frozenset()` なら resume 可、
それ以外は不一致として停止。これにより v0.1 → v0.2 の移行で安全側に倒す。

実装上は:
```python
existing_skip_fp = raw.get("skip_records_fingerprint", "")
# v0.1 の progress.json は ""。v0.2 で --no-skip-default-records を使えば空 set になり一致。
# デフォルト動作（DEFAULT_SKIP_RECORDS）だと不一致で停止 → ユーザーに削除を促す。
```

## 6. テスト戦略

### 6.1 Unit（`test_translator.py` または新設 `test_rec_filter.py`）

- **T56**: `is_translation_needed("Hello", "HDPT:FULL")` → `False`（デフォルトリスト）
- **T57**: `is_translation_needed("Hello", "HDPT:FULL", skip_records=frozenset())` → `True`（空リスト）
- **T58**: `is_translation_needed("Hello", "MGEF:FULL")` → `False`（デフォルトリストに含まれる）
- **T59**: `is_translation_needed("Hello", "WEAP:FULL")` → `True`（デフォルトリストに無い）
- **T60**: `is_translation_needed("Hello", "BPTD:BPTN")` → `False`（`:FULL` 以外も機能）
- **T61**: `is_translation_needed("", "HDPT:FULL")` → `False`（空文字はスキップ）
- **T62**: `is_translation_needed("棺", "HDPT:FULL")` → `False`（日本語はスキップ、REC 型と複合）
- **T63**: `is_translation_needed("Hello", rec="")` → `True`（後方互換性・REC 無し）

### 6.2 CLI（`test_cli.py`）

- **T64**: `--no-skip-default-records` 指定で HDPT:FULL エントリが翻訳対象になる
- **T65**: `--skip-records "LCTN:FULL,ACTI:FULL"` 指定で追加スキップされる
- **T66**: `--no-skip-default-records` + `--skip-records "MGEF:FULL"` → MGEF のスキップ、それ以外は翻訳
- **T67**: dry-run 出力に「スキップ（REC 型）」行が含まれる
- **T69 (v2)**: dry-run で REC skip と言語 skip が**重複カウントされない**（REC skip のエントリは言語判定に回さない）
- **T70 (v2)**: REC スキップされたエントリの `<Dest>` が `original_dest` を保持（source で上書きしない）

### 6.2b skip-records parser（`test_translator.py` または新設 `test_rec_filter.py`）

- **T71 (v2)**: `_parse_skip_records("HDPT:FULL,FURN:FULL")` → `{"HDPT:FULL", "FURN:FULL"}`
- **T72 (v2)**: `_parse_skip_records("HDPT:FULL, ,FURN:FULL")`（空白要素混入）→ `{"HDPT:FULL", "FURN:FULL"}`
- **T73 (v2)**: `_parse_skip_records("HDPT:FULL,HDPT:FULL")`（重複）→ `{"HDPT:FULL"}`
- **T74 (v2)**: `_parse_skip_records("hdpt:full")`（小文字）→ `{"HDPT:FULL"}`
- **T75 (v2)**: `_parse_skip_records("")`（空）→ `frozenset()`
- **T76 (v2)**: `_parse_skip_records("  ")`（空白のみ）→ `frozenset()`

### 6.2c resume / progress.json（`test_progress.py`）

- **T77 (v2)**: skip_records 変更後に `--resume` → `ValueError` で停止
- **T78 (v2)**: skip_records 同一なら `--resume` 成功
- **T79 (v2)**: v0.1 形式の progress.json（fingerprint 無し = `""`）+ `--no-skip-default-records`（空 set = `""`）→ resume 成功
- **T80 (v2)**: v0.1 形式の progress.json（fingerprint 無し = `""`）+ デフォルト動作（`DEFAULT_SKIP_RECORDS` = SHA256(...)）→ `ValueError` で停止（安全側）
- **T81 (v3)**: `compute_skip_records_fingerprint(frozenset())` → `""`（空集合の特例）
- **T81b (v3)**: `compute_skip_records_fingerprint(frozenset({"HDPT:FULL"}))` → SHA256("HDPT:FULL") の hex（ソート済み canonical）
- **T82 (v3, CLI)**: CLI レベルで skip_records を変更して `--resume` → `_apply_existing` 呼出前に `ValueError` で exit code 2 で停止（T77 は ProgressWriter 単体レベル・T82 は CLI 統合レベル）
- **T83 (v3)**: v0.2 で新規書き込みした progress.json に `skip_records_fingerprint` フィールドが含まれること（Codex レビュー#3 の test gap 対応）

### 6.3 XML I/O 結合（`test_xml_io.py`）

- **T68**: skip されたエントリの `<Dest>` が `original_dest` を保持する（上書きされない）

### 6.4 フィクスチャ追加

- `tests/fixtures/skip_records.xml`: HDPT:FULL / MGEF:FULL / WEAP:FULL 等、複数 REC 型を含む小XML

### 6.5 実行コマンド

```
uv run pytest --tb=short -q
uv run ruff check iroiro/ tests/
uv run mypy iroiro
uv run iroiro translate sample/JobsofSkyrim_english_japanese.xml --dry-run
  # 「スキップ（REC 型）」が表示されることを確認
```

## 7. Work Packages

normal だが、v0.1 ほど複雑でない。テスト先行を尊重して2分割:

### WP-1-tests

- Goal: **T56-T82** のテストとフィクスチャを追加（v3: T77-T82 追加で test_progress.py を含む）
- Owner: implementer
- Allowed: `tests/**`（`tests/test_progress.py` を含む）
- Forbidden: `iroiro/**`, `pyproject.toml`, `README.md`, `docs/**`
- Inputs: 本計画書、§5 のシグネチャ
- Outputs:
  - `tests/test_translator.py`（拡張）— T56-T63, T71-T76, T81/T81b
  - `tests/test_cli.py`（拡張）— T64-T67, T69-T70, T82
  - `tests/test_progress.py`（拡張）— T77-T80
  - `tests/test_xml_io.py`（拡張）— T68
  - `tests/fixtures/skip_records.xml` — 複数 REC 型を含む小XML
- Risk: low

### WP-2-impl-and-docs

- Goal: 実装 + ドキュメント更新
- Owner: implementer
- Allowed:
  - `iroiro/translator.py`（`is_translation_needed` 拡張、`DEFAULT_SKIP_RECORDS`、`_parse_skip_records`）
  - `iroiro/cli.py`（新フラグ2つ、dry-run 拡張、`skip_records` 適用）
  - `iroiro/models.py`（`StringEntry.skip_reason` 追加）
  - `iroiro/config.py`（`RunConfig.skip_records`）
  - **`iroiro/progress.py`（v3: `ProgressData.skip_records_fingerprint`、`ProgressWriter` へ fingerprint 渡し、`compute_skip_records_fingerprint` 関数、`load_existing` での fingerprint 検証）**
  - `README.md`（「スキップ REC 型」への軽い言及・docs/usage.md へ誘導）
  - `docs/usage.md`（CLI フラグ表更新）
  - `docs/design.md`（「スキップ REC 型」セクション追加）
  - `docs/notes/translate-skip-records.md`（close マーク）
  - `docs/handoff/002-skip-records.md`（新規・引き継ぎ）
- Forbidden: `tests/**`, `docs/plans/**`
- Inputs: 本計画書、WP-1 のテスト契約
- Risk: medium（`is_translation_needed` の signature 変更・`ProgressWriter` のコンストラクタ変更が既存テストに影響しないか確認必要）

### 段取り

1. 計画承認 → Codex CLI プランレビュー（1回）
2. WP-1 tests
3. WP-2 impl + docs
4. PM 統合検査: 全テスト green、dry-run で件数確認
5. Codex CLI 最終 diff レビュー（1回）
6. QA レビュー（1回）
7. handoff 更新 + commit & push

## 8. 主要リスクと対策

| リスク | 影響 | 対策 |
|---|---|---|
| `is_translation_needed` の signature 変更で既存テストが壊れる | 中 | `rec=""` デフォルト・`skip_records=None` デフォルトで後方互換性確保 |
| デフォルト動作変更で v0.1 ユーザーの出力が変わる | 中 | README と handoff で明記・`--no-skip-default-records` で v0.1 動作を再現可能 |
| `MGEF:FULL` / `RACE:FULL` を翻訳したいユーザーが困る | 中 | ドキュメントで明記・`--no-skip-default-records` + `--skip-records` で細かく制御可能 |
| progress.json を使い回して翻訳結果が一貫しない | 中 | **skip_records_fingerprint を保存し、不一致は ValueError で停止**（v2）。input_hash と同じパターン |
| skip_reason フィールド追加で StringEntry が肥大化 | 低 | `str \| None = None` で既存コードへの影響最小 |

## 9. ドキュメント更新

- **README.md**: 主な機能に「内部管理用 REC 型のスキップ」を1行追加。詳細は docs/usage.md へ誘導
- **docs/usage.md**:
  - CLI フラグ表に `--no-skip-default-records` と `--skip-records` を追加
  - 「翻訳スキップ REC 型」セクションを新設（デフォルトリスト12件 + 制御方法）
  - **ユースケース例（v2）**:
    - `MGEF:FULL` と `RACE:FULL` だけ翻訳したい（他はデフォルトスキップ）:
      `--no-skip-default-records --skip-records "HDPT:FULL,FURN:FULL,CLAS:FULL,DOOR:FULL,FACT:FULL,CLFM:FULL,TREE:FULL,EXPL:FULL,HAZD:FULL,BPTD:BPTN"`
      ※ MGEF/RACE 以外の10件を再指定する必要がある
    - または `--no-skip-default-records` 単独で**全 REC 型を翻訳**（v0.1 互換動作）
- **docs/design.md**: 「翻訳スキップ REC 型」セクションを新設
  - デフォルトリストとその根拠
  - `MGEF:FULL` / `RACE:FULL` の取り扱い注意
  - `is_translation_needed` の拡張設計
- **docs/notes/translate-skip-records.md**: 冒頭に「✅ v0.2 で実装済み」マークを追加
- **docs/handoff/002-skip-records.md**: 新規作成（完了時）

## 10. レビューゲート（normal）

- [x] ユーザーとブレスト合意
- [x] docs/plans/002-skip-records.md 作成
- [x] Codex CLI: プランレビュー v1 → **reject** → v2 で修正（progress.json fingerprint 追加等）
- [x] Codex CLI: プランレビュー v2 → **reject** → v3 で修正（空集合 fingerprint 特例・WP スコープ拡張）
- [x] Codex CLI: プランレビュー v3 → **approve-with-notes**（T83 追加・API shape 明確化で対応）
- [ ] WP-1 tests ← イマ
- [ ] WP-1 tests
- [ ] WP-2 impl + docs
- [ ] テスト全件実行
- [ ] PM combined diff 検査
- [ ] Codex CLI: 最終 diff レビュー
- [ ] QA 最終レビュー
- [ ] handoff + Final report

## 11. 言語ポリシー

- ドキュメント・コメント・説明文は **日本語**
- 技術識別子・CLI フラグ・XML タグ等は **英語のまま**

## 12. v0.1 からの流用

- WP-1 → WP-2 の直列パターン（v0.1 で上手くいった）
- `is_translation_needed` の signature 拡張は後方互換性を保つ（v0.1 の教訓：signature 変更はテスト契約を壊す）
- Codex レビューを1回プラン・1回最終（v0.1 の6回より少ない想定・機能が単純なため）
- handoff は docs/handoff/002-skip-records.md を新規作成（v0.1 の AGENTS.md ルール通り）
