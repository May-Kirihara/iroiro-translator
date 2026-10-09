# 実装計画 008 — レジューム自動化 + `--force-restart` フラグ（v0.8）

- 作成: 2026-07-03
- リスク分類: **high-risk**
- バージョン: v0.8（既定動作の変更・後方互換性は `--resume` で保持）
- 関連: [Plan 004](004-retry-failed.md)（`--retry-failed`・resume 前提）/ [設計判断](../design.md)

---

## 1. ゴール

progress.json が存在する場合に **自動でレジューム** する（`--resume` フラグ省略可）。
最初からやり直したい場合は `--force-restart` で明示指定する。

**動機**: ユーザーが `--resume` 忘れで実行 → 既存 progress.json が **新規データで上書き** され、
蓄積した再開状態（訳文・failed リスト）が消滅する事故が発生した。これを「デフォルト安全」にする。

非ゴール:
- progress.json のフォーマット変更（`ProgressWriter` / `load_existing` は **変更しない**）
- `--retry-failed` の仕様変更（自動レジューム化に伴う警告条件の調整のみ）

---

## 2. 背景・現状

### 2.1 現状のレジューム挙動（`cli.py:311-327` = `translate` / `cli.py:682-697` = `mcm`）

```python
existing: ProgressData | None = None
if cfg.resume:                       # ← --resume フラグが必須
    try:
        existing = writer.load_existing()
    except ValueError as e:          # input_hash 不一致 / JSON decode error → exit 2
        ...
    if existing is not None:
        _apply_existing(entries, existing, retry_failed=cfg.retry_failed)
```

- `--resume` 無し → `load_existing` を呼ばない → entries 全 pending → **翻訳開始と同時に progress.json を新規データで上書き**（`mark_done` が fresh `_data` に書く）。**これが事故の本体**。
- `--resume` + `input_hash` 不一致 → `ValueError` → exit 2（data integrity 保護・維持）。
- `--resume` + `skip_records` fingerprint 不一致 → WARNING のみ・継続（v0.6.1・Plan 006）。

### 2.2 影響範囲

- `translate` / `mcm` **両サブコマンド**（共通の resume ブロック）。
- `RunConfig`（`resume` フィールド）・`cli.py`（`--resume` フラグ定義 ×2）。

### 2.3 既存テストの isolation 問題（QA review Blocker・auto-resume で顕在化）

**重要**: 既存テストのうち、**fixture パスを直接 `_run_translate()` に渡すテスト**が auto-resume で破綻する。

該当テスト（`tests/test_cli.py`・`_run_translate(tiny_xml|tiny_crlf_bom_xml|skip_records_xml)` 直接参照・`--resume` 無し）:
T36(L227) / T37(L270) / T39(L380) / T40(L411) / T64(L596) / T67 相当 / T69(L624) / T70(L688)

破綻メカニズム:
1. **ローカル disk の stale progress.json**: `tests/fixtures/{tiny,skip_records,tiny_crlf_bom}.xml.iroiro-progress.json` が **hash 一致** の状態で disk に存在する（過去のテスト実行で生成・`.gitignore` 対象なので git 非追跡・CI/新規 clone には無いが開発者環境には残る）。
2. auto-resume がこれらを取り込み → T36 は entry[0] が `failed` 扱い（mock 呼ばれず「【訳】」付かず→FAIL）・T69 は `translatable` が 2→0（dry-run 集計・FAIL）。
3. **セッション内汚染**: T36 実行が `mark_done` で `tiny.xml.iroiro-progress.json` を新規生成 → 後続の T37/T39 が auto-resume で取り込む（pytest 定義順で連鎖）。

**根本原因**: これらのテストは fixture を `tmp_path` に copy せず直接参照する（T38 は copy する isolation パターンの模範）。現状は `--resume` 必須なので progress.json が無視され潜在化していたが、auto-resume 既定化で **显在化** する。

