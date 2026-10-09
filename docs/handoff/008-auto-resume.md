# 引き継ぎメモ: iroiro-translator v0.8 自動レジューム + `--force-restart` (008-auto-resume)

- 作成日: 2026-07-03
- 計画書: [`docs/plans/008-auto-resume.md`](../plans/008-auto-resume.md)
- 状態: **done-with-notes**

---

## ステータス

| 項目 | 値 |
|---|---|
| 状態 | done-with-notes |
| 日付 | 2026-07-03 |
| リスク分類 | `high-risk`（既定動作の変更・後方互換性は `--resume` no-op で保持） |
| バージョン | v0.8（機能面・ドキュメント・`iroiro/__init__.py.__version__`（`"0.8.0"`）全て v0.8 に更新済み・`__version__` bump は follow-up で解消済み） |
| 前バージョン | v0.7（Skyrim MCM 翻訳 TXT 対応） |
| 担当 | PM + implementer（WP-1 テスト / WP-2 コア実装 / WP-3 ドキュメント・handoff・本 WP） |
| テスト | 268 passed（+22: auto-resume / `--force-restart` / hash 不一致 exit 2 / 破損 progress.json / retry 警告条件変更 / MCM error-path パリティ・v0.7 までは 246 件） |
| ruff | clean（`All checks passed!`） |
| mypy | clean |
| smoke test | OK（translate / mcm 両方で auto-resume・`--force-restart`・hash 不一致 exit 2 を実機確認・下記「手動確認」参照） |
| 概要 | v0.8 で progress.json が存在する場合の **自動レジュームを既定動作** にした（従来は `--resume` フラグ必須・忘れると上書きで進捗消失の事故）。`--force-restart`（新規）で既存 progress.json を破棄して最初から。`--resume` は後方互換 no-op（deprecated INFO・v0.9 削除候補）。hash 不一致・破損 progress.json が `--resume` 無しでも exit 2 になる破壊的変更あり。 |

---

## 変更内容

v0.8 は **既定動作の変更**（破壊的）で、新規モジュール追加は無し。`translate` / `mcm` 両サブコマンドの
resume ブロック（`_run` / `_run_mcm`）と `RunConfig` のみが変わる。翻訳エンジン（`Translator`・
`_translate_all`）・I/O（`xml_io` / `mcm_io` / `progress.py` の `load_existing`・`ProgressWriter`）・
progress.json フォーマットは **一切触っていない**。

### 機能サマリ

1. **自動レジューム既定化**（`iroiro/cli.py`・`_run` / `_run_mcm`）— progress.json が存在する場合、`--resume` フラグ **無しで自動レジューム**。`load_existing()` を常に呼ぶ（従来は `if cfg.resume:` で gate）。
2. **`--force-restart` / `--no-force-restart`**（新規 CLI フラグ・`translate` / `mcm` 両方）— 既定 False（= 自動レジューム）。`--force-restart` 時、起動時に既存 progress.json を `unlink()` で **削除** して fresh 開始。dry-run でも削除（明示的破壊 opt-in・dry-run の「副作用なし」原則より優先）。
3. **`--resume` の no-op 化**（後方互換）— `--resume` を受け付けるが INFO ログ1行（`--resume は既定動作になりました（no-op・非推奨・v0.9 で削除候補）`）を出すのみ。ロジックでは参照しない。`RunConfig.resume` フィールドは残す（直接構築箇所の churn を避けるため・docstring に vestigial 注記）。
4. **hash 不一致・破損 progress.json の exit 2 既定化**（**振る舞い変更**）— 従来は `--resume` 無しなら無視（fresh start）だったが、auto-resume 既定化で `load_existing()` が常に走るため **常に検証される**。hash 不一致・JSON decode error は `ValueError` → exit 2。エラーメッセージの catch レベルで `-> Or use --force-restart to discard and start fresh.` 案内を付加（hash / 破損の両エラーパスに自動適用）。
5. **`--retry-failed` 警告条件の調整** — 従来「`--retry-failed and not cfg.resume`」→ 新「`--retry-failed and (cfg.force_restart or existing is None)`」。auto-resume 化で `cfg.resume` は意味を失ったため「progress.json が実際に load されたか」に条件を移行。評価位置を resume ブロックの **後**（`existing` 確定後）に移動。
6. **`RunConfig.force_restart`**（`iroiro/config.py`）— `bool` フィールド・デフォルト `False`・**末尾かつデフォルト付き**で追加（直接 `RunConfig(...)` を構築するテスト/スクリプトの後方互換・Plan 008 §3.5 / Codex review 指摘）。CLI 専用で `iroiro.toml` 項目は無い。

