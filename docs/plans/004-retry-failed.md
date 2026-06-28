# 004 — `--retry-failed` フラグ + `iroiro.toml` の `retry_failed` 設定

## ステータス

- バージョン: v0.4
- リスク分類: **normal**（新機能・複数ファイル影響・後方互換性あり）
- 日付: 2026-06-28
- 依頼者要望:
  - 「retry failed はほしい。LLM の応答エラーの場合もあるので頻度が高い」
  - 「toml でも切り替えできると嬉しい」

## 1. 目標

`--resume` 時に `state=failed` のエントリを **再翻訳対象に戻す** ことができるようにする。
以下の3経路で制御可能:

1. **CLI フラグ**: `--retry-failed` / `--no-retry-failed`
2. **`iroiro.toml`**: `retry_failed = true` / `false`
3. **内蔵デフォルト**: `False`（後方互換・v0.3 までと同じ挙動）

## 2. 背景

### 2.1 v0.1 からの設計

`iroiro/progress.py` L29 / L123-124 に明記:

> failed: 失敗した index のリスト（**再試行せず保持**）
> Plan §5.8: resume 時の failed index は再試行しない

つまり v0.1 では「token mismatch などの決定論的エラーなら再試行しても同じ結果」という前提で **failed を確定扱い** していた。

### 2.2 前提が外れた実運用ケース

実運用で以下のような **一時的エラー** が頻発することが判明:

- **llama.cpp の `--ctx-size` 不足** → 長文入力で生成余地が無く LLM が空応答（今回のユーザー報告: `BOOK:DESC` の token mismatch）
- **LLM の一時的な応答エラー**（ネットワーク・モデルの揺らぎ等）

これらは **環境を変えれば通る可能性が高い** が、現状では failed に確定してしまい再試行できない。
ユーザーは progress.json の手動編集（§3 参照）で回避せざるを得ない状況。

### 2.3 ユーザーの希望

「llama.cpp の `--ctx-size` を大きくして再実行」する前に、failed を一括で再試行対象に戻したい。
**toml で `retry_failed = true` と書いておけば毎回 `--retry-failed` を打たなくて済む** のも嬉しい。

## 3. 現状

### 3.1 設定 dataclass

`iroiro/config.py` の `RunConfig`（L17-38）:

```python
@dataclass(slots=True)
class RunConfig:
    input_path: Path
    output_path: Path
    api: ApiConfig
    resume: bool
    dry_run: bool
    verbose: bool
    skip_records: frozenset[str]
```

→ ここに `retry_failed: bool` を追加する（**`ApiConfig` ではなく `RunConfig`** に置く理由: LLM 呼出パラメータではなく実行制御フラグだから）。

### 3.2 `_apply_existing()` の現状

`iroiro/cli.py` L354-368:

```python
def _apply_existing(entries: list[StringEntry], existing: ProgressData) -> None:
    for entry in entries:
        if entry.index in existing.entries:
            entry.new_dest = existing.entries[entry.index]
            entry.state = "translated"
        elif entry.index in existing.failed:
            entry.new_dest = entry.original_dest
            entry.state = "failed"  # ← 常に failed 確定
```

→ `retry_failed: bool` 引数を追加し、`True` の場合は failed の entry を `state="pending"` のままにする。

### 3.3 `mark_failed()` の現状

`iroiro/progress.py` L120-129:

```python
async def mark_failed(self, index: int) -> None:
    async with self._lock:
        failed = self._data["failed"]
        assert isinstance(failed, list)
        failed.append(index)  # ← 重複チェック無し
```

→ `--retry-failed` で再試行してまた失敗した場合、**同じ index が2回 append される** 問題がある。重複チェックを追加する。

## 4. 設計方針

### 4.1 設定の置き場所と優先順位

```
強 ← CLI フラグ（--retry-failed / --no-retry-failed）  ＞  iroiro.toml  ＞  内蔵デフォルト（False）  → 弱
```

