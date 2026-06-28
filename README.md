# iroiro-translator

Skyrim MOD の [xTranslator](https://www.nexusmods.com/skyrimspecialedition/mods/30918) 形式 XML
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
- **翻訳スキップ REC 型**（v0.2）— 内部管理用レコード（`HDPT:FULL` 等12件）を自動スキップ。`--no-skip-default-records` / `--skip-records` で制御。詳細は [docs/usage.md](docs/usage.md)
- **再開機能**（`--resume`） — 進捗ファイルから続きを実行
- **dry-run モード**（`--dry-run`） — LLM を呼ばず処理件数のみ表示
- **並列実行**（`--concurrency`） と **HTTP タイムアウト設定**（`--timeout`）

> **⚠️ v0.1 からの動作変更**: v0.2 では内部管理用 REC 型（`HDPT:FULL` 等12件）が
> **デフォルトで翻訳スキップ** されるようになりました。v0.1 と同じ動作を維持したい場合は
> `--no-skip-default-records` フラグを指定してください。詳細は [docs/usage.md](docs/usage.md)。

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

### 3. dry-run で動作確認

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
- `--api-base URL` — OpenAI 互換 API のベース URL（LM Studio / Ollama 等の切り替え）

CLI フラグ全一覧・設定例・トラブルシュートは [詳細な使い方](docs/usage.md) を参照。

---

## ドキュメント

- [設計判断](docs/design.md) — アーキテクチャ・XML 安全性・`<Dest>` 保護ポリシー・制限事項
- [詳細な使い方](docs/usage.md) — CLI フラグ全一覧・設定例・トラブルシュート
- [開発者向け](docs/development.md) — 開発環境・テスト・モジュール構成・ロードマップ
- [実装計画 v0.1](docs/plans/001-initial.md) — v0.1 初期実装の設計判断・却下代替案の経緯
- [実装計画 v0.2](docs/plans/002-skip-records.md) — v0.2 翻訳スキップ REC 型の設計判断
- [引き継ぎ v0.1](docs/handoff/001-initial.md) — v0.1 完了時の引き継ぎメモ・検証結果
- [引き継ぎ v0.2](docs/handoff/002-skip-records.md) — v0.2 完了時の引き継ぎメモ・検証結果

---

## ライセンス

Apache License 2.0。詳細は [`LICENSE`](LICENSE) ファイルを参照。
