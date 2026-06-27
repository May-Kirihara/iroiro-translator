# 引き継ぎメモ: iroiro-translator v0.1 初期実装 (001-initial)

- 作成日: 2026-06-28
- 計画書: [`docs/plans/001-initial.md`](../plans/001-initial.md) v0.6
- 状態: **done**

---

## ステータス

| 項目 | 値 |
|---|---|
| 状態 | done-with-notes |
| 日付 | 2026-06-28 |
| 担当 | PM agent + implementer |
| 状態 | done |
| 日付 | 2026-06-28 |
| 担当 | PM agent + implementer + ユーザー実機検証 |
| 概要 | Skyrim MOD xTranslator 形式 XML を OpenAI 互換 LLM で英→日翻訳するバッチ CLI `iroiro` v0.1 の初期実装が完了。WP-1（テスト）/ WP-2（コア）/ WP-3（ドキュメント）の3 Work Package を直列で完了。73件のテスト（T1-T53 + XXE対策 T54/T55 + post-processing 補助）が全て green。ユーザー提供の MOD XML（679エントリ）で dry-run 正常動作を確認済み。**ユーザー環境で実 LLM（Gemma4 12B / llama.cpp）による E2E 翻訳が成功**し、progress / 出力XML が正常生成されることを確認済み。 |

---

## 変更内容

本リリースで新規作成・追記されたファイル群。

### 新規作成

#### `iroiro/` パッケージ（11モジュール）

| ファイル | 役割 |
|---|---|
| `iroiro/__init__.py` | パッケージ初期化・`__version__ = "0.1.0"` |
| `iroiro/__main__.py` | `python -m iroiro` エントリポイント |
| `iroiro/cli.py` | `typer` ベースの CLI エントリ。`translate` サブコマンド |
| `iroiro/config.py` | `RunConfig` dataclass |
| `iroiro/models.py` | `StringEntry`, `FileFormat` dataclass |
| `iroiro/xml_io.py` | `parse_xml` / `serialize_xml`（BOM/CRLF/宣言保持） |
| `iroiro/escape.py` | `extract_tokens` / `tokens_match`（プレースホルダ保護） |
| `iroiro/translator.py` | `Translator` / `ApiConfig` / `is_translation_needed`（OpenAI 互換クライアント） |
| `iroiro/progress.py` | `ProgressWriter` / `ProgressData` / `compute_input_hash`（並行安全な再開機能） |
| `iroiro/logging.py` | `rich` ベースの進捗表示ヘルパ |
| `iroiro/errors.py` | `IroiroError` 共通例外 |

#### `tests/`（73テスト + 7フィクスチャ）

| ファイル | 内容 |
|---|---|
| `tests/conftest.py` | 共通フィクスチャ・モック LLM ヘルパ |
| `tests/test_xml_io.py` | XML I/O 周辺（T1-T10, T47-T53）。round-trip・BOM/CRLF/宣言保持・CDATA/comment 検出・空要素展開 |
| `tests/test_escape.py` | プレースホルダ検出・整合性検証（T11-T18, T45） |
| `tests/test_progress.py` | 並行安全な progress.json 読み書き（T19-T25, T46, T50） |
| `tests/test_translator.py` | 翻訳エンジン・post-processing・リトライ（T26-T34, T41-T44, T51）。モックは `httpx.MockTransport` を注入 |
| `tests/test_cli.py` | E2E（T36-T40）。`CliRunner` 経由で `translate` サブコマンドを検証 |

##### フィクスチャ

- `tests/fixtures/tiny.xml` — 数件、alias / `<br>` / `%{...}` / 空文字 含む
- `tests/fixtures/tiny_crlf_bom.xml` — BOM + CRLF の実物コピー
- `tests/fixtures/japanese_source.xml` — 既に日本語の Source を含む
- `tests/fixtures/long_source.xml` — `max-chars` 超過
- `tests/fixtures/with_comment.xml` — XML コメント検出用
- `tests/fixtures/with_cdata.xml` — CDATA 検出用

#### 設定ファイル類

- `pyproject.toml` — PEP 621 形式。依存: `openai>=1.0`, `httpx`, `lxml`, `typer>=0.9`, `rich>=13.0`。
  dev 依存: `pytest>=8.0`, `pytest-asyncio>=0.23`, `ruff>=0.6`, `mypy>=1.10`。
  エントリポイント: `iroiro = "iroiro.cli:main"`。