### 振る舞い変更の全量テーブル

`translate` / `mcm` 共通:

| 状態 | 従来（v0.7 まで・`--resume` 無し） | v0.8 既定（auto-resume） | `--force-restart` |
|---|---|---|---|
| progress.json 無し | fresh 開始 | fresh 開始 | fresh 開始（削除対象無し・no-op） |
| progress.json 有り・hash 一致 | **上書き（進捗消失の事故）** | **自動 resume** ✓ | 削除 → fresh 開始 |
| progress.json 有り・hash 不一致 | 無視＝fresh 開始 | **exit 2 で停止**（data integrity） | 削除 → fresh 開始 |
| progress.json 有り・JSON 破損 | 無視＝fresh 開始 | **exit 2 で停止** | 削除 → fresh 開始 |

### 破壊的変更

1. **hash 不一致・破損 progress.json が `--resume` 無しでも exit 2 になる**（核心）。従来の「`--resume` 無しなら無視して fresh」は今回防止したい事故の変種（暗黙に古い進捗を捨てる）。`--force-restart` または progress.json 削除で回避。
2. **`--resume` 無しの再実行が fresh でなく resume になる**（従来 fresh 開始を意図していた利用者は `--force-restart` を使う必要あり）。
3. **dry-run + `--force-restart` が progress.json を削除する**（dry-run の副作用無し原則の例外・明示 opt-in で優先）。

後方互換（破壊的でない）:

- `--resume` フラグは受け付ける（deprecated INFO のみ・動作は no-op）。
- `RunConfig.force_restart` はデフォルト False で既存の直接構築を壊さない。
- progress.json フォーマット・`load_existing` のシグネチャ・戻り値は不変。

### 削除・廃止

無し（`--resume` は残す・v0.9 削除候補）。

---

## 変更理由

### `--resume` 忘れによる進捗消失事故の防止（本件の動機）

v0.7 までは `--resume` フラグの付与が必須で、**`--resume` 無しで再実行すると `load_existing()` を呼ばず
entries 全 pending → 翻訳開始と同時に progress.json を新規データで上書き** する仕様だった。利用者が
`--resume` を忘れると、蓄積した再開状態（訳文・failed リスト）が消滅する事故が発生した。

「デフォルト安全」への転換: progress.json が存在するなら自動でレジュームし、最初からやり直したい場合は
`--force-restart` で明示的に opt-out する設計（Plan 008 §1 / §3.1）。

### hash 不一致を exit 2 にする理由

入力ファイルが編集された場合、古い progress.json で resume するのは誤り（data integrity）。従来の
「無視して fresh」は暗黙に古い進捗を捨てる = 今回防止したい事故の変種。エラーにして利用者に判断させる
（`--force-restart` or progress.json 削除）のが安全（Plan 008 §3.3）。

### `--force-restart` が progress.json を削除する（skip-only でなく）理由

単に `load_existing` を skip するだけだと、初回 `mark_done` 前にクラッシュした場合に **古い progress.json
が生き残り**、次回（フラグ無し）実行で古いデータから resume してしまう（利用者意図と矛盾）。削除で
semantics を明確化（Plan 008 §3.2・却下: `.bak` リネームはクラッター発生で過剰保護）。

