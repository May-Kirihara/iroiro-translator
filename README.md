# iroiro-translator

Skyrim / Fallout4 / Starfield MOD の [xTranslator](https://www.nexusmods.com/skyrimspecialedition/mods/30918) 形式 XML
（`SSTXMLRessources` v2）の `<Source>` 英文を、OpenAI 互換 LLM で `<Dest>` に日本語翻訳する
**バッチ CLI** ツール。ローカル LLM（llama.cpp server / Gemma 系 12B 想定）を前提とする。

入力 XML の `<Content>/<String>` ごとに `<Source>` を LLM で日本語訳し、`<Dest>` に書き戻した
同形式の XML を出力する。すでに日本語が入っている `<Source>` や空文字は自動的にスキップされ、
巨大な MOD（数百〜数千エントリ）でも途中で止まったら `--resume` で続きから再実行できる。

> 本ツールは出力 XML の **主要なバイトレベルフォーマット**（BOM / CRLF /
> `standalone="yes"` 宣言 / 空要素の `<X></X>` 形式 / インデント）を保持し、
> xTranslator がそのまま再読み込みできる相互運用性を保証する。
> ※ 属性の順序や実体参照の細部など、XML シリアライザ依存の差分は許容される
> （xTranslator 互換性に影響しない範囲）。

---

## 主な機能

- **OpenAI 互換 API による英→日翻訳**（ローカル LLM 想定。llama.cpp server を推奨）
- **BOM / CRLF / `standalone="yes"` 宣言の保持** — xTranslator 互換
- **プレースホルダ保護** — `<alias=NAME>`, `<br>`, `%{...}`, `\n`, `\r`, `#` 等の出現回数を検証
- **失敗時の `<Dest>` 保護** — 翻訳失敗・スキップ時は元の `<Dest>` を保持し、`<Source>` で上書きしない
- **翻訳スキップ REC 型**（v0.2 / **v0.6 で toml 必須化**）— 内部管理用レコード（`HDPT:FULL` 等14件）を自動スキップ。v0.6 で `DEFAULT_SKIP_RECORDS` 定数をコードから完全削除し、`iroiro.toml` の `skip_records`（必須）に移行。CLI `--no-skip-default-records` は廃止・`--skip-records` は toml を完全置換するセマンティクスに変更（**後方互換性の破れ**・3 ゲーム対応）。詳細は [docs/usage.md](docs/usage.md)
- **設定ファイル**（v0.3）— 繰り返し使う設定（LLM エンドポイント・API キー・モデル名・タイムアウト等）を `iroiro.toml` に書いておけます。`.gitignore` 対象・環境依存情報をプロジェクトに混入させない。詳細は [docs/usage.md](docs/usage.md)
- **failed エントリの再試行**（v0.4）— LLM の一時的エラー等で `failed` になったエントリを `--retry-failed` で再翻訳対象に戻せる。`iroiro.toml` の `retry_failed = true` でデフォルト化も可。詳細は [docs/usage.md](docs/usage.md)
- **LLM プロンプト・エラー判定語句の完全 toml 化**（v0.5）— `system_prompt` / `reject_phrases` / `[iroiro.rec_hints]` の LLM 挙動中核を `iroiro.toml` で編集可能。コード内のハードコード定数を完全削除。`iroiro.toml` が `--dry-run` 含む全操作で必須になりました（**後方互換性の破れ**・詳細は [docs/usage.md](docs/usage.md)）
- **3 ゲーム対応 + skip_records の toml 化**（v0.6）— Skyrim / Fallout4 / Starfield の 3 ゲーム共通の skip リスト（14件）と `[iroiro.rec_hints]` に拡充。`skip_records` が `iroiro.toml` 必須に・`--no-skip-default-records` 廃止・`--skip-records` を完全置換セマンティクスに変更（**後方互換性の破れ**・詳細は [docs/usage.md](docs/usage.md)）
- **再開機能**（`--resume`） — 進捗ファイルから続きを実行
- **dry-run モード**（`--dry-run`） — LLM を呼ばず処理件数のみ表示
- **並列実行**（`--concurrency`） と **HTTP タイムアウト設定**（`--timeout`）


---

## クイックスタート

### 1. uv をインストール（未導入の場合）

[uv](https://docs.astral.sh/uv/) は Rust 製の Python パッケージ・環境管理ツール。

**macOS / Linux**:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows (PowerShell)**:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

インストール後、シェルを再起動して `uv --version` が動くことを確認（uv 0.5.x 以上を推奨）。
その他の導入方法（Homebrew / pip / pipx）は [uv 公式ドキュメント](https://docs.astral.sh/uv/getting-started/installation/) を参照。

### 2. リポジトリをクローンして依存関係を同期

```bash
git clone <repository-url> iroiro-translator
cd iroiro-translator
uv sync
```

`uv sync` は `uv.lock` に基づいて仮想環境を構築し、`iroiro` パッケージと依存ライブラリ
（`openai`, `httpx`, `lxml`, `typer`, `rich`）をインストールする。

> **注意**: リポジトリには翻訳対象のサンプル XML は含まれません（第三者著作物のため git 管理外）。
> お手持ちの MOD XML（xTranslator 形式の `SSTXMLRessources` v2）を各自で用意してください。

### 3. 設定ファイルを作成（必須・v0.5）

v0.5 では `iroiro.toml` が `--dry-run` を含む全操作で必須です。雛形をコピーします
（LLM 挙動中核のデフォルト値が全て入っているため、編集なしでも動きます）:

```bash
cp iroiro.toml.example iroiro.toml   # 雛形をコピー（.gitignore 対象・commit しない）
# 必要なら iroiro.toml を編集（api_key / model / system_prompt 等）
```

詳細は [詳細な使い方](docs/usage.md) を参照。

### 4. dry-run で動作確認

LLM サーバーを起動せずに、処理件数の集計だけを行う:

```bash
uv run iroiro translate path/to/your_mod.xml --dry-run
```

出力例:

```
INFO  Parsing input: path/to/your_mod.xml
INFO  Parsed 679 <String> entries (BOM=True, newline='\r\n', encoding=UTF-8)
総エントリ数: 679
翻訳対象: 31
スキップ（REC 型）: 6
スキップ（空/日本語混入）: 642
スキップ（長文超過）: 0
--dry-run: LLM を呼ばず終了します
```

---

## 基本的な使い方

別ターミナルでローカル LLM サーバーを起動後（既定は `http://localhost:8081/v1`）:

```bash
uv run iroiro translate path/to/your_mod.xml
```

よく使うフラグ:

- `--dry-run` — LLM を呼ばず処理件数のみ表示
- `--resume` — `progress.json` があれば続きから再実行
- `--resume --retry-failed` — resume 時に `failed` エントリも再翻訳対象に戻す（v0.4）
- `--api-base URL` — OpenAI 互換 API のベース URL（LM Studio / Ollama 等の切り替え）

CLI フラグ全一覧・設定例・トラブルシュートは [詳細な使い方](docs/usage.md) を参照。

---

## ドキュメント

- [設計判断](docs/design.md) — アーキテクチャ・XML 安全性・`<Dest>` 保護ポリシー・制限事項
- [詳細な使い方](docs/usage.md) — CLI フラグ全一覧・設定例・トラブルシュート
- [開発者向け](docs/development.md) — 開発環境・テスト・モジュール構成・ロードマップ
- [実装計画 v0.1](docs/plans/001-initial.md) — v0.1 初期実装の設計判断・却下代替案の経緯
- [実装計画 v0.2](docs/plans/002-skip-records.md) — v0.2 翻訳スキップ REC 型の設計判断
- [実装計画 v0.3](docs/plans/003-config-file.md) — v0.3 設定ファイル（`iroiro.toml`）の設計判断
- [実装計画 v0.4](docs/plans/004-retry-failed.md) — v0.4 failed エントリ再試行（`--retry-failed`）の設計判断
- [実装計画 v0.5](docs/plans/005-llm-config.md) — v0.5 LLM プロンプト・エラー判定語句の完全 toml 化の設計判断
- [実装計画 v0.6](docs/plans/006-multi-game.md) — v0.6 Fallout4 / Starfield 対応 + skip_records の toml 化の設計判断
- [引き継ぎ v0.1](docs/handoff/001-initial.md) — v0.1 完了時の引き継ぎメモ・検証結果
- [引き継ぎ v0.2](docs/handoff/002-skip-records.md) — v0.2 完了時の引き継ぎメモ・検証結果
- [引き継ぎ v0.3](docs/handoff/003-config-file.md) — v0.3 完了時の引き継ぎメモ・検証結果
- [引き継ぎ v0.4](docs/handoff/004-retry-failed.md) — v0.4 完了時の引き継ぎメモ・検証結果
- [引き継ぎ v0.5](docs/handoff/005-llm-config.md) — v0.5 完了時の引き継ぎメモ・検証結果
- [引き継ぎ v0.6](docs/handoff/006-multi-game.md) — v0.6 完了時の引き継ぎメモ・検証結果

---

## ライセンス

Apache License 2.0。詳細は [`LICENSE`](LICENSE) ファイルを参照。
