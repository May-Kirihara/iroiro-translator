# AGENTS.md

AI agent（Claude Code, Cursor, Codex 等）がこのリポジトリで作業する際のガイド。
人間の貢献者にも有用。

---

## プロジェクト概要

`iroiro` は Skyrim MOD の [xTranslator](https://www.nexusmods.com/skyrimspecialedition/mods/30918)
形式 XML（`SSTXMLRessources` v2）の `<Source>` 英文を、OpenAI 互換 LLM（ローカル LLM 想定）で
`<Dest>` に日本語翻訳する **バッチ CLI** ツール（Python 3.12+ / uv 管理）。出力 XML の
BOM / CRLF / `standalone="yes"` 宣言 / 空要素 `<X></X>` 形式を保持し、xTranslator との
相互運用性を保証する。

---

## クイックコマンド

```bash
uv sync                                        # 依存関係インストール（dev extras 含む）
uv run pytest                                  # テスト（144件）
uv run pytest -k "xml_io"                      # 個別テスト
uv run ruff check iroiro/ tests/               # lint
uv run mypy iroiro                             # 型チェック
uv run iroiro translate INPUT.xml --dry-run    # 動作確認（LLM 不要）
```

---

## ディレクトリ構成

```
iroiro-translator/
├── iroiro/             # 実装コード（11モジュール）
├── tests/              # テスト（test_*.py + fixtures/*.xml）
├── docs/               # ドキュメント
│   ├── design.md       # 設計判断
│   ├── usage.md        # 詳細な使い方
│   ├── development.md  # 開発者向け
│   ├── plans/          # 実装計画（歴史的記録・変更時は新規ファイルで）
│   └── handoff/        # 引き継ぎメモ（歴史的記録・変更時は新規ファイルで）
├── sample/             # 翻訳対象 XML（git 管理外・第三者著作物）
├── pyproject.toml      # PEP 621 設定・ツール設定
├── uv.lock             # uv が管理（触らない）
├── .python-version     # 3.12
├── .gitignore
├── iroiro.toml.example # 設定ファイル雛形（git 管理対象・ダミー値のみ）
├── README.md
├── AGENTS.md           # 本ファイル
└── LICENSE             # Apache 2.0
```

> `iroiro.toml`（実体・個人環境依存の LLM 設定）は `.gitignore` 対象でコミットされません。
> 各ユーザーが `cp iroiro.toml.example iroiro.toml` で作成します。

---

## コーディング規約

### 言語ポリシー

- **日本語** で: コメント・docstring・説明文・ドキュメント・コミットメッセージの説明部
- **英語のまま** で: 技術識別子（関数名・CLI フラグ・API名・XMLタグ・ファイルパス）・
  コマンド・パッケージ名・エラーメッセージ・コードブロック内

### リント・型

- ruff ルール: `E` / `F` / `W` / `I` / `B` / `UP`（`pyproject.toml` 参照）
- `iroiro/cli.py` は `B008` 除外（typer の idiomatic API）
- `tests/**` は `B011` 除外（`pytest.raises` を優先）
- mypy は strict ではないが `iroiro/` は型チェック必須。段階的型導入。

### XML 安全性の鉄則

- **アプリ側で XML エスケープ/アンエスケープは絶対にしない**。lxml が parse 時に解除・serialize 時に
  再エスケープする。二重エスケープ（`&amp;lt;`）を防ぐため。
- **失敗・スキップ時は元の `<Dest>` を保持** する。`<Source>` で上書きしない（`original_dest` / `new_dest` 分離）。
- **`root.iter()` は `_Comment` ノードを含む** が **CDATA は含まない**。CDATA は生バイトスキャンで検出。

---

## 触ってはいけないもの

| 対象 | 理由 |
|---|---|
| `sample/` 配下 | 第三者著作物の MOD XML。`.gitignore` で除外済み。コミットしないこと |
| `iroiro.toml`（実体） | 個人環境依存の LLM 設定（エンドポイント・API キー等）。`.gitignore` 対象・commit しない。`iroiro.toml.example`（雛形）は git 管理対象なので編集してよい |
| `uv.lock` | uv が管理。手動編集しない（`uv sync` / `uv add` 経由でのみ更新） |
| `docs/plans/`, `docs/handoff/` | 歴史的記録。変更が必要な場合は新規ファイル（`002-*.md` 等）で作成 |
| テストの weakning / skip | 正当な理由がある場合のみ `@pytest.mark.skipif` を使用。安易な `pytest.skip` は禁止 |

> **サンプルデータ事故の教訓**: 過去にユーザー提供の Skyrim MOD XML（第三者著作物）を `sample/` に
> 置いたまま `git add .` でコミットした事故あり。サンプルデータは必ず「私的な開発用か、再配布可能か」を
> 確認し、疑わしいものはコミット前に `.gitignore` 行きにする。

---

## 必ず通すべきフロー

実装変更後は以下を全てクリーンにすること:

```bash
uv run pytest                          # 全テスト green
uv run ruff check iroiro/ tests/       # lint クリーン
uv run mypy iroiro                     # 型チェック クリーン
```

ドキュメントの更新タイミング:

- **設計変更時** → `docs/design.md` を更新
- **CLI フラグ追加・変更時** → `README.md` / `docs/usage.md` を更新
- **新モジュール追加時** → `docs/development.md` のモジュール構成を更新
- **重大な変更** → `docs/plans/` に新規ファイル（`002-*.md` 等）で文書化

---

## PR・コミット方針

### コミットメッセージ

Conventional Commits 風のプレフィックスを使用:

- `feat:` — 新機能
- `fix:` — バグ修正
- `chore:` — ビルド・依存・設定等の雑務
- `docs:` — ドキュメント変更
- `refactor:` — リファクタリング（機能変更なし）
- `test:` — テスト追加・修正
- `perf:` — パフォーマンス改善

### PR の原則

- **1 PR = 1 論理的変更**。複数の変更は分割する。
- テストを weakning する PR は **reject**。
- 実装変更に対応するテストを含める（TDD 歓迎）。
- ドキュメントと実装の乖離を避ける。

---

## 参考ドキュメント

- [README.md](README.md) — プロジェクト概要・クイックスタート
- [docs/design.md](docs/design.md) — 設計判断（XML 安全性・プレースホルダ保護・`<Dest>` 保護・制限事項）
- [docs/usage.md](docs/usage.md) — 詳細な使い方（CLI フラグ全一覧・設定例・トラブルシュート）
- [docs/development.md](docs/development.md) — 開発環境・テスト・モジュール構成・ロードマップ
- [docs/plans/001-initial.md](docs/plans/001-initial.md) — v0.1 初期実装の設計判断・却下代替案の経緯
- [docs/handoff/001-initial.md](docs/handoff/001-initial.md) — v0.1 完了時の引き継ぎメモ・検証結果
- [docs/plans/003-config-file.md](docs/plans/003-config-file.md) — v0.3 設定ファイル（`iroiro.toml`）の設計判断・却下代替案
- [docs/handoff/003-config-file.md](docs/handoff/003-config-file.md) — v0.3 完了時の引き継ぎメモ・検証結果