### `--resume` を削除せず no-op で残す理由（Plan 008 §3.1・却下代替案）

`--resume` 削除は既存スクリプトを壊す breaking change。本件は「安全な既定化」が目的で、削除はスコープ外。
vestigial だが無害。v0.9 で削除候補（直接 `RunConfig` 構築箇所の churn が大きいと high-risk では最小差分が優先）。

### `RunConfig.force_restart` を末尾かつデフォルト付きで追加した理由

直接 `RunConfig(input_path=..., ...)` を構築する既存テスト/スクリプトが `force_restart` を指定せずに壊れるのを
避けるため（Plan 008 §3.5・Codex review 指摘）。`slots=True` dataclass で末尾にデフォルト付きフィールドを追加
すれば、位置引数での構築以外は後方互換。

---

## Work packages

### WP-1-tests（✅ 完了）

| 項目 | 値 |
|---|---|
| Goal | auto-resume / `--force-restart` / hash / corrupt / retry 警告 / MCM error-path のテスト追加（test-first）+ 既存テストの isolation 強化 |
| Status | done |
| Allowed paths | `tests/test_cli.py` |
| Files | `tests/test_cli.py`（新規テスト: auto-resume / `--force-restart`（dry-run 削除 / 非 dry 旧エントリ無し / `--resume` 同時指定で force 優先 / progress.json 無し no-op）・hash 不一致 exit 2（`--resume` 無しでも）・破損 progress.json exit 2・`--force-restart` で回避・retry 警告条件の「progress.json 未 load」化・MCM error-path パリティ T-MCM-HASH/CORRUPT/RETRY-WARN・dry-run 自動 resume 表示・`--resume` no-op INFO ログ検証） |
| Verification | WP-2 完了後に全 green・既存テスト回帰無し・`tests/fixtures/*.iroiro-progress.json` が disk にあっても全 green（isolation 確認） |
| Notes | **既存テストの isolation 強化**: `_run_translate(tiny_xml\|tiny_crlf_bom_xml\|skip_records_xml)` を直接参照するテスト（T36/T37/T39/T40/T64/T69/T70 相当）を T38 パターン（`shutil.copy(fixture, tmp_path)` → tmp_path 入力）に変換。**アサーションは変更せず setup のみ**（テスト弱化禁止）。詳細は下記「既知の問題」の stale progress.json 問題を参照。 |

### WP-2-core（✅ 完了）

| 項目 | 値 |
|---|---|
| Goal | `cli.py`（両サブコマンド）・`config.py`（`RunConfig`）の実装 |
| Status | done |
| Allowed paths | `iroiro/cli.py`・`iroiro/config.py` |
| Files | `iroiro/cli.py`（`translate` / `mcm` 両方に `--force-restart` フラグ追加 L187 / L597・resume ブロック auto-resume 化 L316-355 / L720-753・`--resume` deprecated INFO L287-290 / L690-693・retry 警告条件調整 L351-355 / L748-753・hash/破損エラー catch で `--force-restart` 案内付加 L329-337 / L731-737）・`iroiro/config.py`（`RunConfig.force_restart: bool = False` 追加 L61・`resume` docstring に vestigial 注記 L29-31, L53-55） |
| Verification | `uv run pytest`（268 passed）・`uv run ruff check iroiro/ tests/` clean・`uv run mypy iroiro` clean |
| Notes | I/O（`progress.py` の `load_existing` / `ProgressWriter`・progress.json フォーマット）・翻訳エンジン（`translator.py`）・XML/MCM I/O（`xml_io.py` / `mcm_io.py`）は **1行も変更していない**。`translate` と `mcm` の resume ブロックは複製構造のため対称に実装（片側漏れは T-MCM-* が検知）。 |

### WP-3-docs-handoff（✅ 完了・本 WP）

