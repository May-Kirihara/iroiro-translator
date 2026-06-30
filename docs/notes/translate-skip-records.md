# 翻訳スキップ対象レコード型（v0.2 機能の種）

- 作成: 2026-06-28
- ステータス: ✅ implemented（v0.2 で実装済み・v0.6 で toml 化・14 件に拡充）

> ✅ **v0.2 で実装済み**（`DEFAULT_SKIP_RECORDS` + `--no-skip-default-records` / `--skip-records` CLI フラグ）。
> ✅ **v0.6 で toml 化・14 件に拡充**（`DEFAULT_SKIP_RECORDS` 定数をコードから完全削除し
> `iroiro.toml` の `skip_records`（必須）に移行・`--no-skip-default-records` 廃止・
> `--skip-records` を完全置換セマンティクスに変更）。詳細は
> [docs/usage.md](../usage.md) と [docs/design.md](../design.md)、
> [Plan 006](../plans/006-multi-game.md) を参照。

## v0.6 移行メモ（2026-06-30）

v0.6（Plan 006）で本機能は以下のように変更された:

- **toml 化（案 α 徹底版）**: `DEFAULT_SKIP_RECORDS` 定数は `iroiro/translator.py` から
  **完全削除** され、`iroiro.toml` の `[iroiro] skip_records` が **必須** になった
  （v0.5 の LLM 挙動中核 toml 化と同じ哲学）。
- **14 件に拡充**: v0.2 の 12 件に `FLST:FULL`（FormID List）/ `KYWD:FULL`（Keyword）を追加。
  根拠は NG ガイド §9.1 Conservative Preset（EDID 抜き）。3 ゲーム
  （Skyrim / Fallout4 / Starfield）共通の内部管理用レコード。
- **`--no-skip-default-records` 廃止**: `DEFAULT_SKIP_RECORDS` 定数がコードから消えたため
  意味を成さない。代替手段: `--skip-records ""`（明示的空 set = 全件翻訳）か
  `iroiro.toml` で `skip_records = []`。
- **`--skip-records` の完全置換セマンティクス化**: v0.5 までの「DEFAULT への追加」から
  `str | None = None` パターン（3 状態）の完全置換に変更。
- **`is_translation_needed` の `skip_records` 引数必須化**: `None` フォールバック削除。

既存ユーザーは `iroiro.toml` に `skip_records`（14 件）を **手動追記** する必要がある。
また v0.5 までの `progress.json` を v0.6 で `--resume` すると fingerprint 不一致
（12 件 → 14 件）で停止する（安全側の挙動・`progress.json` 削除で対応）。

## 背景

Skyrim MOD の XML（`SSTXMLRessources` v2）で、`<REC>` が以下のレコード型の `<String>` は
**内部管理用** に使われるため、翻訳すると MOD が誤動作する可能性がある。
これらを翻訳対象から除外したい。

## スキップ候補レコード型

> ※ v0.6 で `FLST:FULL` / `KYWD:FULL` が追加され 14 件になった。以下は v0.2 時点の
> 12 件（原本の記録）。v0.6 の最終リストは `iroiro.toml.example` または
> [docs/usage.md](../usage.md) を参照。

| REC | 名前 |
|---|---|
| `HDPT:FULL` | Head Part name |
| `FURN:FULL` | Furniture name |
| `CLAS:FULL` | Class name |
| `DOOR:FULL` | Door name |
| `FACT:FULL` | Faction name |
| `CLFM:FULL` | Color Form name |
| `TREE:FULL` | Tree name |
| `MGEF:FULL` | Magic Effect name |
| `RACE:FULL` | Race name |
| `EXPL:FULL` | Explosion name |
| `HAZD:FULL` | Hazard name |
| `BPTD:BPTN` | Body Part Data name |

## v0.2 での実装メモ

- `is_translation_needed()` を `<REC>` 型でも判定するよう拡張
- 設定方法の候補:
  - CLI フラグ `--skip-records PATH`（JSON/YAML を読み込み）
  - 組み込みデフォルト + `--no-skip-default-records` で無効化
  - または `--skip-records HDPT:FULL,FURN:FULL,...` のカンマ区切り
- スキップされたエントリは `state=skipped`、`<Dest>` は元のまま（Plan §5.9 の保護ポリシー準拠）

> ※ v0.6 で「組み込みデフォルト」は廃止され `iroiro.toml` の `skip_records` 必須化。
> 設計は案 α 徹底版（コードから定数完全削除）で確定。

## 要検討事項

- `MGEF:FULL`（魔法効果名）と `RACE:FULL`（種族名）は、ユーザーが翻訳を**希望する**ケースも多い。
  デフォルトでスキップするか、オプトインにするか要議論。
  → **v0.2 の決定**: デフォルトでスキップ（安全側）。`--no-skip-default-records`（v0.2）/
  `--skip-records ""`（v0.6）で個別制御可能。
- 実データでの出現頻度・影響度を要調査。
  → v0.6 で NG ガイド §3 / §9.1 に基づき 14 件に拡充（実データ検証済み）。
