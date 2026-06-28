# 引き継ぎメモ: iroiro-translator v0.4 failed エントリ再試行 (004-retry-failed)

- 作成日: 2026-06-28
- 計画書: [`docs/plans/004-retry-failed.md`](../plans/004-retry-failed.md)
- 状態: **done-with-notes**

---

## ステータス

| 項目 | 値 |
|---|---|
| 状態 | done-with-notes |
| 日付 | 2026-06-28 |
| 担当 | PM + implementer（WP-1 テスト / WP-2 実装 / WP-3 ドキュメント） |
| 概要 | v0.4「`failed` エントリの再試行」機能を実装。`--resume` 時に `failed` エントリを再翻訳対象に戻す `--retry-failed` / `--no-retry-failed` CLI フラグと `iroiro.toml` の `retry_failed` 設定を追加した。優先順位は **CLI フラグ（明示指定時）＞ `iroiro.toml` ＞ 内蔵デフォルト `False`**（後方互換・v0.3 までと同じ挙動）。`ProgressWriter.mark_done` で retry 成功時に `failed` から index を削除（不変性 `entries ∩ failed = ∅` を保証）・`mark_failed` に重複チェックを追加。163件のテストが全て green。 |

---

## 変更内容

v0.4 は **後方互換** の新機能。`--retry-failed` を使わなければ v0.3 と完全に同じ挙動。

### 機能サマリ

1. **CLI フラグ**: `--retry-failed` / `--no-retry-failed`（`bool | None = None` で3状態を区別）
2. **`iroiro.toml`**: `[iroiro]` テーブルに `retry_failed = true` / `false`（厳格 bool・`1` / `0` / `"true"` は拒否）
3. **優先順位**: CLI フラグ ＞ `iroiro.toml` ＞ 内蔵デフォルト `False`
4. **`_apply_existing()` 拡張**: `retry_failed=True` の場合、`failed` index を `state=pending` に戻す（`new_dest` は触らない・`original_dest` を保持）
5. **`mark_done()` 拡張**: retry 成功時に `failed` から同 index を削除（不変性 `entries ∩ failed = ∅`）
6. **`mark_failed()` 拡張**: 重複チェックを追加（retry ループで同じ index が複数回 append されるのを防止）
7. **`--retry-failed` 単独（`--resume` 無し）**: WARNING ログを出して通常実行（exit 2 にしない）

### 修正（実装コード・WP-2）

| ファイル | 変更内容 |
|---|---|
| `iroiro/config.py` | `RunConfig` に `retry_failed: bool` フィールド追加。`_validate_bool(v, key, path)` validator 追加（厳格 bool・`isinstance(v, bool)` のみ許可・`1` / `0` / `"true"` は `IroiroError`）。`_VALIDATORS` dict に `"retry_failed": _validate_bool` を追加 |
| `iroiro/cli.py` | `translate()` に `retry_failed: bool \| None = typer.Option(None, "--retry-failed/--no-retry-failed", ...)` を追加。`_resolve(retry_failed, file_cfg, "retry_failed", False)` でマージ。`RunConfig` 構築時に `retry_failed=retry_failed_resolved` を渡す。`_apply_existing()` に `retry_failed: bool = False` 引数を追加し、`True` の場合は `failed` index を `state=pending` のままにする（`new_dest` を触らない）。`_run()` の先頭で `retry_failed and not resume` の場合に WARNING ログを出力 |
| `iroiro/progress.py` | `mark_done()`: `failed` に同 index があれば削除（不変性保証・v0.4）。`mark_failed()`: `if index not in failed` の重複チェックを追加（v0.4）。docstring に v0.4 の変更内容と不変性を明記 |
| `iroiro.toml.example` | `[iroiro]` セクションに `# retry_failed  = false` 行を追記（コメントアウト・v0.4 追加の注記付き） |

### 修正（テスト・WP-1）