| 項目 | 値 |
|---|---|
| Goal | ドキュメント更新・handoff 作成 |
| Status | done-with-notes |
| Allowed paths | `README.md` / `docs/usage.md` / `docs/development.md` / `docs/handoff/008-auto-resume.md`（新設）/ `docs/plans/008-auto-resume.md`（微修正のみ） |
| Forbidden | `iroiro/*`（`__version__` bump は follow-up 委譲） / `tests/*` / `iroiro.toml.example` / `docs/design.md` / 既存の plans/handoff 001-007 |
| Files | `README.md`（冒頭に v0.8 破壊的変更の注意喚起 blockquote・機能一覧を「自動再開 + `--force-restart`」に更新・よく使うフラグ更新・Plan 008 / handoff 008 リンク追記）/ `docs/usage.md`（CLI フラグ表に `--force-restart` 追加（translate / mcm 両方）・v0.8 破壊的変更 callout・「自動レジューム化と移行（v0.8）」専用節新設（振る舞い変更テーブル・移行手順）・「再開」節を全面改訂（自動レジューム + `--force-restart` + `--resume` no-op）・`--retry-failed` 単独節の警告条件書き換え・hash 不一致トラブルシュートに `--force-restart` 併記）/ `docs/development.md`（テスト数 246→268・モジュール構成の cli.py / config.py に v0.8 変更追記・テスト戦略表に v0.8 追加内容 + isolation 強化を追記・ロードマップ v0.8（✅ 完了）追加・v0.9 以降に `--resume` 削除候補を追記）/ `docs/handoff/008-auto-resume.md`（本ファイル・新設） |
| Verification | `uv run pytest -q`（268 passed・docs 変更でテストは壊れないことを確認） |

---

## 触ったファイル一覧

### WP-3 で触ったファイル（本 WP）

| ファイル | 変更内容 |
|---|---|
| `README.md` | 冒頭（intro 直後）に v0.8 破壊的変更の blockquote 注意喚起を追加。intro 文の `--resume` で続きから → 自動レジュームに更新。主な機能の「再開機能（`--resume`）」→「自動再開 + `--force-restart`（v0.8・破壊的変更）」に更新。よく使うフラグを `--force-restart` / `--retry-failed` / `--resume`（no-op）に更新。ドキュメント一覧に Plan 008 / handoff 008 を追記。**既存 XML `translate` / MCM 記述は全て保持** |
| `docs/usage.md` | CLI フラグ表（translate / mcm 両方）に `--force-restart` 行を追加・`--resume` 行を no-op 化注記に更新。v0.6 callout の直後に v0.8 破壊的変更 callout を追加。「自動レジューム化と移行（v0.8）」専用節を新設（振る舞い変更テーブル・回避方法・移行手順・`--resume` no-op 説明）。「再開」節を全面改訂（自動レジューム + `--force-restart` + `--resume` no-op・既存の failed 再試行・不変性の記述は保持）。`--retry-failed` 単独節の警告条件を「progress.json 未 load」に全面書き換え。hash 不一致トラブルシュートに `--force-restart` を併記・破損 progress.json の言及を追加。**既存 XML `translate` / MCM / skip_records / LLM プロンプト記述は全て保持** |
| `docs/development.md` | テスト全実行のコメントを 246 → 268 に更新（v0.8 +22件の内訳）。モジュール構成表の `cli.py` / `config.py` に v0.8 変更を追記。テスト戦略表の `tests/test_cli.py` 行に v0.8 追加内容 + isolation 強化を追記。ロードマップに v0.8（✅ 完了）を追加（v0.7 の次）。v0.8 以降（予定）→ v0.9 以降（予定）にリネーム・`--resume` 削除候補を先頭に追記 |
| `docs/handoff/008-auto-resume.md` | 新規作成（本ファイル） |

### WP-1 / WP-2 で触ったファイル（参考・本 WP では触っていない）