**修正方針**（WP-1 スコープ拡張・下記 §4）: 該当テストを T38 パターン（`shutil.copy(fixture, tmp_path)` → tmp_path 入力で `_run_translate`）に揃える。これは「既存テストの弱化」ではなく **isolation の強化**（アサーション不変・setup のみ修正）。併せて `.gitignore` の `*.iroiro-progress.json` エントリは既存（line 222）なので追記不要。

※ QA review は「commit 済み」と主張したが、実測では `.gitignore` 対象・`git ls-files` 空・**ローカル disk のみ**。追跡の有無によらず isolation 修正は必須（CI は clean でも開発者環境の `uv run pytest` で破綻するため）。

---

## 3. 設計判断

### 3.1 自動レジューム（デフォルト）— `--resume` は後方互換 no-op

**採用**: progress.json が存在する場合、**フラグ無しで自動レジューム**。
`--resume` フラグは **後方互換のため残す**（既存スクリプト・肌肉記憶を壊さない）。auto-resume が既定になったため `--resume` は実質 no-op だが、受け付けて INFO ログで「resume は既定動作になりました（no-op）」を1行出す（ deprecated 案内・v0.9 で削除候補）。

却下（`--resume` 削除）: 既存スクリプトを壊す breaking change。本件は「安全な既定化」が目的で、削除はスコープ外。

### 3.2 `--force-restart`（新規・明示的再開）

**採用**: `--force-restart` / `--no-force-restart`（bool・既定 False）。
- 既定（False）= 自動レジューム。
- `--force-restart` = 既存 progress.json を **破棄** して新規開始。

**破棄の sematics**: `--force-restart` 時、既存 progress.json ファイルがあれば **起動時に削除**（`unlink`）する。
理由: 単に `load_existing` を skip するだけだと、初回 `mark_done` 前にクラッシュした場合に **古い progress.json が生き残り**、次回（フラグ無し）実行で古いデータから resume してしまう（利用者意図と矛盾）。削除で sematics を明確化する。
dry-run + `--force-restart` の組み合わせも削除する（`--force-restart` は利用者の明示的破壊 opt-in であり、dry-run の「副作用なし」原則より優先・docs に明記）。

却下（`.bak` リネーム）: クラッター発生・progress.json は次回実行で再生成されるため過剰保護。

`--resume` と `--force-restart` の同時指定: **`--force-restart` を優先**（明示的 opt-out がより具体的意図）。エラーにしない（利用者が両方渡した時に停止より継続）。

### 3.3 `input_hash` 不一致・破損 progress.json の既定動作（**振る舞い変更**）

自動レジューム化に伴い、以下が **既定で exit 2 エラー** になる（従来は `--resume` 無しなら無視＝fresh start）:

| 状態 | 従来（`--resume` 無し） | 新既定（auto-resume） | `--force-restart` |
|---|---|---|---|
| progress.json 無し | fresh | fresh | fresh（削除対象無し・no-op） |
| progress.json 有り・hash 一致 | **上書き（事故）** | **自動 resume** ✓ | 削除 → fresh |
| progress.json 有り・**hash 不一致** | 無視＝fresh | **exit 2 エラー**（data integrity） | 削除 → fresh |
| progress.json 有り・**JSON 破損** | 無視＝fresh | **exit 2 エラー** | 削除 → fresh |

**hash 不一致を exit 2 にする理由**: 入力ファイルが編集された場合、古い progress.json で resume するのは誤り（data integrity）。従来の「無視して fresh」は **暗黙に古い進捗を捨てる** = 今回防止したい事故の変種。エラーにして利用者に判断させる（`--force-restart` or progress.json 削除）のが安全。
エラーメッセージは既存の `load_existing` のもの（「Please remove <path>」）に `--force-restart` 案内を追記。

### 3.4 `--retry-failed` 警告条件の調整

現状（`cli.py:280-284` / `mcm` 側にも同ロジック）: `cfg.retry_failed and not cfg.resume` → WARNING。
auto-resume 化で `cfg.resume` は意味を失うため、条件を **「progress が実際に load されたか」** に変更:

```python
# retry_failed が意味を持つのは progress から failed が load された時のみ
if cfg.retry_failed and (cfg.force_restart or existing is None):
    warn("--retry-failed が指定されましたが progress.json が読み込まれなかったため、"
         "failed エントリの再試行は行われません（--force-restart または progress.json 無し）")
```

**実装上の注意**（Codex review 指摘）: 現状の警告は parse/resume **前**（`cli.py:281` / `651`）に
実行されるが、新条件は `existing`（= `load_existing()` の結果）に依存するため、**resume ブロックの
後** に移動する必要がある。`existing` が確定した時点で評価する。

### 3.5 RunConfig 変更（最小・後方互換）

- `force_restart: bool = False` フィールド追加（**デフォルト False 必須**・既存フィールドの末尾に追加・
  直接 `RunConfig(...)` 構築するテスト/スクリプトの後方互換・Codex review 指摘）。
- `resume: bool` は **残す**（後方互換・`--resume` フラグから設定・ロジックでは参照しない・docstring に
  deprecated 注記）。
  - 却下（`resume` 削除）: `RunConfig` 構築箇所・直接構築するテストの churn が大きく、high-risk では最小差分が優先。vestigial だが無害。

---

## 4. スコープ・非ゴール

### スコープ

- `iroiro/cli.py`: `translate` / `mcm` 両方に `--force-restart` フラグ追加・resume ブロックを auto-resume 化・`--resume` を no-op 化（deprecated INFO）・retry 警告条件調整
- `iroiro/config.py`: `RunConfig` に `force_restart: bool` 追加・`resume` docstring に deprecated 注記
- `tests/test_cli.py`: auto-resume / `--force-restart` / hash 不一致エラー / dry-run 自動 resume / retry 警告 の新規テスト + 既存 resume テストの `--resume` no-op 追随確認
- ドキュメント: `README.md` / `docs/usage.md`（resume セクション全面改訂 + `--force-restart`）/ `docs/development.md`（ロードマップ）・本計画書・`docs/handoff/008-*.md`

### 非ゴール

- `ProgressWriter` / `load_existing` / `progress.py` のロジック変更（I/O は触らない）
- progress.json フォーマット変更
- `--resume` の削除（v0.9 候補）
- MCM 固有の変更（共通ロジックのため両サブコマンドで同等に働く）

---

## 5. テスト戦略

### 5.1 自動レジューム（新規）

- T-AUTO-01: progress.json 有り・`--resume` 無し → **自動 resume**（entry[0] が progress.json の訳文・MockTranslator に渡されない）
- T-AUTO-02: progress.json 無し・`--resume` 無し → fresh（従来同様）
- T-AUTO-03: `--resume` 明示 + progress.json 有り → 従来同様 resume（後方互換）
- T-AUTO-04: dry-run + progress.json 有り → 「再開済: N」表示（dry-run も auto-resume する）

### 5.2 `--force-restart`（新規）

- T-FORCE-01: progress.json 有り + `--force-restart`（**dry-run**） → fresh 開始・**progress.json ファイルが削除される**（`progress_path.exists() == False` after・dry-run は mark_done が走らないのでファイル不在が成立）
- T-FORCE-02: progress.json 有り + `--force-restart`（dry-run） → dry-run 表示で「再開済」が 0（fresh 扱い）
- T-FORCE-03: progress.json 有り + `--force-restart`（**非 dry・実翻訳**） → entry[0] が MockTranslator に渡される（resume しない）・**翻訳後に再生成された progress.json に旧エントリが含まれない**（Codex review 指摘: 非 dry では mark_done がファイルを再生成するため「ファイル不在」ではなく「新ファイルに旧データ無し」で検証）
- T-FORCE-04: progress.json 無し + `--force-restart` → fresh・エラー無し（no-op）
- T-FORCE-05: `--resume` + `--force-restart` 同時 → `--force-restart` 優先（fresh・削除）

### 5.3 hash 不一致・破損（振る舞い変更）