| ファイル | 変更内容 |
|---|---|
| `tests/test_config.py` | T110-T113（4件）を追加。`retry_failed = true` / `false` の受理・`"true"`（文字列）・`1`（int）の拒否を検証 |
| `tests/test_progress.py` | T118-T121（4件）を追加。`mark_failed` 重複チェック（同 index 2回 → 1個）・`mark_done` 後の failed クリア（在/不在両方）を検証。T23 の docstring / コメントを v0.4 の重複排除仕様に更新（assert 自体は維持・単発呼出の挙動は不変） |
| `tests/test_cli.py` | T114-T117（4件・`_apply_existing` ユニットテスト）+ T123-T129（7件・CLI 統合テスト）を追加。`_apply_existing` の retry_failed 分岐・`--resume --retry-failed` で再翻訳・retry 成功時の progress.json 不変性・`iroiro.toml` の `retry_failed=true` 反映・`--no-retry-failed` の toml 上書き・`--help` の3状態表示・`--retry-failed` 単独の WARNING を検証 |
| `tests/fixtures/iroiro_retry_true.toml` | 新規。`retry_failed = true` のみ記述（T110 / T126 用） |
| `tests/fixtures/iroiro_retry_false.toml` | 新規。`retry_failed = false` のみ記述（T111 / T127 用） |

### 修正（ドキュメント・WP-3）

| ファイル | 変更内容 |
|---|---|
| `docs/usage.md` | CLI フラグ表に `--retry-failed` / `--no-retry-failed` 行を追加・解決順序の注記に v0.4 を含める・設定ファイル節の書き方サンプルと各項目表に `retry_failed` を追加・「再開」節に「failed の再試行（v0.4）」サブ節を新設（使い方・優先順位・`--retry-failed` 単独の挙動・不変性・使用シナリオ・`<Dest>` 扱い） |
| `docs/design.md` | 「retry_failed 設計判断（v0.4）」節を新設（デフォルト False の理由・全 failed 一括の理由・`mark_done` で failed クリアする理由・`mark_failed` 重複チェックの理由・`RunConfig` に置いた理由・`bool \| None = None` パターンの理由・`_validate_bool` 厳格 bool の理由・`--retry-failed` 単独を exit 2 にしない理由） |
| `docs/development.md` | テスト件数（163件）・モジュール構成ツリーの `cli.py` / `config.py` / `progress.py` キャプション更新・テストファイル表に v0.4 追加分（T110-T113 / T114-T117 / T118-T121 / T123-T129）を明記・フィクスチャ一覧に `iroiro_retry_true` / `iroiro_retry_false` を追加・ロードマップに v0.4 完了 / v0.5 以降を更新 |
| `README.md` | 「主な機能」に v0.4 failed エントリ再試行の1行を追加・「よく使うフラグ」に `--resume --retry-failed` を追加・ドキュメントリンクに v0.4 計画・引き継ぎを追加 |
| `AGENTS.md` | クイックコマンドのテスト件数（163件）・参考ドキュメントに v0.4 計画・引き継ぎを追加 |
| `docs/handoff/004-retry-failed.md` | 本ファイル（新規） |

---

## 変更理由

v0.1 から「`failed` エントリは再試行せず確定扱い」としていたが、実運用で以下のような **一時的エラー** が
頻発することが判明した:

- **llama.cpp の `--ctx-size` 不足** → 長文入力で生成余地が無く LLM が空応答（ユーザー報告: `BOOK:DESC` の token mismatch）
- **LLM の一時的な応答エラー**（ネットワーク・モデルの揮らぎ等）

これらは **環境を変えれば通る可能性が高い** が、現状では `failed` に確定してしまい再試行できない。
ユーザーは `progress.json` の手動編集で回避せざるを得ない状況だった（計画書 §2.2 / §2.3）。

v0.4 では:

1. **明示的な再試行手段の提供**: `--retry-failed` で `failed` エントリを再翻訳対象に戻す
2. **`iroiro.toml` でデフォルト化**: `retry_failed = true` と書けば毎回フラグを打たなくて済む
3. **後方互換**: デフォルト `False` で v0.3 までと同じ挙動。既存ユーザーへの影響ゼロ
4. **不変性保証**: `entries ∩ failed = ∅` を `mark_done` で保証し、progress.json と「Resuming」メッセージの整合性を維持

計画書 §1（目標）・§2（背景）のユーザー確定事項に従い実装。詳細な設計判断・却下代替案は計画書 §14 を参照。

---

## Work packages

### WP-1-tests