- `iroiro/cli.py`（WP-2）/ `iroiro/config.py`（WP-2）
- `tests/test_cli.py`（WP-1）

---

## テスト

### 実行コマンド

```bash
uv run pytest -q                                                    # 全テスト（268件）
uv run pytest -k "auto_resume or force_restart or hash or corrupt or retry_warn" --tb=no -q  # v0.8 関連のみ
uv run ruff check iroiro/ tests/                                    # lint
uv run mypy iroiro                                                  # 型チェック
```

### 結果（2026-07-03 実機確認）

- **`uv run pytest -q`**: `268 passed in 2.35s`（v0.7 の 246 件 + 22 件）
- **`uv run ruff check iroiro/ tests/`**: `All checks passed!`
- **`uv run mypy iroiro`**: clean
- **既存テスト isolation 確認**: `tests/fixtures/*.iroiro-progress.json` がローカル disk に存在する状態で `uv run pytest` を実行しても全 green（stale 依存でなく tmp_path copy で isolation 成立）

### smoke test（実機・sample は git 管理外の第三者著作物）

下記は PM / WP-2 時点の実機確認結果（本 WP では docs 変更のみのため再実行の必要は無いが、事実として記録）:

- **auto-resume（translate・`--resume` 無し）**: `uv run iroiro translate sample/JobsofSkyrim_english_japanese.xml --dry-run` → `Resuming: 2 translated, 0 failed` + `再開済（progress.json）: 2` が表示される（progress.json が存在する状態で `--resume` 無しでも自動レジューム）。
- **`--force-restart`**: `uv run iroiro translate sample/JobsofSkyrim_english_japanese.xml --dry-run --force-restart` → `discarding existing progress.json (--force-restart)` INFO + 当該 progress.json ファイルが削除される（dry-run でも削除）。
- **hash 不一致**: 入力ファイルを編集した状態で `--resume` 無しで再実行 → `Error: input_hash mismatch: progress.json has '...', current input is '...'. Please remove <path> if the input file has changed.  -> Or use --force-restart to discard and start fresh.` + exit code 2。
- **mcm 対称**: `uv run iroiro mcm sample/<MCM_ENGLISH.txt> --dry-run` → `Resuming: 3 translated, ...`（mcm 側でも auto-resume 動作・translate と対称）。

### 未実行項目

- **実 LLM での auto-resume E2E**: CI 上では実施せず（`translate` / `mcm` と同じ方針）。ユーザー環境での手動検証に委ねる。モック LLM ベースのテスト（T-AUTO-* / T-FORCE-* / T-MCM-*）で論理的な挙動は保証済み。

---

## ドキュメント更新状況

| ファイル | 更新状況 | 備考 |
|---|---|---|
| `README.md` | ✅ 更新 | 冒頭の破壊的変更注意喚起・主な機能・よく使うフラグ・ドキュメント一覧 |
| `docs/usage.md` | ✅ 更新 | CLI フラグ表（translate / mcm）・v0.8 callout・「自動レジューム化と移行（v0.8）」専用節・「再開」節全面改訂・`--retry-failed` 単独節・hash 不一致トラブルシュート |
| `docs/development.md` | ✅ 更新 | テスト数・モジュール構成（cli.py / config.py）・テスト戦略表・ロードマップ（v0.8 完了 / v0.9 以降） |
| `docs/handoff/008-auto-resume.md` | ✅ 新規作成 | 本ファイル |
| `docs/plans/008-auto-resume.md` | （本 WP では触れていない） | 計画書は WP-1/WP-2 フェーズで確定済み・docs のみの本 WP で追加修正は不要だった |
| `iroiro.toml.example` | （触っていない） | v0.8 は `iroiro.toml` 項目追加無し（`force_restart` は CLI 専用）・編集不要 |
| `docs/design.md` | （触っていない） | 歴史的記録・v0.8 の設計判断は Plan 008 に集約 |
| `iroiro/__init__.py` | （本 WP では触れていない） | `__version__` は follow-up で `"0.8.0"` に bump 済み（v0.7 と同じ手順・doc-code mismatch 解消済み） |