v0.3 と同じ `_resolve()` helper パターンで解決。

### 4.2 `RunConfig` への追加

```python
@dataclass(slots=True)
class RunConfig:
    ...
    retry_failed: bool  # ← 追加・デフォルト False（後方互換）
```

### 4.3 CLI フラグ

```python
retry_failed: bool | None = typer.Option(
    None,
    "--retry-failed/--no-retry-failed",
    help=(
        "resume 時に failed エントリを再翻訳対象に戻す（未指定時は iroiro.toml → 内蔵デフォルト False）"
    ),
)
```

Typer の `--flag/--no-flag` 構文で `True` / `False` / `None`（未指定）を区別可能。

### 4.4 `iroiro.toml` のスキーマ拡張

```toml
[iroiro]
# 既存6項目に加え:
retry_failed = false   # resume 時に failed を再試行するか（v0.4 追加）
```

`load_config()` の `_VALIDATORS` dict に `retry_failed` を追加:

```python
def _validate_bool(v: object, key: str, path: Path) -> bool:
    if not isinstance(v, bool):
        raise IroiroError(f"{key} must be bool, got {type(v).__name__} in {path}")
    return v

_VALIDATORS: dict[str, Callable[[object, str, Path], object]] = {
    "api_base": _validate_str_nonempty,
    "api_key": _validate_str_allow_empty,
    "model": _validate_str_nonempty,
    "timeout": _validate_number_positive,
    "concurrency": _validate_concurrency,
    "max_chars": _validate_max_chars,
    "retry_failed": _validate_bool,  # ← 追加
}
```

### 4.5 `_apply_existing()` の拡張

```python
def _apply_existing(
    entries: list[StringEntry],
    existing: ProgressData,
    retry_failed: bool = False,  # ← 追加・デフォルトで後方互換
) -> None:
    """load_existing の結果を entries に反映する。

    retry_failed=False（デフォルト）: failed はそのまま state=failed で保持。
    retry_failed=True: failed の index を state=pending に戻す（再翻訳対象）。
        new_dest は original_dest のまま（前回の失敗時と同じ）。
    """
    for entry in entries:
        if entry.index in existing.entries:
            # 翻訳済（最優先・retry_failed に関わらず確定）
            entry.new_dest = existing.entries[entry.index]
            entry.state = "translated"
        elif entry.index in existing.failed:
            if retry_failed:
                # 再試行対象: pending のまま（new_dest は original_dest）
                entry.state = "pending"
            else:
                # 従来動作: failed 確定
                entry.new_dest = entry.original_dest
                entry.state = "failed"
        # else: 未処理・state=pending のまま
```

### 4.6 `mark_failed()` の重複チェック + `mark_done()` の failed クリア

**不変性（v0.4 で明文化）**: ある index は **同時に `entries` と `failed` に存在しない**。
これを保証するため、両メソッドを拡張:

```python
# iroiro/progress.py

async def mark_failed(self, index: int) -> None:
    async with self._lock:
        failed = self._data["failed"]
        assert isinstance(failed, list)
        if index not in failed:  # ← 重複チェック追加（v0.4）
            failed.append(index)

async def mark_done(self, index: int, translated: str) -> None:
    async with self._lock:
        # 既存: entries[index] = translated
        # 追加（v0.4）: failed に同じ index があれば削除
        entries = self._data["entries"]
        assert isinstance(entries, dict)
        entries[str(index)] = translated
        failed = self._data["failed"]
        assert isinstance(failed, list)
        if index in failed:  # ← retry 成功時にクリア
            failed.remove(index)
```

**理由**: 
- `mark_failed()` 重複チェック: `retry_failed=True` で再試行 → また失敗 のループで same index が重複 append されるのを防止。
- `mark_done()` の failed クリア: retry 成功時に entries と failed が両方持つ不整合を防止。「Resuming: X translated, Y failed」メッセージと progress.json の一貫性を維持。