- T-HASH-01: progress.json 有り・hash 不一致・`--resume` 無し → **exit 2 エラー**（従来は fresh・振る舞い変更）・メッセージに `--force-restart` 案内
- T-HASH-02: progress.json 有り・hash 不一致 + `--force-restart` → 削除 → fresh・エラー無し
- T-CORRUPT-01: progress.json 破損（不正 JSON）・`--resume` 無し → **exit 2 エラー**
- T-CORRUPT-02: 破損 + `--force-restart` → 削除 → fresh

### 5.4 retry 警告

- T-RETRY-WARN-01: `--retry-failed` + progress.json 有り（hash 一致）→ 警告無し（failed 再試行が意味を持つ）
- T-RETRY-WARN-02: `--retry-failed` + progress.json 無し → WARNING
- T-RETRY-WARN-03: `--retry-failed` + `--force-restart` → WARNING（progress 破棄なので）

### 5.5 MCM パリティ（happy-path + error-path・QA Major-1 対応）

- T-MCM-AUTO-01: `mcm` でも progress.json 有り・`--resume` 無し → 自動 resume（translate と対称）
- T-MCM-FORCE-01: `mcm` + `--force-restart` → fresh・progress.json 削除
- **T-MCM-HASH-01**: `mcm` + progress.json hash 不一致・`--resume` 無し → **exit 2 エラー**（translate 側 T-HASH-01 と対称・複製ブロックの片側漏れを検知）
- **T-MCM-CORRUPT-01**: `mcm` + 破損 progress.json → exit 2 エラー
- **T-MCM-RETRY-WARN-01**: `mcm` + `--retry-failed` + progress.json 無し → WARNING（新条件の mcm 側検証）

### 5.6 既存テスト回帰 + 補助テスト（QA Minor 対応）

- T38 / T82 / T123-T127 / T-CLI-MCM-02 / T-MCM-RESUME が `--resume` 明示で従来 green を維持することを確認。
- §2.3 の isolation 強化後、`tests/fixtures/*.iroiro-progress.json` が disk にあっても T36/T37/T39/T40/T64/T67/T69/T70 が green になることを確認（stale 依存でなく isolation で通過）。
- **T-AUTO-03 拡張**: `--resume` 明示渡しで INFO ログに「既定動作」「no-op（deprecated）」が含まれること（§3.1・QA Minor-1）。
- **T-AUTO-FP-01**: auto-resume（`--resume` 無し）+ `skip_records` fingerprint 不一致 → WARNING のみで継続（exit 2 に昇格していないことの回帰ガード・QA Minor-2・T82 の auto-resume 版）。
- T129 docstring の「`--resume` 単独無し」前提を「progress.json 無し」に更新（QA Minor-4・`tests/test_cli.py` WP-1 スコープ）。

---

## 6. 実装計画（Work Packages）

high-risk につき **直列・並列化しない**。`WP-1-tests` → `WP-2-core` → `WP-3-docs`。

### WP-1: テスト（test-first + 既存テスト isolation 強化）

- Scope（§2.3 対応込み）:
  - `tests/test_cli.py` に §5 の新規テスト追加（auto-resume / force-restart / hash / corrupt / retry 警告 / MCM error-path）
  - **既存テストの isolation 強化**: `_run_translate(tiny_xml|tiny_crlf_bom_xml|skip_records_xml)` を直接参照するテスト（T36/T37/T39/T40/T64/T67/T69/T70・grep で全件特定すること）を **T38 パターン（`shutil.copy(fixture, tmp_path)` → tmp_path 入力）** に変換。**アサーションは変更しない**（弱化禁止）・setup のみ。これにより auto-resume でも fixture ディレクトリの stale progress.json に影響されない。
- Acceptance: 新規テストが RED（未実装）・変換した既存テストが green 維持・`uv run pytest` で `tests/fixtures/*.iroiro-progress.json` が disk にあっても全 green（isolation 確認）
- Allowed paths: `tests/test_cli.py`（既存テストの setup 変更を含む・アサーション変更は禁止）

### WP-2: コア実装

