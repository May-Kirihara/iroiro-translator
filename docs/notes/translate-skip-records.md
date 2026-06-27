# 翻訳スキップ対象レコード型（v0.2 機能の種）

- 作成: 2026-06-28
- ステータス: idea（v0.2 で実装検討）

## 背景

Skyrim MOD の XML（`SSTXMLRessources` v2）で、`<REC>` が以下のレコード型の `<String>` は
**内部管理用** に使われるため、翻訳すると MOD が誤動作する可能性がある。
これらを翻訳対象から除外したい。

## スキップ候補レコード型

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

## 要検討事項

- `MGEF:FULL`（魔法効果名）と `RACE:FULL`（種族名）は、ユーザーが翻訳を**希望する**ケースも多い。
  デフォルトでスキップするか、オプトインにするか要議論。
- 実データでの出現頻度・影響度を要調査。