| 項目 | 値 |
|---|---|
| Scope | T110-T113（`retry_failed` validator）+ T114-T117（`_apply_existing` ユニット）+ T118-T121（`mark_failed` / `mark_done` 重複・クリア）+ T123-T129（CLI 統合）+ T23 docstring 更新 + TOML フィクスチャ2種 |
| Status | done |
| Files | `tests/test_config.py`（T110-T113 追記）, `tests/test_progress.py`（T118-T121 追記・T23 docstring 更新）, `tests/test_cli.py`（T114-T117 + T123-T129 追記）, `tests/fixtures/iroiro_retry_true.toml`（新規）, `tests/fixtures/iroiro_retry_false.toml`（新規） |
| Verification | WP-2 完了後に `uv run pytest` で全 green（163/163）。ruff クリーン |
| Remaining risks | low。実 LLM は使わず `httpx.MockTransport` と単体テストで論理網羅 |

### WP-2-impl

| 項目 | 値 |
|---|---|
| Scope | `RunConfig.retry_failed` + `_validate_bool` + CLI `--retry-failed` / `--no-retry-failed` + `_apply_existing` 拡張 + `mark_failed` 重複チェック + `mark_done` failed クリア + `iroiro.toml.example` 1行追加 |
| Status | done |
| Files | `iroiro/config.py`, `iroiro/cli.py`, `iroiro/progress.py`, `iroiro.toml.example` |
| Verification | `uv run pytest`（163/163 green）, `uv run ruff check iroiro/ tests/`（クリーン）, `uv run mypy iroiro`（クリーン）, `uv run iroiro translate --help` で `--retry-failed` / `--no-retry-failed` フラグ表示を確認 |
| Remaining risks | low。実 LLM E2E は未実施（単体テスト + CLI 統合テストで論理網羅・プロトコルは v0.1 で実機確認済み） |

### WP-3-docs

| 項目 | 値 |
|---|---|
| Scope | ドキュメント更新 + 引き継ぎメモ |
| Status | done |
| Files | `docs/usage.md`, `docs/design.md`, `docs/development.md`, `README.md`, `AGENTS.md`, `docs/handoff/004-retry-failed.md`（新規・本ファイル） |
| Verification | 計画書 §7.4 の更新内容を全て網羅。`uv run pytest` / ruff / mypy がクリーンであることを確認（docs 変更なので結果は不変・念のため確認） |
| Remaining risks | なし |

---

## 触ったファイル（全リスト・絶対パス）

### 実装コード（WP-2）

- `/mnt/holyland/Project/iroiro-translator/iroiro/config.py`（修正）
- `/mnt/holyland/Project/iroiro-translator/iroiro/cli.py`（修正）
- `/mnt/holyland/Project/iroiro-translator/iroiro/progress.py`（修正）

### 設定・運用（WP-2）

- `/mnt/holyland/Project/iroiro-translator/iroiro.toml.example`（修正・`retry_failed` 行追加）

### テスト（WP-1）

- `/mnt/holyland/Project/iroiro-translator/tests/test_config.py`（修正・T110-T113 追記）
- `/mnt/holyland/Project/iroiro-translator/tests/test_progress.py`（修正・T118-T121 追記・T23 docstring 更新）
- `/mnt/holyland/Project/iroiro-translator/tests/test_cli.py`（修正・T114-T117 + T123-T129 追記）
- `/mnt/holyland/Project/iroiro-translator/tests/fixtures/iroiro_retry_true.toml`（新規）
- `/mnt/holyland/Project/iroiro-translator/tests/fixtures/iroiro_retry_false.toml`（新規）

### ドキュメント（WP-3）

- `/mnt/holyland/Project/iroiro-translator/docs/usage.md`（修正）
- `/mnt/holyland/Project/iroiro-translator/docs/design.md`（修正）
- `/mnt/holyland/Project/iroiro-translator/docs/development.md`（修正）
- `/mnt/holyland/Project/iroiro-translator/README.md`（修正）
- `/mnt/holyland/Project/iroiro-translator/AGENTS.md`（修正）
- `/mnt/holyland/Project/iroiro-translator/docs/plans/004-retry-failed.md`（新規・PM 作成）
- `/mnt/holyland/Project/iroiro-translator/docs/handoff/004-retry-failed.md`（新規・本ファイル）

---

## テスト

### 実行したコマンド

```bash
uv run pytest --tb=short -q
uv run ruff check iroiro/ tests/
uv run mypy iroiro
uv run iroiro translate --help
```

### 結果

#### pytest

```
163 passed in 1.70s
```

ファイル別内訳:

| ファイル | 件数 | v0.3 からの差分 |
|---|---|---|
| `tests/test_xml_io.py` | 22 | — |
| `tests/test_escape.py` | 15 | — |
| `tests/test_translator.py` | 53 | — |
| `tests/test_progress.py` | 24 | +4（T118-T121） |
| `tests/test_config.py` | 19 | +4（T110-T113） |
| `tests/test_cli.py` | 30 | +11（T114-T117 + T123-T129） |
| **合計** | **163** | **+19** |

v0.4 追加分の詳細:

- **T110-T113**（`retry_failed` validator・`tests/test_config.py`）: 4件 green
  - `retry_failed = true` / `false` の受理（T110 / T111）
  - `"true"`（文字列）の拒否（T112）
  - `1`（int）の拒否・`bool ⊂ int` 事故防止（T113）
- **T114-T117**（`_apply_existing` ユニット・`tests/test_cli.py`）: 4件 green
  - `retry_failed=False`（デフォルト）→ `state=failed`・`new_dest=original_dest`（T114・回帰保証）
  - `retry_failed=True` → `state=pending`・`new_dest=None`（触らない・T115）
  - `retry_failed=True` でも translated は確定（T116）
  - `retry_failed=True` でも未処理 index は pending のまま（T117）
- **T118-T121**（`mark_failed` / `mark_done`・`tests/test_progress.py`）: 4件 green
  - 同 index 2回 `mark_failed` → 1個だけ（T118・重複排除）
  - 異なる index 2回 → 2個（T119・正常系）
  - `mark_done` 後・failed に無い → 追加なし（T120・回帰保証）
  - `mark_done` 後・failed に有った → 削除（T121・v0.4 新機能・不変性保証）
- **T123-T129**（CLI 統合・`tests/test_cli.py`）: 7件 green
  - `--resume` のみ → 再翻訳されない（T123・v0.3 互換）
  - `--resume --retry-failed` → 再翻訳される（T124）
  - retry 成功 → progress.json から削除・`entries["1"]` に訳文（T125・不変性検証・最重要）
  - `iroiro.toml` の `retry_failed=true` が `--resume` 時に反映（T126）
  - `--no-retry-failed` が toml の `retry_failed=true` より優先（T127）
  - `--help` に `--retry-failed` / `--no-retry-failed` が両方表示（T128・3状態区別）
  - `--retry-failed` 単独（`--resume` 無し）→ WARNING + exit 0（T129）

#### ruff / mypy

```
All checks passed!                       # ruff
Success: no issues found in 11 source files   # mypy
```

#### `--help` 確認

`uv run iroiro translate --help` に `--retry-failed` / `--no-retry-failed` フラグが表示されることを確認。
help テキストに「resume 時に failed エントリを再翻訳対象に戻す（未指定時は iroiro.toml → 内蔵デフォルト False）」
が含まれることを確認。

### 未実行

- 実 LLM（llama.cpp server / Gemma 4 12B）による E2E 翻訳検証
  - 理由: 本 WP は `failed` エントリの再試行ロジックが主体。`_apply_existing` の分岐・`mark_done` /
    `mark_failed` の不変性・優先順位マージ（`_resolve`）は単体テスト + CLI 統合テストで担保済み。
    実 LLM 呼び出し部分（`Translator`）は v0.1 で実機確認済みで v0.4 では無変更のため、再検証は次回実機時で十分

---

## ドキュメント

### 更新

- `docs/usage.md` — CLI フラグ表に `--retry-failed` / `--no-retry-failed` 追加・解決順序の注記に v0.4 を含める・設定項目表に `retry_failed` 追加・「再開」節に「failed の再試行（v0.4）」サブ節新設
- `docs/design.md` — 「retry_failed 設計判断（v0.4）」節新設（8つの設計判断を解説）
- `docs/development.md` — テスト件数（163件）・モジュール構成ツリー・テストファイル表・フィクスチャ一覧・ロードマップ更新
- `README.md` — 「主な機能」に1行追加・「よく使うフラグ」に `--resume --retry-failed` 追加・ドキュメントリンク追加
- `AGENTS.md` — クイックコマンド件数（163件）・参考ドキュメントに v0.4 追加
- `docs/handoff/004-retry-failed.md` — 本ファイル（新規）

### 未更新

- なし。計画書 §7.4 で想定された全ドキュメントを更新済み。

---

## 手動確認

実施済み（WP-3 時点）:

- `uv run iroiro translate --help` で `--retry-failed` / `--no-retry-failed` フラグが表示されることを確認
- `uv run pytest` / `ruff` / `mypy` が全てクリーンであることを確認

推奨される実機確認（次回実 LLM 検証時）:

1. `cp iroiro.toml.example iroiro.toml` で実体を作成（既存の場合は省略）
2. 適当な MOD XML で一度翻訳を実行し、意図的に `failed` エントリを残す
   （例: LLM サーバーを落とした状態で実行・ネットワークエラーで `failed` にする）
3. `progress.json` の `failed` リストに index が入っていることを確認
4. LLM サーバーを起動し、`uv run iroiro translate INPUT.xml --resume --retry-failed` を実行
5. 以下を確認:
   - `failed` にあった index が再翻訳されること
   - 成功した index が `progress.json` の `entries` に移り、`failed` から消えていること（不変性）
   - 出力 XML の `<Dest>` に新しい訳文が入っていること
6. `iroiro.toml` に `retry_failed = true` と書き、`--resume` 単独で同じ挙動になることを確認（T126 の実機相当）
7. `--no-retry-failed` を付けると `iroiro.toml` の `retry_failed = true` が上書きされて再翻訳されないことを確認（T127 の実機相当）
8. `--retry-failed` 単独（`--resume` 無し）で WARNING ログが出て通常実行になることを確認（T129 の実機相当）

---

## 既知の問題・残 TODO・リスク

### 既知の問題

1. **`mark_failed()` の重複チェックが O(N) 線形探索**
   - `if index not in failed` は `failed` リスト（`list[int]`）の線形探索。
   - `failed` は通常数十件程度なので実用上問題なし。
   - 数千件になったら `set` への持ち替えを検討する（計画書 §11.5・将来課題）。

2. **決定論的エラーも再試行対象になる**
   - token mismatch 等の決定論的エラー（同じ入力・同じモデルなら同じ結果）も `--retry-failed` で再試行される。
   - 同じ結果になる可能性が高く、無駄な LLM 呼出になる点に注意。
   - ユーザー判断で opt-in する設計なので、ドキュメント（`docs/usage.md`「使用シナリオ」）で注意喚起済み。

3. **実 LLM での動作検証が未実施**
   - 再試行ロジック・不変性・優先順位マージは単体テスト（T110-T129）で担保済み。
   - 実モデルでの `--resume --retry-failed` の動作確認は次回実機検証時に行う。

### 残 TODO（v0.5 候補）

- **`max_tokens` 設定** — LLM の生成トークン上限を `iroiro.toml` / CLI フラグで調整可能に。
  `--ctx-size` 不足の空応答対策。v0.4 でスコープ外（計画書 §5.2）。
- **選択的リトライ**（`--retry-failed-only INDEX` 等） — 特定 index だけ再試行。
  v0.4 は全 `failed` 一括のみ。必要なら progress.json 手動編集で代替可能（計画書 §5.2 / §14）。
- **リトライ回数制限**（N 回失敗したら諦める等） — v0.4 は無制限。複雑性増のため将来課題（計画書 §5.2 / §14）。
- **用語集機能** — v0.2 計画書から継続。
- **長文 BOOK の自動分割** — 同上。

### リスク

| リスク | 影響度 | 状態 |
|---|---|---|
| 決定論的エラー（token mismatch 等）を無駄に再試行するコスト | 低 | ユーザー判断で明示 opt-in する設計で緩和済み。`docs/usage.md` の「使用シナリオ」で注意喚起 |
| `mark_failed` の O(N) 線形探索が大規模 MOD で遅くなる | 極低 | `failed` は通常数十件。数千件になったら `set` 検討（将来課題） |
| ユーザーが `retry_failed = 1` と書いて意図せず全 failed が再試行対象になる | 極低 | `_validate_bool` が厳格 bool のみ許可（`1` / `0` / `"true"` は `IroiroError`）・T113 で検証済み |
| 既存ユーザーが v0.3 からアップデートして挙動が変わる | 極低 | v0.4 は後方互換。`--retry-failed` を使わなければ v0.3 と同じ挙動 |

---

## ロールバックメモ

`iroiro` は入力 XML を破壊しない設計。v0.4 の生成物を削除すれば v0.3 の状態に戻る:

```bash
rm path/to/your_mod.translated.xml
rm path/to/your_mod.xml.iroiro-progress.json
rm -f path/to/your_mod.xml.iroiro-progress.json.tmp
```

### v0.3 動作に戻したい場合（コードは v0.4 のまま）

`--retry-failed` を使わず、`iroiro.toml` にも `retry_failed` を書かなければ v0.3 と同じ挙動
（`failed` は確定扱い・再試行しない）。`iroiro.toml` に `retry_failed = true` を書いてしまった場合は
削除・コメントアウトすれば無効化される:

```toml
# retry_failed = true   # コメントアウトで無効化
```

### v0.4 コード自体を巻き戻す場合

`git revert <v0.4 commit>` で v0.3 に戻る。`iroiro.toml`（実体）に `retry_failed = true` と書いて
残っていても、v0.3 では未知キー扱いで **WARNING ログのみ** 出力され、例外送出せず続行する
（`load_config` の前方互換仕様・計画書 §9）。実害なし。

---

## 次の担当者・エージェントへのメモ

### v0.4 は後方互換

- 既存の CLI フラグ運用（`--resume` 等を毎回明示）は **そのまま動く**。
- `--retry-failed` を使わなければ v0.3 と完全に同じ挙動。
- v0.3 で作成した `progress.json` は v0.4 でもそのまま resume 可能（`progress.json` 仕様は無変更・
  `failed` リストの重複チェックは単発呼出には影響しない）。

### コードを読む場合の推奨順序（v0.4 追加分）

1. `iroiro/config.py` — `RunConfig.retry_failed` フィールド・`_validate_bool` validator（厳格 bool）
2. `iroiro/cli.py` — `--retry-failed` / `--no-retry-failed` フラグ（`bool | None = None`）・
   `_resolve` でのマージ・`_apply_existing` の `retry_failed` 分岐・`_run` 先頭の WARNING ログ
3. `iroiro/progress.py` — `mark_done` の failed クリア（不変性保証）・`mark_failed` の重複チェック
4. `tests/test_cli.py` の T114-T117（`_apply_existing` 単体）と T123-T129（CLI 統合）— 契約の網羅

### 設計上の重要事項（申送り事項）

- **`_resolve` は `is None` 判定を使う**（`or` 演算子は `0` / `""` / `False` を埋もれさせるため絶対に使わない）。
  `retry_failed` も同じパターン。`bool | None = None` で3状態（`True` / `False` / 未指定）を区別する（T126/T127 の肝）。
- **不変性 `entries ∩ failed = ∅`**: retry 成功時に `mark_done` が `failed` から index を削除することで保証。
  これにより progress.json と「Resuming: X translated, Y failed」メッセージが常に整合する（T121 / T125）。
- **`mark_failed` の重複チェック**: retry ループで同じ index が複数回 append されるのを防止（T118）。
  O(N) 線形探索だが実用上問題なし。
- **`_validate_bool` は厳格 bool**: `retry_failed = 1` は `IroiroError` で拒否（`bool ⊂ int` 事故防止・T113）。
  他の数値フィールドが `bool` を拒否するのと対称。
- **`retry_failed` は `RunConfig`（`ApiConfig` でなく）に置く**: 実行制御フラグ（`resume` / `dry_run` 等と同種）だから。
  `Translator` は `retry_failed` を知らない（テスト容易性）。
- **`--retry-failed` 単独（`--resume` 無し）は WARNING で続行**: exit 2 にしない（ユーザーの `--resume` 忘れに
  対する親切設計・T129）。

### v0.5（`max_tokens` 設定 / 選択的リトライ等）を始める場合

- **`max_tokens` 設定** を追加する場合、`ApiConfig`（`RunConfig` でなく）に置くのが自然
  （LLM 呼出パラメータだから・`retry_failed` とは逆の置き場所）。`_validate_int_min` が再利用可能。
- **選択的リトライ**（`--retry-failed-only INDEX` 等）を追加する場合、`_apply_existing` の `failed` 分岐を
  「全件」から「指定 index のみ」に拡張する。`retry_failed` の型を `bool` から `bool | list[int]` 等に変更する
  必要がある（破壊的変更になるため、v0.5 で別フラグにするのが無難）。
- **リトライ回数制限** を追加する場合、`progress.json` に `retry_count` フィールドを持たせる必要がある
  （`ProgressWriter` の schema 拡張・`load_existing` の後方互換処理が必要）。