---

## 手動確認項目

リリース前にユーザー環境で確認すべき項目:

### auto-resume の実機確認（translate）

```bash
# progress.json が存在する状態で --resume 無しで再実行
uv run iroiro translate path/to/your_mod.xml --dry-run
# 期待: "Resuming: N translated, M failed" + "再開済（progress.json）: N" が表示される
```

### `--force-restart` の実機確認

```bash
# 既存 progress.json を破棄して fresh 開始
uv run iroiro translate path/to/your_mod.xml --dry-run --force-restart
# 期待: "discarding existing progress.json (--force-restart)" INFO + progress.json が削除される
# （dry-run でも削除される・明示的 opt-in）
```

### hash 不一致の exit 2 確認

```bash
# 入力ファイルを編集した状態で（--resume 無しで）再実行
uv run iroiro translate path/to/your_mod.xml --dry-run
# 期待: exit code 2 + "--force-restart" 案内付きの Error メッセージ
echo $?  # 2
```

### mcm での対称確認

```bash
uv run iroiro mcm path/to/your_mod_ENGLISH.txt --dry-run          # auto-resume
uv run iroiro mcm path/to/your_mod_ENGLISH.txt --dry-run --force-restart  # 削除 → fresh
```

### `--resume` deprecated INFO 確認

```bash
uv run iroiro translate path/to/your_mod.xml --dry-run --resume
# 期待: "INFO  --resume は既定動作になりました（no-op・非推奨・v0.9 で削除候補）"
# （動作は --resume 無しと同じ・exit code 0）
```

---

## 既知の問題

### `iroiro/__init__.py` の `__version__`（follow-up で `"0.8.0"` に bump 済み）

WP-3 では `iroiro/*` が forbidden だったため `"0.7.0"` のまま残っていたが、**PM 主導の follow-up で
`"0.8.0"` に bump 済み**（`iroiro/__init__.py`・v0.7 と同じ手順）。doc-code mismatch は解消済み。

### テスト isolation 強化の背景（stale `tests/fixtures/*.iroiro-progress.json` 問題）

**問題（Plan 008 §2.3・QA review Blocker）**: 既存テストのうち **fixture パスを直接 `_run_translate()` に渡すテスト**
（T36/T37/T39/T40/T64/T69/T70 相当）が、auto-resume 既定化で破綻した。

破綻メカニズム:
1. ローカル disk の `tests/fixtures/{tiny,tiny_crlf_bom,skip_records}.xml.iroiro-progress.json` が
   **hash 一致** の状態で存在した（過去のテスト実行で生成・`.gitignore` 対象なので git 非追跡・CI/新規 clone には無いが開発者環境には残る）。
2. auto-resume がこれらを取り込み → T36 は entry[0] が `failed` 扱い（MockTranslator 呼ばれず「【訳】」付かず→FAIL）・
   T69 は `translatable` が 2→0（dry-run 集計・FAIL）。
3. セッション内汚染: T36 実行が `mark_done` で `tiny.xml.iroiro-progress.json` を新規生成 → 後続の T37/T39 が
   auto-resume で取り込む（pytest 定義順で連鎖）。

**根本原因**: これらのテストは fixture を `tmp_path` に copy せず直接参照していた（T38 は copy する isolation パターンの模範）。
現状は `--resume` 必須なので progress.json が無視され潜在化していたが、auto-resume 既定化で顕在化した。

**解決（WP-1 スコープ拡張）**: 該当テストを T38 パターン（`shutil.copy(fixture, tmp_path)` → tmp_path 入力で
`_run_translate`）に揃えた。**アサーションは変更せず setup のみ**（テスト弱化ではなく isolation 強化）。
`.gitignore` の `*.iroiro-progress.json` エントリは既存のため追記不要。