- Scope: `iroiro/cli.py`（両サブコマンド）・`iroiro/config.py`（`RunConfig`）
- Acceptance: `uv run pytest` 全 green・`ruff`・`mypy` clean
- Allowed paths: `iroiro/cli.py`・`iroiro/config.py`

### WP-3: ドキュメント・引き継ぎ

- Scope（QA Major-2 対応・更新対象セクション明示）:
  - `docs/usage.md`: (a) resume セクション全面改訂（自動レジューム既定化 + `--force-restart`）・(b) `--retry-failed` 単独の挙動節（`usage.md:661-671` 相当・警告条件が「`--resume` 無し」→「progress.json 無し」に変わるので全面書き換え）・(c) hash 不一致トラブルシュート（`--force-restart` 案内を併記）・(d) **破壊的変更の専用節**（hash 不一致・破損が `--resume` 無しでも exit 2 になる・目立つ場所に）
  - `README.md`: 機能一覧の「再開機能（`--resume`）」→「自動再開 + `--force-restart`」・破壊的変更の注意喚起
  - `docs/development.md`: ロードマップ（v0.8）・テスト戦略表に auto-resume/isolation 強化を追記
  - `docs/handoff/008-auto-resume.md`（新設）: 検証結果（stale ファイル実態・isolation 強化内容・破壊的変更）を事実ベースで記録
- Acceptance: 破壊的変更（hash 不一致 exit 2）が README + usage.md の目立つ場所に明記・`--force-restart` の使い方が実装と整合
- Allowed paths: `README.md`・`docs/`（`iroiro.toml.example` は触らない）

---

## 7. リスク

| リスク | 影響 | 軽減 |
|---|---|---|
| hash 不一致が既定で exit 2 になる（振る舞い変更） | 中 | エラーメッセージで `--force-restart` を案内・docs/usage.md で強調・T-HASH-01 で検証 |
| 既存 `--resume` 利用者が混乱（no-op 化） | 低 | deprecated INFO ログ・docs で「既定動作化」を明記 |
| dry-run + `--force-restart` が progress.json を削除（副作用） | 低 | docs で明記・`--force-restart` は明示 opt-in |
| `RunConfig.resume` が vestigial で保守者混乱 | 低 | docstring に deprecated 注記・v0.9 削除候補 |
| `mcm` 側の resume ブロック改修漏れ | 中 | WP-2 で両サブコマンドを対称に実装・T-MCM-AUTO/FORCE で検証 |

---

## 8. 仮定台帳

| # | 仮定 | 根拠 | 反証条件 | 影響範囲 |
|---|---|---|---|---|
| A1 | `--force-restart` という名称でよい | ユーザー申告「--force-restart的な」 | ユーザーが別名希望 | CLI flag 再設計（小） |
| A2 | hash 不一致は既定で exit 2（エラー） | data integrity・事故防止が目的 | ユーザーが「warn+fresh」希望 | エラー処理 → 警告に変更（小） |
| A3 | `--resume` は後方互換で残す（no-op） | 既存スクリプト保護 | ユーザーが削除希望 | breaking change（中） |
| A4 | `--force-restart` は progress.json を削除 | sematics 明確化・stale 残存防止 | ユーザーが削除不可希望 | skip-only に変更（小） |
| A5 | dry-run + `--force-restart` も削除する | 明示 opt-in 優先 | dry-run 副作用なし原則を優先 | dry-run は skip-only（小） |

---

## 9. 検証完了条件

1. `uv run pytest`（246 + 新規）全 green
2. `uv run ruff check iroiro/ tests/`・`uv run mypy iroiro` clean
3. 実機: progress.json 有りで `iroiro translate X.xml --dry-run`（`--resume` 無し）→ 「再開済: N」表示
4. 実機: `--force-restart` で progress.json が削除され fresh 開始
5. 既存 `translate`/`mcm` の `--resume` 利用が従来 green（後方互換）

---

## 10. レビューゲート（high-risk）

Codex 計画レビュー / QA 計画レビュー / test-first / Codex+QA テスト差分 / 実装 / PM 検証 / Codex 最終 / QA 最終 / writeback（全実施）。