### 4.7 出力XMLでの `<Dest>` 扱い

retry_failed=True で pending に戻った entry は **翻訳が終わるまで `original_dest`** を保持する。
これは v0.2.1 までと同じ挙動（失敗時は `<Source>` で上書きしない・§5.6.3「`<Dest>` 保護」）。
翻訳が成功すれば `new_dest` に訳文が入り、出力XMLの `<Dest>` に反映される。
再失敗時は `original_dest` が保持され、`state=failed` に戻る。

## 5. スコープ

### 5.1 含む

- `RunConfig` に `retry_failed: bool` 追加
- `--retry-failed` / `--no-retry-failed` CLI フラグ
- `iroiro.toml` の `retry_failed` キー（bool 型）
- `_apply_existing()` の `retry_failed` 引数と pending 戻しロジック
- `mark_failed()` の重複チェック
- `iroiro.toml.example` に `retry_failed` 行追加（コメントアウト）
- テスト（unit + CLI 統合）
- ドキュメント更新（usage.md / design.md / development.md / README.md / AGENTS.md / handoff）

### 5.2 含まない（Non-goals）

- **`max_tokens` 設定**: v0.5 以降（ユーザーの別案件・今回のスコープ外）
- **選択的リトライ**（特定 index だけ再試行）: 今回は全 failed 一括のみ
- **リトライ回数制限**（N 回失敗したら諦める等）: 今回は無制限・毎回 `--retry-failed` を指定すれば再試行
- **自動 retry_failed**: デフォルトは `False` のまま（明示的な opt-in）
- **failed エントリの手動編集 UI**: 引き続き progress.json の手動編集は可能だが、本機能で代替可能

## 6. テスト戦略

### 6.1 ローダーのユニットテスト（`tests/test_config.py` に追記）

| ID | 内容 |
|---|---|
| T110 | `retry_failed = true` → `{"retry_failed": True}` を返す |
| T111 | `retry_failed = false` → `{"retry_failed": False}` を返す |
| T112 | `retry_failed = "true"`（文字列） → `IroiroError` |
| T113 | `retry_failed = 1`（int） → `IroiroError`（Python `bool ⊂ int` だが厳格 bool のみ許可） |

### 6.2 `_apply_existing()` のユニットテスト（`tests/test_cli.py` に追記）

| ID | 内容 |
|---|---|
| T114 | `retry_failed=False`（デフォルト）: failed index → `state=failed`, `new_dest=original_dest`（従来動作・回帰保証） |
| T115 | `retry_failed=True`: failed index → `state=pending`, `new_dest=original_dest`（再試行対象） |
| T116 | `retry_failed=True`: translated index → `state=translated`（retry_failed に関わらず確定） |
| T117 | `retry_failed=True`: 未処理 index → `state=pending`（変化なし） |

### 6.3 `mark_failed()` / `mark_done()` 重複・クリアチェック（`tests/test_progress.py` に追記）

| ID | 内容 |
|---|---|
| T118 | 同じ index を2回 `mark_failed` → failed リストは1個だけ（重複排除） |
| T119 | 異なる index を2回 → 2個（正常系） |
| T120 | `mark_done(index, translated)` の後・その index が failed に無い → 追加なし（既存の挙動・回帰保証） |
| T121 | `mark_done(index, translated)` の後・その index が failed に有った → failed から削除される（v0.4 新機能） |
| T122 | 既存 T23 で「duplicate 可能」のコメントがあれば更新（v0.4 で重複排除されたため） |

### 6.4 CLI 統合テスト（`tests/test_cli.py` に追記）

`CliRunner` + `monkeypatch` + MockTranslator で:

| ID | 内容 |
|---|---|
| T123 | progress.json に `failed=[1]`・CLI `--resume` のみ（retry_failed 無指定）→ entry 1 は再翻訳されない（v0.3 互換） |
| T124 | progress.json に `failed=[1]`・CLI `--resume --retry-failed` → entry 1 が再翻訳される |
| T125 | progress.json に `failed=[1]`・CLI `--resume --retry-failed`・mock が成功 → **resulting progress.json から `1` が削除され、entries["1"] に訳文が入る**（不変性検証） |
| T126 | progress.json に `failed=[1]`・`iroiro.toml` に `retry_failed=true`・CLI `--resume`（フラグ無指定）→ entry 1 が再翻訳される（toml から読込） |
| T127 | progress.json に `failed=[1]`・`iroiro.toml` に `retry_failed=true`・CLI `--resume --no-retry-failed` → entry 1 は再翻訳されない（CLI フラグが toml より優先） |
| T128 | Typer `bool | None = None` の3状態区別をヘルプ出力で確認（`--retry-failed` / 省略 / `--no-retry-failed` が全て認識される） |
| T129 | `--retry-failed` 単独（`--resume` 無し）→ 警告ログが出て通常実行継続（exit 0） |

T129 の挙動は設計判断: **警告ログを出して通常実行**（`--resume` 無しの retry_failed は無意味だが exit 2 にする程ではない）。

### 6.5 既存テストの後方互換性

`uv run pytest` 全件 green を保証。特に:
- T36-T40, T64-T67, T69-T70, T82, T103-T109（既存 CLI テスト）は `retry_failed` がデフォルト False なので影響を受けないはず。
- T23（`test_progress.py`）は「duplicate 可能」コメントを v0.4 の重複排除仕様に更新（挙動は単発呼出なので変わらず green）。

## 7. 実装計画（Work Package）

### 7.1 WP 構成

| WP | Goal | Files | 並列可 |
|---|---|---|---|
| WP-1 | テスト先行 | `tests/test_config.py`（追記）, `tests/test_cli.py`（追記）, `tests/test_progress.py`（追記） | 〇 |
| WP-2 | コア実装 | `iroiro/config.py`, `iroiro/cli.py`, `iroiro/progress.py`, `iroiro.toml.example` | × |
| WP-3 | docs + handoff | `docs/usage.md`, `docs/design.md`, `docs/development.md`, `README.md`, `AGENTS.md`, `docs/handoff/004-retry-failed.md`（新規） | 〇（草案は並行・最終は WP-2 後） |

### 7.2 WP-1: テスト先行

**Allowed paths**: `tests/test_config.py`, `tests/test_cli.py`, `tests/test_progress.py`
**Forbidden paths**: `iroiro/`, `pyproject.toml`, `.gitignore`, `iroiro.toml.example`, `docs/`, `README.md`, `AGENTS.md`

**契約**（WP-2 が実装する側）:

```python
# iroiro/config.py の RunConfig
@dataclass(slots=True)
class RunConfig:
    ...
    retry_failed: bool  # 追加・デフォルト False

# iroiro/cli.py の _apply_existing
def _apply_existing(
    entries: list[StringEntry],
    existing: ProgressData,
    retry_failed: bool = False,
) -> None: ...

# iroiro/progress.py の mark_failed
async def mark_failed(self, index: int) -> None:
    # 重複チェック追加（index in failed なら append しない）
```

### 7.3 WP-2: コア実装

**Allowed paths**: `iroiro/config.py`, `iroiro/cli.py`, `iroiro/progress.py`, `iroiro.toml.example`
**Forbidden paths**: `tests/`, `pyproject.toml`, `docs/`, `README.md`, `AGENTS.md`

実装内容:

1. `iroiro/config.py`:
   - `RunConfig` に `retry_failed: bool = False` 追加
   - `_validate_bool()` 関数を追加（`isinstance(v, bool)` 厳格）
   - `_VALIDATORS` dict に `"retry_failed": _validate_bool` 追加