- `.python-version` — `3.12`

#### ドキュメント

- `README.md` — 既存の暫定 README を全面的に書き直し（プロジェクト概要・CLI フラグ一覧・
  設定例・安全性・トラブルシュート・制限事項）
- `docs/plans/001-initial.md` — 実装計画書 v0.6
- `docs/handoff/001-initial.md` — 本ファイル

### 既存ファイルへの追記

- `.gitignore` — 末尾に iroiro 実行生成物を追加:
  - `*.translated.xml`
  - `*.iroiro-progress.json`
  - `*.iroiro-progress.json.tmp`

---

## 変更理由

Skyrim MOD の英語版 XML を日本語化する作業は、xTranslator で手動で行うにはエントリ数が
膨大（ユーザー提供の MOD XML だけで 679件）で反復作業が辛い。ローカル LLM でバッチ翻訳しつつ、
xTranslator 形式のバイトレベルフォーマット（BOM/CRLF/宣言）を厳密に保持して相互運用性を
保つツールが欲しい、というユーザー要件を満たすため。

特に以下を重視した:

1. **xTranslator との相互運用性** — 出力 XML を xTranslator がそのまま読めること。
   これを実現するため BOM / CRLF / `standalone="yes"` 宣言 / 空要素 `<X></X>` 形式を保持する。
2. **破壊しない設計** — 翻訳失敗時・スキップ時に元の `<Dest>` を保持し、`<Source>` で上書きしない。
3. **再開可能性** — `progress.json`（原子的書き込み + 並行安全）で巨大 MOD の途中再実行を可能にする。
4. **ローカル LLM 前提** — OpenAI 互換 API + ローカル（llama.cpp / Gemma 4 12B）でプライバシーとコストを確保。

詳細な設計判断・却下代替案は計画書 §3 / §15 を参照。

---

## Work packages

### WP-1-tests

| 項目 | 値 |
|---|---|
| Scope | テスト・フィクスチャを先に実装し、実装の受け入れ基準を固定（テスト駆動） |
| Status | done |
| Files | `tests/conftest.py`, `tests/fixtures/*.xml`（7件）, `tests/test_{xml_io,escape,progress,translator,cli}.py` |
| Verification | WP-2 完了後に `uv run pytest` で全 green（73/73）|
| Remaining risks | low。実 LLM E2E は未実施（WP-1 範囲外） |

### WP-2-core

| 項目 | 値 |
|---|---|
| Scope | `iroiro/` パッケージ本体 + `pyproject.toml` + `.python-version` + `.gitignore` 追記 |
| Status | done |
| Files | `iroiro/` 11モジュール, `pyproject.toml`, `.python-version`, `.gitignore` |
| Verification | `uv run pytest` 全 green、ユーザー提供の MOD XML で dry-run 実行時に 679件正常表示 |
| Remaining risks | medium。実 LLM での品質検証が未実施。llama.cpp の model alias はユーザー環境依存 |

### WP-3-docs

| 項目 | 値 |
|---|---|
| Scope | README.md（全面書き直し）+ 本 handoff メモ |
| Status | done |
| Files | `README.md`, `docs/handoff/001-initial.md` |
| Verification | README の CLI フラグ一覧が `iroiro/cli.py` 実装と完全一致。デフォルト値を `iroiro translate --help` 出力と照合 |
| Remaining risks | low |

---

## 触ったファイル

### 新規作成

```
iroiro/__init__.py
iroiro/__main__.py
iroiro/cli.py
iroiro/config.py
iroiro/errors.py
iroiro/escape.py
iroiro/logging.py
iroiro/models.py
iroiro/progress.py
iroiro/translator.py
iroiro/xml_io.py
pyproject.toml
.python-version
tests/conftest.py
tests/fixtures/tiny.xml
tests/fixtures/tiny_crlf_bom.xml
tests/fixtures/japanese_source.xml
tests/fixtures/long_source.xml
tests/fixtures/with_comment.xml
tests/fixtures/with_cdata.xml
tests/test_cli.py
tests/test_escape.py
tests/test_progress.py
tests/test_translator.py
tests/test_xml_io.py
docs/plans/001-initial.md
docs/handoff/001-initial.md
README.md（暫定1行から全面書き直し）
```

### 既存ファイル修正