> QA review は「commit 済み」と主張したが、実測では `.gitignore` 対象・`git ls-files` 空・**ローカル disk のみ**。
> 追跡の有無によらず isolation 修正は必須（CI は clean でも開発者環境の `uv run pytest` で破綻するため）。

### `--resume` が vestigial no-op になったことの保守上の注意

`RunConfig.resume` フィールド・`--resume` CLI フラグ定義（`translate` / `mcm` 両方）は残っているが、
ロジック（`_run` / `_run_mcm`）では **参照しない**（`if cfg.resume:` gate は削除済み・`cfg.resume` は deprecated INFO
を出すためだけに読む）。新規コードで `cfg.resume` を条件分岐に使わないこと（常に no-op になる）。
v0.9 で `--resume` フラグ・`RunConfig.resume` フィールドを削除する候補。

---

## 残 TODO（将来機能・v0.8 ではスコープ外）

- ✅ **`iroiro/__init__.py` の `__version__` bump**（`"0.8.0"` に bump 済み・follow-up で解消）
- **`--resume` フラグ / `RunConfig.resume` フィールドの削除**（v0.9 候補・vestigial no-op・直接構築箇所の churn に注意）
- **MCM 独自プロンプト / `[iroiro.mcm]` セクション**（v0.7 から持ち越し・`{N}` 保存はトークン検証で強制保証済み）
- **Fallout4 / Starfield の MCM 形式実データ検証**（v0.7 から持ち越し・構造同一想定）
- その他: `max_tokens` 設定・接続設定 6 項目の必須化検討・用語集機能・長文 BOOK の自動分割・
  実 LLM での品質レビュー用 diff 出力・SSTXMLRessources v3 対応・`--game` ゲーム選択機能・
  review-needed 状態の導入・`iroiro.toml` の親ディレクトリ遡り探索・選択的リトライ

---

## リスク

### 中リスク項目（破壊的変更・文書化済み）

- **hash 不一致・破損 progress.json が `--resume` 無しでも exit 2 になる**: 従来の「無視して fresh」を期待する利用者が
  エラーに驚く可能性。エラーメッセージで `--force-restart` を案内・README / usage.md の目立つ場所に明記（T-HASH-01 / T-CORRUPT-01 で検証）。
- **`--resume` 無しの再実行が fresh でなく resume になる**: 従来 fresh 開始を意図していた利用者は `--force-restart` が必要。
  README / usage.md の移行手順で明記。
- **dry-run + `--force-restart` が progress.json を削除する**: dry-run の副作用無し原則の例外。`--force-restart` は明示 opt-in
  であり docs で明記（T-FORCE-01 で検証）。

### 低リスク項目

- **`--resume` vestigial 化**: deprecated INFO で案内・v0.9 削除候補。新規コードで `cfg.resume` を条件分岐に使わない限り無害。
- **`RunConfig.force_restart` 追加**: 末尾かつデフォルト付きで既存の直接構築を壊さない（T で検証）。
- **`translate` / `mcm` 対称性**: 複製ブロックの片側漏れは T-MCM-AUTO / T-MCM-FORCE / T-MCM-HASH / T-MCM-CORRUPT / T-MCM-RETRY-WARN が検知。
- **I/O・翻訳エンジン・progress.json フォーマット**: 一切触っていない（回帰ゼロ・268 テスト green で保証）。

---

## ロールバックメモ

v0.8 は既定動作の変更で新規モジュール追加は無いため、ロールバックは差分 revert で完了する:

### v0.7 への戻し

1. `iroiro/cli.py` の v0.8 差分を revert（`--force-restart` フラグ定義 L187 / L597・resume ブロックの auto-resume 化 L316-355 / L720-753・
   `--resume` deprecated INFO L287-290 / L690-693・retry 警告条件 L351-355 / L748-753・hash/破損エラー catch の `--force-restart` 案内 L329-337 / L731-737）。