2. `iroiro/cli.py`:
   - `translate()` に `--retry-failed/--no-retry-failed` フラグ追加（`bool | None = None`）
   - `_resolve()` でマージ（`_resolve(retry_failed, file_cfg, "retry_failed", False)`）
   - `RunConfig` 構築時に `retry_failed` を渡す
   - `_apply_existing()` の呼出で `retry_failed=cfg.retry_failed` を渡す
   - `_apply_existing()` 本体の拡張（§4.5）
   - `--retry-failed` 単独（`--resume` 無し）の警告ログ
3. `iroiro/progress.py`:
   - `mark_failed()` に重複チェック追加（§4.6）
4. `iroiro.toml.example`:
   - `[iroiro]` セクションに `# retry_failed = false` 行を追記

### 7.4 WP-3: docs + handoff

**Allowed paths**: `docs/usage.md`, `docs/design.md`, `docs/development.md`, `README.md`, `AGENTS.md`, `docs/handoff/004-retry-failed.md`
**Forbidden paths**: `iroiro/`, `tests/`, `pyproject.toml`, `iroiro.toml.example`

更新内容:

- **`docs/usage.md`**: 
  - 「CLI フラグ一覧」節に `--retry-failed` / `--no-retry-failed` を追加
  - 「設定ファイル」節の各項目表に `retry_failed` を追加
  - 「再開（resume）」節に「failed を再試行する（v0.4）」サブ節を新設し、`--retry-failed` と `iroiro.toml` の両方を説明
- **`docs/design.md`**: 
  - 「`retry_failed` 設計判断（v0.4）」節を新設
  - なぜデフォルト False か（後方互換・確定エラーとの区別）
  - なぜ全 failed 一括か（選択的リトライはスコープ外）
  - なぜ `mark_failed` 重複チェックを入れたか
- **`docs/development.md`**: 
  - モジュール表に追記
  - テスト件数更新（144 + 15 = 159 件想定）
- **`README.md`**: 
  - 「主な機能」に v0.4 の1行追加
  - 必要ならクイックスタート節に「failed の再試行」を軽く言及（詳細は usage.md）
- **`AGENTS.md`**: 
  - クイックコマンド件数更新
  - 必要なら「触ってはいけないもの」等には追加なし（設定項目なので触ってよい）
- **`docs/handoff/004-retry-failed.md`**: 
  - 新規・標準テンプレ使用

## 8. ドキュメント影響

- README.md: 軽微（1行）
- docs/usage.md: 中規模（CLI フラグ節・設定ファイル節・resume 節）
- docs/design.md: 中規模（設計判断節）
- docs/development.md: 軽微（モジュール表・テスト件数）
- AGENTS.md: 軽微（件数更新）
- iroiro.toml.example: 軽微（1行追加）

言語ポリシー: 日本語（既存方針維持）。

## 9. 引き継ぎ影響

`docs/handoff/004-retry-failed.md` を新規作成。v0.3 の `iroiro.toml` 機能に加えて、v0.4 の `--retry-failed` 機能を記載。

## 10. 言語ポリシー影響

- `retry_failed` キー: snake_case（英語識別子）・既存方針維持
- `--retry-failed` / `--no-retry-failed` CLI フラグ: kebab-case（CLI 慣例）
- エラーメッセージ: 英語（`retry_failed must be bool, got ...` 等）
- ドキュメント・コメント・handoff: 日本語

## 11. リスク

### 11.1 後方互換性

- **リスク低**: デフォルト `False` で v0.3 までと完全同じ挙動。`--retry-failed` または toml の `retry_failed = true` を明示した場合のみ挙動が変わる。
- **回帰保証**: T114, T120 で明示的に保証。

### 11.2 既存テストの破壊

- **リスク低**: `_apply_existing()` の `retry_failed` 引数はデフォルト `False` なので、既存呼出（引数無し）は影響なし。
- `mark_failed()` の重複チェック追加も、既存テスト（単発呼出）には影響しない。

### 11.3 progress.json の failed リストが膨らむ可能性