```
.gitignore（末尾に iroiro 実行生成物を追記）
README.md（暫定1行から全面書き直し）
```

---

## テスト

### 実行したコマンド

```bash
uv sync
uv run pytest --tb=no -q
```

### 結果

```
73 passed in 1.15s
```

- T1-T53 のテストケース（実装計画 §7 参照）が全て green
- フィクスチャベース・`httpx.MockTransport` モック LLM 使用。ネットワーク接続不要
- XML I/O の round-trip / BOM・CRLF・宣言保持 / CDATA・comment 検出 / 空要素展開 を網羅
- progress.json の並行安全（`asyncio.Lock` + 原子書き込み）を `--concurrency 4` 相当で検証
- post-processing（ラベル削除・フェンス削除・複数行最初の行のみ・リストマーカー削除）を検証
- リトライ（最大3回・指数バックオフ）の成功・最終失敗ケースを検証

### ユーザー環境で実施済み（2026-06-28）

- **実 LLM による E2E 翻訳検証** ✅
  - ユーザー環境（Gemma4 12B Q4_K_M / llama.cpp server ポート8081）でユーザー提供の MOD XML（679エントリ）を処理。
  - progress ファイル（`<input>.iroiro-progress.json`）と出力 XML（`<input>.translated.xml`）が正常生成されることを確認。
  - モックベースで検証した protocol/post-processing/エラーハンドリングが実機でもそのまま成立した。

---

## ドキュメント

### 更新

- `README.md` — プロジェクト概要・主な機能・必要環境・インストール・使い方（CLI フラグ一覧・
  デフォルト値表）・設定例（llama.cpp 起動・他サーバー）・安全性の説明（失敗時 `<Dest>` 保護・
  長文スキップ・CDATA/comment 非サポート）・トラブルシュート・制限事項・ライセンス・貢献。
- `docs/handoff/001-initial.md` — 本ファイル。

### 未更新

- なし。計画書 §10 で想定された全ドキュメントを更新済み。

---

## 手動確認

実施済み:

- ユーザー提供の MOD XML（679エントリ）で dry-run を実行し、
  **679エントリ**が正常にパースされ、件数集計（翻訳対象 32 / スキップ 647 / 長文超過 0）
  が表示されることを確認。BOM=True / `newline='\r\n'` / encoding=UTF-8 も正しく検出。
- `uv run iroiro translate --help` で全 CLI フラグとデフォルト値が想定通り表示されることを確認。
- `file <input>.xml` で入力が UTF-8 BOM + CRLF であることを確認。

未実施:

- 実 LLM（llama.cpp server / Gemma 4 12B）による実際の翻訳実行と、出力 XML の xTranslator での再読込確認。
- 環境: handoff 時点でローカル LLM サーバーが未起動のため。

---

## 既知の問題

1. **実 LLM での品質検証が未実施**
   - モック LLM ベースでプロトコル・post-processing・エラーハンドリングは検証済み。
   - 実モデル（Gemma 4 12B 相当）が日本語品質・トークン保持・`model` パラメータの面で
     期待通り動くかは、ユーザー環境での実検証が必要。

2. **llama.cpp の `model` alias はユーザー環境依存**
   - llama.cpp server が受ける `model` パラメータは `--alias` / `--host` 起動オプションに依存。
   - 既定値 `ggml-org/gemma-4-12B-it-GGUF:Q4_K_M` で繋がらない場合は `--model` で調整が必要
     （README のトラブルシュートに明記）。

3. **長文 BOOK エントリのスキップ**
   - `--max-chars`（既定 4000）超過の `<Source>` はスキップされる。ユーザー提供の MOD XML では
     該当なし。長い書籍本文を持つ MOD では一部エントリが未翻訳で残る可能性がある。

---

## 残 TODO

- **v0.2 用語集機能** — 用語の統一訳を指定できる仕組み。計画書 §4.2 で見送り。
- **長文の自動分割** — `--max-chars` 超過時にチャンク化して翻訳する機能。計画書 §4.2 で見送り。
- **実 LLM E2E テストの追加** — CI 上でローカル LLM を動かすか、記録済みレスポンスで再生する
  E2E テスト。現在は `tests/test_translator.py` のモックベースのみ。
- **SSTXMLRessources v3 / Interface 形式対応** — 将来機能。

---

## リスク

