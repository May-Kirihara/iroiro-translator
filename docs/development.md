# 開発者向け

iroiro-translator の開発環境・テスト・モジュール構成・ロードマップ。設計の背景は
[設計判断](design.md) を、実装の経緯は [実装計画](plans/001-initial.md) を参照。

---

## 開発環境セットアップ

### 必要環境

- **Python 3.12+**（`.python-version` 参照）
- **[uv](https://docs.astral.sh/uv/)** — Python パッケージ・環境管理

### セットアップ

```bash
git clone <repository-url> iroiro-translator
cd iroiro-translator
uv sync           # dev extras（pytest / ruff / mypy）を含めて依存関係を同期
```

`uv sync` は `uv.lock` に基づいて `.venv/` を構築する。以降のコマンドは `uv run` 経由で
仮想環境内のツールを呼び出す。

---

## テスト・品質チェック

### テスト全実行

```bash
uv run pytest                          # 268 テスト（v0.8 で +22件: auto-resume / --force-restart / hash 不一致 exit 2 / 破損 progress.json / retry 警告条件変更 / MCM error-path パリティ T-MCM-HASH/CORRUPT/RETRY-WARN・v0.7 までは 246 件）
uv run pytest -k "xml_io"              # 個別実行（キーワード指定）
uv run pytest --tb=no -q               # 簡易出力
```

テストは `httpx.MockTransport` ベースのモック LLM を使用するため、ネットワーク接続不要で実行できる。
テストケース ID（T1-T55）と実装計画 §7 の対応は [実装計画](plans/001-initial.md#7-テスト戦略) を参照。

### リント・型チェック

```bash
uv run ruff check iroiro/ tests/       # リント（E/F/W/I/B/UP ルール）
uv run mypy iroiro                     # 型検査（iroiro/ のみ・strict ではない）
```

- ruff 設定: `pyproject.toml` の `[tool.ruff]` / `[tool.ruff.lint]` 参照
- mypy 設定: `pyproject.toml` の `[tool.mypy]` 参照。段階的型導入（`iroiro/` のみ検査）

---

## モジュール構成

```
iroiro/
├── __init__.py        # パッケージ初期化・__version__（v0.8: 0.8.0）
├── __main__.py        # python -m iroiro エントリポイント
├── cli.py             # typer ベースの CLI。translate サブコマンド・--retry-failed フラグ・_apply_existing 拡張（v0.4）・RunConfig に PromptConfig 追加・--config help 更新（v0.5）・--no-skip-default-records 廃止・--skip-records を str|None=None の完全置換セマンティクスに変更（v0.6）・mcm サブコマンド + _run_mcm + _default_mcm_output_path 追加（v0.7）・auto-resume 既定化 + --force-restart フラグ + --resume no-op（deprecated INFO）・retry 警告条件を「progress.json 未 load」に変更（v0.8・translate/mcm 対称）
├── config.py          # RunConfig dataclass（retry_failed 含む・v0.4 / force_restart 含む・v0.8）/ load_config（iroiro.toml ローダー・v0.3・v0.5 で必須化）/ _validate_bool（v0.4）/ _validate_system_prompt / _validate_reject_phrases / _validate_rec_hints（v0.5）/ _validate_skip_records（v0.6・skip_records 必須化・frozenset[str] 返却）・RunConfig.resume に vestigial 注記（v0.8・auto-resume 既定化で no-op）
├── errors.py          # IroiroError 共通例外
├── escape.py          # プレースホルダ検出（extract_tokens）/ 整合性検証（tokens_match）・{0} {1} 等 MCM 数値プレースホルダ保護追加（v0.7）
├── logging.py         # rich ベースの進捗表示ヘルパ
├── models.py          # StringEntry / FileFormat dataclass
├── progress.py        # ProgressWriter（asyncio.Lock + 原子書き込み）/ ProgressData・mark_failed 重複チェック・mark_done failed クリア（v0.4）
├── translator.py      # Translator / ApiConfig / PromptConfig（v0.5）/ is_translation_needed（OpenAI 互換クライアント・v0.5 でハードコード定数を完全削除し PromptConfig 注入・v0.6 で DEFAULT_SKIP_RECORDS 定数を完全削除し is_translation_needed の skip_records 引数を必須化）
├── xml_io.py          # parse_xml / serialize_xml（BOM/CRLF/宣言保持）
└── mcm_io.py          # parse_mcm / serialize_mcm / McmFormat（Skyrim MCM 翻訳 TXT の I/O・v0.7 新規・BOM/改行/エンコーディング保存 + 改行正規化）
```

各モジュールの責務は [実装計画 §5.3](plans/001-initial.md) を参照。コードを読む推奨順序:

1. `iroiro/cli.py` — 全体フロー（parse → resume → dry-run → translate → serialize）
2. `iroiro/models.py` — `StringEntry` / `FileFormat` の dataclass
3. `iroiro/xml_io.py` — BOM/CRLF/宣言保持戦略の中核。最も注意深くレビューすべき箇所
4. `iroiro/escape.py` + `iroiro/translator.py` — プレースホルダ保護と LLM クライアント
5. `iroiro/progress.py` — 並行安全な再開機能

---

## テスト戦略の概要

3層構造で網羅する:

### 1. ユニットテスト（`tests/test_*.py`）

各モジュール単位のテスト。`httpx.MockTransport` を `openai.AsyncOpenAI(http_client=...)` に
注入することで、LLM への実リクエストを送らずにプロトコル・post-processing・エラーハンドリングを検証。

| テストファイル | 対象 |
|---|---|
| `tests/test_xml_io.py` | XML I/O 周辺（T1-T10, T47-T53, T68）。round-trip・BOM/CRLF/宣言保持・CDATA/comment 検出・空要素展開 |
| `tests/test_mcm_io.py` | MCM TXT I/O 周辺（v0.7 新規・T-MCM-01〜T-MCM-RESUME）。parse/serialize round-trip・UTF-16 LE/BE/UTF-8 BOM 受入・支配的改行正規化・末尾改行保存・`{0}` プレースホルダ・パススルー行・skip/fail 時英文保持・resume の index 対応 |
| `tests/test_escape.py` | プレースホルダ検出・整合性検証（T11-T18, T45）。v0.7 追加: `{0}` `{1}` 等 MCM 数値プレースホルダ検出・欠落検知・既存トークン回帰無し・`{{0}}` 過剰マッチ pin（T-ESC-N*） |
| `tests/test_progress.py` | 並行安全な progress.json 読み書き（T19-T25, T46, T50, T77-T80, T83）。v0.4 追加: `mark_failed` 重複チェック・`mark_done` failed クリア（T118-T121） |
| `tests/test_translator.py` | 翻訳エンジン・post-processing・リトライ（T26-T34, T41-T44, T51, T56-T63, T71-T76, T81/T81b, T85-T87b）。v0.5 追加: `PromptConfig` 注入・カスタム `system_prompt` / `reject_phrases` / `rec_hints` の検証・空 `rec_hints` 時の `_build_user_message`（T143-T145・T157）。既存 `Translator` 構築箇所の signature 追随。v0.6 追加: `DEFAULT_SKIP_RECORDS` import 削除・`is_translation_needed` の `skip_records` 必須化検証（`TypeError` 確認）・`default_skip_records` fixture（14件）使用（T165・既存 T56-T63 を追随） |
| `tests/test_config.py` | `iroiro.toml` ローダー `load_config`（T88-T102・v0.3）。パス解決・型/値域検証・bool 拒否・未知キー警告。v0.4 追加: `retry_failed` 厳格 bool 検証（T110-T113）。v0.5 追加: `system_prompt` / `reject_phrases` / `[iroiro.rec_hints]` 必須化・厳格型検証・`iroiro.toml` 無しエラー・`[iroiro]` セクション無しエラー・quoted REC key・`iroiro.toml.example` の tomllib parse 検証（T132-T142, T149-T156・既存 T88/T94/T103 等の v0.5 化）。v0.6 追加: `skip_records` toml 読み込み・必須化検証・型検証（`list[str]`・各要素非空・大文字正規化）・空リスト `[]` 許可・重複除去（T158-T164・既存 fixtures に `skip_records` 追記） |
| `tests/test_cli.py` | E2E（T36-T40, T64-T67, T69-T70, T82, T103-T109）。`CliRunner` 経由で `translate` サブコマンドを検証。v0.4 追加: `_apply_existing` の retry_failed 分岐（T114-T117）・`--retry-failed` / `--no-retry-failed` の CLI 統合（T123-T129）。v0.5 追加: `iroiro.toml` 無し dry-run エラー・3 新項目欠損エラー・3 新項目あり dry-run 正常・CLI → `PromptConfig` 注入の検証（T146-T148, T154）。v0.6 追加: `--skip-records` の 3 状態（省略=toml使用 / `""`=空set / 非空=完全置換）・CLI 側正規化・`--no-skip-default-records` 廃止（未知オプション）・`iroiro.toml.example` の v0.6 内容検証（T166a-T167, T168）。**v0.8 追加**: auto-resume 既定化（progress.json 有り・`--resume` 無しで自動 resume）・`--force-restart`（dry-run で progress.json 削除 / 非 dry で旧エントリ無し / `--resume` との同時指定で force 優先）・hash 不一致・破損 progress.json の exit 2（`--resume` 無しでも）・retry 警告条件の「progress.json 未 load」化・MCM error-path パリティ（T-MCM-HASH/CORRUPT/RETRY-WARN）・dry-run 自動 resume 表示。**既存テストの isolation 強化**: fixture パスを直接 `_run_translate()` に渡すテスト（T36/T37/T39/T40/T64/T69/T70 相当）を T38 パターン（`shutil.copy(fixture, tmp_path)` → tmp_path 入力）に変換（アサーション不変・setup のみ。`tests/fixtures/*.iroiro-progress.json` がローカル disk に残っていても auto-resume で破綻しない） |

### 2. フィクスチャ（`tests/fixtures/`）

XML I/O の検証用に小さなサンプル XML を同梱（実データ由来でない自作フィクスチャ）:

- `tiny.xml` — 数件、alias / `<br>` / `%{...}` / 空文字 含む
- `tiny_crlf_bom.xml` — BOM + CRLF の実物コピー
- `japanese_source.xml` — 既に日本語の Source を含む
- `long_source.xml` — `max-chars` 超過
- `with_comment.xml` / `with_cdata.xml` — コメント・CDATA 検出用
- `skip_records.xml` — HDPT/WEAP/MGEF/RACE/BPTD/ACTI/空/日本語 の8エントリを含むテスト用 XML（BOM + CRLF + `standalone="yes"`）
- `mcm_tiny.txt`（v0.7 新規）— 小さな MCM TXT（UTF-16 LE BOM / CRLF / `{0}` プレースホルダ / 空行 / タブ無し行 含む・自作）
- `mcm_lf.txt`（v0.7 新規）— MCM TXT（LF / BOM 無し / 末尾改行あり・改行・BOM バリエーション用・自作）
- `iroiro_*.toml` — `load_config` 検証用の TOML フィクスチャ。v0.3: `iroiro_full` / `iroiro_partial` / `iroiro_broken` / `iroiro_not_table` / `iroiro_other_only` / `iroiro_unknown_key` / `iroiro_empty_base` / `iroiro_max_chars_zero` の8種。v0.4 追加: `iroiro_retry_true` / `iroiro_retry_false` の2種（`retry_failed` 厳格 bool 検証用・T110/T111）。v0.5 追加: `iroiro_v05_full` / `iroiro_v05_missing_prompt` / `iroiro_v05_missing_reject` / `iroiro_v05_missing_rec_hints` / `iroiro_v05_empty_reject` / `iroiro_v05_custom_prompt` の6種（3 新項目の必須検証・quoted REC key）。既存 7 fixtures に 3 新項目を追記（必須チェックで fail しないよう）。v0.6 追加: `iroiro_v06_missing_skip_records`（必須チェック検証用）・`iroiro_v06_custom_skip`（カスタム skip リスト検証用）。既存 13 fixtures に `skip_records` を追記（必須チェックで fail しないよう）

### 3. E2E（実 LLM）

実 LLM による E2E は CI 上では実施せず、ユーザー環境での手動検証に委ねる。
v0.1 では Gemma 4 12B / llama.cpp server で 679 エントリの実データ検証を完了済み
（[引き継ぎメモ](handoff/001-initial.md) 参照）。

---

## 貢献

プルリクエストを歓迎する。

### 進め方

1. Issue で方針を相談（大きな変更は特に）
2. フォーク → ブランチ作成 → 実装
3. `uv run pytest` / `uv run ruff check` / `uv run mypy iroiro` が全てクリーンであることを確認
4. テストを **weakning / skip しない**（正当な理由がある場合のみ `@pytest.mark.skipif`）
5. PR 作成（1 PR = 1 論理的変更）

### コーディング規約

- **日本語** でコメント・docstring・説明文を書く
- **英語** で技術識別子（関数名・CLI フラグ・API名・XMLタグ・ファイルパス）を書く
- ruff ルール: `E` / `F` / `W` / `I` / `B` / `UP`（`pyproject.toml` 参照）
- mypy は strict ではないが `iroiro/` は型チェック必須
- アプリ側での XML エスケープは絶対にしない（lxml 任せ・二重エスケープ防止）

---

## コミット運営

Conventional Commits 風のプレフィックスを使用:

| プレフィックス | 用途 |
|---|---|
| `feat:` | 新機能 |
| `fix:` | バグ修正 |
| `chore:` | ビルド・依存・設定等の雑務 |
| `docs:` | ドキュメント変更 |
| `refactor:` | リファクタリング（機能変更なし） |
| `test:` | テスト追加・修正 |
| `perf:` | パフォーマンス改善 |

例: `feat: 用語集機能を追加`, `fix: 空要素展開の regex が属性付きタグを取りこぼす問題を修正`

---

## ロードマップ

v0.1 は英→日バッチ翻訳の安定版。以降は以下を予定（PR 歓迎）:

### v0.2（✅ 完了）

- **翻訳スキップ REC 型** — `DEFAULT_SKIP_RECORDS`（12件）+ `--no-skip-default-records` / `--skip-records` CLI フラグ。詳細は [docs/plans/002-skip-records.md](plans/002-skip-records.md) と [docs/handoff/002-skip-records.md](handoff/002-skip-records.md)。

### v0.3（✅ 完了）

- **設定ファイル（`iroiro.toml`）** — LLM エンドポイント・API キー・モデル名・タイムアウト・並列数・`max_chars` のデフォルト値を `iroiro.toml` に外部化。`--config PATH` フラグ・cwd 自動検出。詳細は [docs/plans/003-config-file.md](plans/003-config-file.md) と [docs/handoff/003-config-file.md](handoff/003-config-file.md)。

### v0.4（✅ 完了）

- **failed エントリの再試行** — `--retry-failed` / `--no-retry-failed` CLI フラグ・`iroiro.toml` の `retry_failed` 設定。`--resume` 時に `failed` エントリを再翻訳対象に戻す。優先順位は CLI フラグ ＞ `iroiro.toml` ＞ 内蔵デフォルト `False`（後方互換）。`mark_done` で `failed` をクリア（不変性 entries ∩ failed = ∅）・`mark_failed` 重複チェック。詳細は [docs/plans/004-retry-failed.md](plans/004-retry-failed.md) と [docs/handoff/004-retry-failed.md](handoff/004-retry-failed.md)。

### v0.5（✅ 完了）

- **LLM プロンプト・エラー判定語句の完全 toml 化** — `system_prompt` / `reject_phrases` / `[iroiro.rec_hints]` の LLM 挙動中核 3 要素を `iroiro/translator.py` から完全削除し `iroiro.toml` に移行（案 α）。`iroiro.toml` の必須化（`--dry-run` 含む全操作）・`PromptConfig` dataclass の導入・3 新項目の厳格型検証。後方互換性の破れ（`iroiro.toml` 無しで動く v0.4 までの挙動を廃止）。詳細は [docs/plans/005-llm-config.md](plans/005-llm-config.md) と [docs/handoff/005-llm-config.md](handoff/005-llm-config.md)。

### v0.6（✅ 完了）

- **Fallout4 / Starfield 対応 + skip_records の toml 化** — `DEFAULT_SKIP_RECORDS` 定数を `iroiro/translator.py` から完全削除し `iroiro.toml` の `skip_records`（必須）に移行（案 α 徹底版・v0.5 と同じ哲学）。skip リストを 12件 → **14件**（`FLST:FULL` / `KYWD:FULL` 追加・NG ガイド §9.1 Conservative Preset・EDID 抜き）に拡充。`[iroiro.rec_hints]` を NG ガイド §4 に基づき 3 ゲーム共通の翻訳候補レコード（`AMMO:FULL` / `MISC:FULL` / `WRLD:FULL` / `INFO:NAM1` 等）に拡充。CLI `--no-skip-default-records` 廃止・`--skip-records` を `str | None = None` の完全置換セマンティクス（3 状態）に変更。`is_translation_needed` の `skip_records` 引数を必須化。後方互換性の破れ（既存 `iroiro.toml` に `skip_records` 追記必要・`progress.json` fingerprint 不整合で resume 停止）。詳細は [docs/plans/006-multi-game.md](plans/006-multi-game.md) と [docs/handoff/006-multi-game.md](handoff/006-multi-game.md)。

### v0.7（✅ 完了）

- **Skyrim MCM 翻訳 TXT 対応** — `iroiro mcm INPUT.txt` サブコマンドで SkyUI MCM 翻訳ファイル（`*_ENGLISH.txt` 系・UTF-16 LE + BOM）の値を英→日翻訳。新モジュール `iroiro/mcm_io.py`（`parse_mcm` / `serialize_mcm` / `McmFormat`）・`escape.py` の共有 regex に `{0}` `{1}` 等の数値プレースホルダ保護を追加。**既存 XML `translate` パスは1行も変更せず回帰ゼロ**（サブコマンド分離）。`--skip-records` は MCM には存在しない（REC 概念無し・指定すると exit 2 で拒否）。出力デフォルト `<input>.translated.txt`。フォーマット保存（BOM/エンコーディング/末尾改行）+ 改行正規化。skip/fail 時の出力値は英文のまま（`original_dest=source`・data-loss 無し）。詳細は [docs/plans/007-mcm-translation.md](plans/007-mcm-translation.md) と [docs/handoff/007-mcm-translation.md](handoff/007-mcm-translation.md)。

### v0.8（✅ 完了）

- **自動レジューム既定化 + `--force-restart`** — progress.json が存在する場合、`--resume` フラグ **無しで自動レジューム** する（従来は `--resume` 必須・忘れると上書きで進捗消失の事故）。`--force-restart`（新規）で既存 progress.json を **破棄（削除）** して最初から（dry-run でも削除・明示的 opt-in）。`--resume` は後方互換 no-op（deprecated INFO・v0.9 削除候補）。**破壊的変更**: hash 不一致・破損 progress.json が `--resume` 無しでも **exit 2 で停止** するようになった（従来は無視＝fresh start・data integrity 保護）。エラーメッセージに `--force-restart` 案内を付加。`--retry-failed` の警告条件を「`--resume` 無し」→「progress.json が load されなかった」に変更。`translate` / `mcm` 両サブコマンドで対称。`RunConfig.force_restart` 追加（デフォルト False・末尾かつデフォルト付きで後方互換）。既存テストの isolation 強化（fixture 直接参照→tmp_path copy・T38 パターン）。詳細は [docs/plans/008-auto-resume.md](plans/008-auto-resume.md) と [docs/handoff/008-auto-resume.md](handoff/008-auto-resume.md)。

### v0.9 以降（予定）

- **`--resume` フラグの削除候補** — v0.8 で自動レジュームが既定化し `--resume` は vestigial no-op。後方互換期間を経て v0.9 で削除を検討（`RunConfig.resume` フィールド・CLI フラグ定義の撤去）
- **`max_tokens` 設定** — LLM の生成トークン上限を `iroiro.toml` / CLI フラグで調整可能に（`--ctx-size` 不足の空応答対策・v0.4 でスコープ外）
- **接続設定 6 項目の必須化検討** — `api_base` 等の接続設定も v0.5 と同様に `iroiro.toml` 必須にするか（v0.5 では LLM 挙動中核のみ必須化・接続設定は省略可のまま）
- **MCM 独自プロンプト検討** — v0.7 は既存 `system_prompt` を再利用。`{N}` 保存行の追記や MCM 専用 `[iroiro.mcm]` セクション・`first-line-only` 制限の改善（長文 description 系）を検討
- 用語集機能（JSON/YAML形式・人間メンテ可能）
- 長文 BOOK の自動分割
- 実 LLM での品質レビュー用 diff 出力
- Fallout4 / Starfield の MCM 形式実データ検証（構造は同一想定だが v0.7 では Skyrim のみ保証）
- SSTXMLRessources v3 対応
- **`--game skyrim|fallout4|starfield` ゲーム選択機能** — v0.6 では 3 ゲーム共通デフォルトのみ提供・ゲーム別の skip リスト / rec_hints プリセット切り替え（Conservative / Translation-Friendly / Starfield-Friendly）は将来機能
- **review-needed 状態の導入** — iroiro は `translate` / `skip` の 2 状態だが、NG ガイド §5 Review-Needed List（`OMOD:FULL` / `COBJ:*` / `PERK:FULL` / `AVIF:FULL` / `GMST:*` / `LSCR:*` / `TERM:*` 等）を扱うための第 3 状態（v0.6 ではスコープ外）
- `iroiro.toml` の親ディレクトリ遡り探索
- 選択的リトライ（`--retry-failed-only INDEX` 等・v0.4 は全 failed 一括のみ）
- CI での `iroiro.toml.example` 構文検証（T155 / T168 で回帰防止済み・継続保証）