- **リスク低**: 重複チェックを入れたので、同じ index は1回しか append されない。
- ただし `retry_failed=True` で何度も再試行を繰り返すと、**最終的に全失敗した場合** progress.json の `failed` には全失敗 index が残る。これは仕様通り（最終状態の記録）。

### 11.4 `--retry-failed` 単独（`--resume` 無し）の挙動

- **判断**: 警告ログを出して通常実行（exit 2 にしない）。
- 理由: progress.json が無ければ「failed を pending に戻す」対象も無い。ユーザーが `--resume` 忘れに気づけるよう WARNING レベルで出力。
- T124 で検証。

### 11.5 `mark_failed()` の重複チェックと並行性

- `_lock` で保護されているので race condition なし。
- `if index not in failed` の線形探索は O(N) だが、failed リストは通常数十件程度なので実用上問題なし。数千件になったら set に持ち替える（将来課題）。

## 12. 受入基準

- [ ] `uv run pytest` 全件 green（既存144件 + 新規17件 = 161件想定・T23 は更新）。
- [ ] `uv run ruff check iroiro/ tests/` クリーン。
- [ ] `uv run mypy iroiro` クリーン。
- [ ] `uv run iroiro translate --help` に `--retry-failed` フラグが表示される。
- [ ] `iroiro.toml.example` に `# retry_failed = false` 行が含まれる。
- [ ] `iroiro.toml` に `retry_failed = true` と書いて `--resume` した時、failed エントリが再翻訳されることを手動確認。
- [ ] `--no-retry-failed` が toml の `retry_failed = true` より優先されることを手動確認。
- [ ] Codex CLI 最終 diff レビュー: approve または approve-with-notes。
- [ ] QA レビュー: pass または pass-with-notes。

## 13. レビューゲート（normal）

- [x] ユーザーと本計画 v0.4 の合意
- [ ] Codex CLI: プランレビュー v0.4
- [ ] （必要なら）改訂
- [ ] WP-1 実装（テスト）
- [ ] WP-2 実装（`iroiro/` 本体・`iroiro.toml.example`）
- [ ] WP-3 実装（docs・handoff）
- [ ] テスト全件実行
- [ ] PM combined diff 検査
- [ ] Codex CLI: 最終 diff レビュー
- [ ] QA 最終レビュー
- [ ] Final report

## 14. 代替案と却下理由

- **`--retry-failed` のみ（toml 非対応）**: ユーザー要望で toml 対応も要求されたため却下。
- **選択的リトライ（`--retry-failed 1,5,10`）**: スコープ膨張。全 failed 一括で十分（必要なら progress.json 手動編集）。将来必要なら `--retry-failed-only INDEX` 等で拡張可能。
- **自動 retry_failed（デフォルト True）**: 後方互換性破壊・確定エラー（token mismatch 等）を無駄に再試行するコスト。明示 opt-in が適切。
- **リトライ回数制限**: 複雑性増・progress.json に retry_count を持たせる必要あり。今回は無制限。
- **failed の自動クリア（retry_failed=True 時に progress.json から削除）**: 一度却下していたが、**v0.4 で採用**（Codex レビュー指摘）。但し retry_failed=True 時の一括削除ではなく、`mark_done()` で **retry 成功時に限り** その index を failed から削除（不変性: entries ∩ failed = ∅）。これにより progress.json と「Resuming: X translated, Y failed」メッセージが常に整合する。

## 15. GaOTTT memory writeback（計画確定後）

計画が Codex approve されたら以下を保存:

- v0.4 設計判断: retry_failed デフォルト False（後方互換・確定エラーとの区別）
- 優先順位: CLI フラグ（`--retry-failed` / `--no-retry-failed`）＞ iroiro.toml ＞ 内蔵デフォルト False
- `_apply_existing()` の `retry_failed` 引数（デフォルト False で既存呼出に影響なし）
- `mark_failed()` 重複チェック（同じ index が複数回 append されるのを防止）