| リスク | 影響度 | 状態 |
|---|---|---|
| 実 LLM が想定外のノイズ（説明文・マークダウン・複数行）を返す | 中 | post-processing（§5.7.4）で軽減済み。品質悪化時は `--concurrency 1` を推奨 |
| `progress.json` が巨大 MOD（数千エントリ）で肥大化する可能性 | 低 | 各エントリ1行のため線形増加。679件で数十KB程度。監視推奨 |
| トークン不一致で大量エントリが `failed` になる | 中 | モデルが `<alias=...>` 等を保持しない場合に発生しうる。失敗時は `<Dest>` 保護で安全側 |
| llama.cpp server の API 仕様変更 | 低 | OpenAI 互換エンドポイントは安定。`openai>=1.0` SDK が追従 |

---

## ロールバックメモ

`iroiro` は入力 XML を破壊しない設計。出力ファイルと進捗ファイルを削除すれば完全に元の状態に戻る。

### 出力・進捗ファイルの削除

```bash
# 入力: path/to/your_mod.xml の場合
rm path/to/your_mod.translated.xml
rm path/to/your_mod.xml.iroiro-progress.json
```

一般形:

```bash
rm <input_stem>.translated.xml
rm <input_full_name>.iroiro-progress.json
```

- 入力 XML は一切変更しない（読み込み専用）。
- 出力 XML は `<input>.translated.xml`（`-o` で明示した場合はそのパス）。
- 進捗ファイルは `<input>.iroiro-progress.json`（入力のフルファイル名 + 接尾辞）。
- 一時ファイル `<input>.iroiro-progress.json.tmp` が異常終了で残った場合は、それも削除。
  正常時は `os.replace` で原子的に置換されるため残らない。

### v0.1 コード自体を巻き戻す場合

`git` で初期コミット（`c589e6e`）に戻す。WP-1 / WP-2 / WP-3 は全て同一ブランチ（`main`）上の
未コミット変更として存在するため、`git restore` / `git clean -fd` で全て消える。
ただし `docs/plans/001-initial.md`（計画書）も消える点に注意。

---

## 次の担当者・エージェントへのメモ

### 実 LLM での初回検証をする場合

1. llama.cpp server を起動（README の設定例参照）:
   ```bash
   ./llama-server -m model.gguf --port 8081
   ```
2. 小さな MOD XML で試す:
   ```bash
   uv run iroiro translate path/to/your_mod.xml --dry-run
   uv run iroiro translate path/to/your_mod.xml
   ```
3. 出力 `path/to/your_mod.translated.xml` を xTranslator で開いて互換性確認。
4. `model` 不一致エラーが出たら `--model <alias>` を調整。
5. タイムアウトが出たら `--timeout 300` 等に増やす。

### v0.2（用語集）を始める場合

- 計画書 §4.2 で「v0.2機能以降」と明記されている機能。
- 設計段階で用語集フォーマット（TSV / YAML / JSON）・適用順序・衝突解決ポリシーを決める必要がある。
- 既存の `Translator` と `_build_user_message` が用語集挿入の自然な拡張点。

### コードを読む場合の推奨順序

1. `iroiro/cli.py` — 全体フロー（parse → resume → dry-run → translate → serialize）の理解。
2. `iroiro/models.py` — `StringEntry` / `FileFormat` の dataclass を把握。
3. `iroiro/xml_io.py` — BOM/CRLF/宣言保持戦略（§5.5）の中核。最も注意深くレビューすべき箇所。
4. `iroiro/escape.py` + `iroiro/translator.py` — プレースホルダ保護と LLM クライアント。
5. `iroiro/progress.py` — 並行安全な再開機能。

### 注意点

- **アプリ側での XML エスケープは絶対にしない**。lxml が parse 時に解除・serialize 時に再エスケープ
  する。二重エスケープ（`&amp;lt;`）を防ぐため（計画書 §5.6）。
- **`root.iter()` は `_Comment` ノードを含む** が **CDATA は含まない**。このため CDATA は生バイト列
  スキャンで検出する（計画書 §5.5.2 v0.6）。
- **`<Dest>` は失敗・スキップ時に元の値を保持** する。`source` で上書きしない（計画書 §5.9）。
- テストは `httpx.MockTransport` を `openai.AsyncOpenAI(http_client=...)` に注入する形式。
  実リクエストを送らないので CI で安全。