2. `iroiro/config.py` の v0.8 差分を revert（`RunConfig.force_restart` フィールド L61・`resume` docstring の vestigial 注記 L29-31, L53-55）。
3. `tests/test_cli.py` の v0.8 差分を revert（新規テスト + isolation 強化の setup 変更）。
   ※ isolation 強化（tmp_path copy）は v0.7 でも有用だが、v0.7 では `--resume` 必須で progress.json が無視されるため
   元の直接参照に戻しても動く。アサーションは不変のため setup のみの revert で可。
4. ドキュメント（README / usage / development / 本 handoff / Plan 008）の v0.8 記述を revert。
5. progress.json は `--force-restart` で削除されたもの以外は残っているため、進捗の復旧は不要（v0.7 では `--resume` で再開）。

---

## 次の担当者・エンジニアへのメモ

### v0.8 リリース前の対応推奨

1. ✅ **`iroiro/__init__.py` の `__version__` bump**（`"0.8.0"` に bump 済み・follow-up で解消・v0.7 と同じ手順）。
2. **ユーザー判断事項**: `iroiro.toml.example` の作業ツリー状態（v0.7 から持ち越し・ユーザー由来のコメント削除）は
   v0.8 では触っていない。v0.8 は `iroiro.toml` 項目追加無し（`force_restart` は CLI 専用）のため `iroiro.toml.example` 編集は不要。

### v0.9 以降の開発への引き継ぎ

- **`--resume` 削除を行う場合**: `iroiro/cli.py` の `--resume` フラグ定義（`translate` / `mcm` 両方）・`RunConfig.resume` フィールド・
  deprecated INFO ログ（L287-290 / L690-693）を削除。直接 `RunConfig(resume=...)` を構築するテスト/スクリプトの churn に注意
  （`resume` が必須位置引数でなければフィールド削除は安全・`slots=True` dataclass のフィールド順序に注意）。
- **resume ブロックを触る場合**: `translate`（`_run`）と `mcm`（`_run_mcm`）の resume ブロックは **複製構造**。
  片側だけ修正するとパリティが崩れるため、両方を対称に変更すること（T-MCM-* シリーズが検知）。
- **progress.json フォーマット / `load_existing` を触る場合**: 本件では I/O に手を入れていない。フォーマット変更は
  `input_hash` / `skip_records_fingerprint` との整合・旧 progress.json との互換性に注意（Plan 008 §4 非ゴール）。

### テスト・CI の継続保証

- **T-AUTO-01**（progress.json 有り・`--resume` 無しで自動 resume）が auto-resume 既定化を pin する。resume ブロックを触る場合は通すこと。
- **T-FORCE-01**（dry-run + `--force-restart` で progress.json が削除される）が削除 semantics を pin する。
- **T-HASH-01**（hash 不一致・`--resume` 無しで exit 2）が破壊的変更を pin する。これを弱体化してはいけない。
- **T-MCM-HASH / T-MCM-CORRUPT / T-MCM-RETRY-WARN** が mcm 側のパリティを pin する（複製ブロックの片側漏れ検知）。
- **isolation 強化後の既存テスト**（T36/T37/T39/T40/T64/T69/T70）は tmp_path copy で実行される。fixture を直接参照する書き方に
  戻さないこと（auto-resume で stale progress.json に汚染される）。

### 関連資料

- [Plan 008](../plans/008-auto-resume.md) — 本 v0.8 の設計判断・却下代替案の経緯・仮定台帳
- [Plan 004](../plans/004-retry-failed.md) — `--retry-failed` の原著（resume 前提・本件で警告条件を調整）
- [詳細な使い方](../usage.md) — 「自動レジューム化と移行（v0.8）」節・「再開」節・hash 不一致トラブルシュート
- [開発者向け](../development.md) — ロードマップ v0.8・テスト戦略表
