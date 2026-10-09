# 実装計画 007 — Skyrim MCM 翻訳 TXT 対応（v0.7）

- 作成: 2026-07-02
- リスク分類: **high-risk**
- バージョン: v0.7（新機能・破壊的変更は既存 XML パスには無し）
- 関連: [設計判断](../design.md) / [Plan 001](001-initial.md) / [Plan 005](005-llm-config.md)

---

## 1. ゴール

`iroiro-translator` に **Skyrim MCM（Mod Configuration Menu）翻訳 TXT** 形式の対応を追加する。
ユーザーは `iroiro mcm INPUT.txt` で、xTranslator ではなく SkyUI MCM 翻訳ファイル
（`*_ENGLISH.txt` / `translation_english.txt` 系）を英→日翻訳できる。

非ゴール（本計画では扱わない）:

- ファイル形式の **自動判別**（ユーザー申告通り引数 = サブコマンドで明示指定）
- MCM 独自の `system_prompt` / `[iroiro.mcm]` 設定セクション（既存 `system_prompt` を再利用・将来拡張）
- Fallout4 / Starfield の MCM 形式検証（構造は同一想定だが実データ未検証・将来拡張）

---

## 2. 背景・現状

### 2.1 MCM TXT フォーマットの実態（`sample/daymoyl_ENGLISH.txt` を実測）

- **エンコーディング**: UTF-16 LE + BOM（先頭 `ff fe`）。Skyrim が UTF-16 を要求するため。
- **構造**: 1行1エントリ・タブ区切り `` `$KEY\tEnglish text` ``。
  - `$KEY` は MCM 文字列 ID（例: `` `$DAYMOYL_QST_DEFAULT` ``）。**保存必須**（識別子）。
  - 値側が翻訳対象の英文。
  - 空行がグループ区切りとして挟まる（意味なし・そのまま保持）。
- **改行**: 実データは **混在**（daymoyl: CRLF 213件 + LF-only 7件、末尾改行なし）。
  submissivelola サンプルは CRLF 統一。
- **忠実度契約**（Codex review 指摘を受けて明文化）: 本計画の保証は **「フォーマット保存
  + 改行正規化」** であり、完全なバイト同一性（byte-fidelity）**ではない**。BOM / encoding /
  末尾改行の有無は保存するが、混在改行は支配的改行へ正規化する。これは既存 ``xml_io.py``
  が改行スタイルを検出して正規化するのと対称（§3.2 で却下代替案とともに詳述）。
- **プレースホルダ**: `` `{0}` `` / `` `{1}` `` / `` `{2}` `` 等（Skyrim GlobalVariable 置換）。
  翻訳でも **出現回数を完全保存** しなければならない（壊すと MCM 表示が崩れる）。

### 2.2 現状のコード構造（再利用可能資産）

| モジュール | MCM での再利用 | 備考 |
|---|---|---|
| `iroiro/translator.py` ``Translator`` / ``ApiConfig`` / ``PromptConfig`` | ✅ そのまま | LLM 呼び出し・post-processing・トークン整合性検証 |
| `iroiro/models.py` ``StringEntry`` | ✅ そのまま | `edid=$KEY` / `rec=""` / `source=英文値` / **`original_dest=source`**（Codex review blocking fix・後述） |
| `iroiro/progress.py` ``ProgressWriter`` | ✅ そのまま | index ベース・``<input>.iroiro-progress.json`` |
| `iroiro/translator.py` ``is_translation_needed`` | ✅ そのまま | `rec=""` で言語判定のみ |
| `iroiro/config.py` ``load_config`` | ✅ そのまま | ``skip_records`` は MCM では無視（`frozenset()` 使用） |
| `iroiro/escape.py` ``extract_tokens`` / ``tokens_match`` | ⚠ **拡張必須** | `` `{N}` `` 数値プレースホルダを保護対象に追加 |
| `iroiro/xml_io.py` ``parse_xml`` / ``serialize_xml`` | ❌ 不使用 | MCM 専用 I/O を新設 |
| `iroiro/cli.py` ``translate`` | ❌ 流用不可 | ``parse_xml``/``serialize_xml`` に強結合・新サブコマンド ``mcm`` を新設 |

### 2.3 再利用の要点

MCM パイプラインは XML パイプラインと **エントリモデルと翻訳エンジンを共有** し、
**I/O と CLI エントリポイントだけが異なる**。したがって新規コードは:

1. ``iroiro/mcm_io.py`` — ``parse_mcm`` / ``serialize_mcm``（バイト忠実度保存）
2. ``iroiro/cli.py`` — ``mcm`` サブコマンド追加（``_run`` 相当の ``_run_mcm``）
3. ``iroiro/escape.py`` — `` `{N}` `` プレースホルダ保護追加
4. テスト・フィクスチャ・ドキュメント

---

## 3. 設計判断

### 3.1 CLI surface — 新サブコマンド ``iroiro mcm``（却下: ``--format mcm`` フラグ）

**採用**: ``iroiro mcm INPUT.txt [-o OUTPUT] [--dry-run] [--resume] ...``（共通オプションは ``translate`` と同じ）。

却下理由（``--format`` フラグ）: ``translate`` の ``_run`` は ``parse_xml``/``serialize_xml``
に強結合しており、分岐を入れると既存 XML パスの回帰リスクが生じる。サブコマンド分離により
**既存 XML パスは1行も変更しない**（リスク隔離・AGENTS.md「触ってはいけないもの」の精神）。

フラグ群は ``translate`` と共有: ``--config`` / ``--api-base`` / ``--api-key`` / ``--model``
/ ``--concurrency`` / ``--max-chars`` / ``--timeout`` / ``--resume`` / ``--dry-run``
/ ``-v`` / ``-o`` / ``--retry-failed``。``--skip-records`` は **MCM では無意味**（REC 概念無し）
のため省略する。

### 3.2 出力形式 — フォーマット保存 + 改行正規化（Codex review blocking fix）

- 出力ファイル: ``<input>.translated.txt``（``-o`` で上書き可能）。
- エンコーディング・BOM: 入力と同一（UTF-16 LE + BOM をそのまま再現）。
- 改行: 入力の **支配的改行**（CRLF 件数 ≥ LF 件数 なら CRLF、 else LF）で正規化。
- 末尾改行: 入力の有無を保存（daymoyl は「末尾改行なし」を再現）。
- ``$KEY`` はそのまま・値側を訳文で置換。空行・タブ無し非空行は構造要素としてそのまま保持（§3.6）。

**保証の名称**: 「フォーマット保存 + 改行正規化」（format-preserving with newline normalization）。
完全なバイト同一性を **意図的に保証しない**。理由:

却下代替案（行ごとの改行保存）: ``McmFormat`` に行ごとの区切り文字列リストを持たせて再現する。
採用しない理由: (1) Skyrim は行単位で読み・混在改行の厳密保存に実用価値が無い、(2) 既存
``xml_io.py`` が改行スタイル検出＋正規化を採用しており対称性が保たれる、(3) 行ごと保存は
fragile で実装コストに見合わない。テスト（T-MCM-03）は「混在入力が支配的改行へ正規化される」
ことを **意図仕様として** assert する（バイト同一を主張しない）。

### 3.2.1 MCM skip/fail 時の値保護（Codex review blocking fix・必須）

**問題**: 既存 ``_translate_all`` は skip（language/max_chars）/ fail 全経路で
``entry.new_dest = entry.original_dest`` をセットする（``cli.py:441/447/459/474``）。
MCM で ``original_dest=""`` とすると、skip/fail 時の出力値が **空文字になり英文が消滅** する
（data-loss）。

**修正**: MCM エントリは ``original_dest = source``（英文値そのもの）で構築する。
これにより skip/fail 時は英文値がそのまま出力に残る（既存 XML の「失敗時は元 ``<Dest>`` を保持」
哲学と同じ。MCM では「元の値 = 英文」）。テスト T-MCM-FAIL / T-MCM-LONG / T-MCM-JP で検証。

### 3.3 プレースホルダ保護 — ``escape.py`` の共有 regex 拡張（却下: MCM ローカル）

**採用**: ``PROTECTED_TOKENS_RE`` に `` `\{\d+\}` ``（数値プレースホルダ）を追加。

却下理由（MCM ローカル関数）:
- ``extract_tokens`` / ``tokens_match`` は ``Translator.translate_entry`` 内で
  ``source`` と ``cleaned``（訳文）の整合性を検証する **唯一の安全装置**。これを MCM 用に
  分岐させると、トークン検証ロジックが2系統に分裂し保守性が下がる。
- `` `{0}` `` は XML Source にも出現しうる（Skyrim の書籍・メッセージ等）。共有 regex への
  追加は **保護の厳密化**（安全方向の拡張）であり、既存 XML パスのテストを破らない
  （`` `{0}` `` を「保護しない」ことを主張する既存テストは存在しない・要確認）。
- 追加後、`` `{0}` `` を含む原文の訳文が `` `{0}` `` を欠落させると ``token mismatch``
  ``IroiroError`` で ``state=failed`` になる（既存の失敗回復経路そのまま）。
- **過剰マッチの仕様固定**（Codex review 指摘）: 単純な `` `\{\d+\}` `` は `` `{{0}}` `` の内側や
  XML 散文のリテラル数値波括弧にもマッチする。これは **安全バイアス**（保護しすぎる方向）として
  受容する。`` `{{0}}` `` → 内側の `` `{0}` `` を1個として抽出・両辺で同数なら整合 OK。
  厳密化（negative lookaround）は v0.7 では見送り・T-ESC-N4 で挙動を pin する。
- **確認済み**（QA 代行証明）: ``tests/fixtures/`` 配下に `` `{N}` `` リテラルを含む fixture は
  存在しない（2026-07-02 時点）。したがって既存テストの回帰は無い。

### 3.4 skip_records / rec_hints の扱い

- MCM エントリは全て ``rec=""`` とする（MCM に REC 概念は無い）。
- ``skip_records`` は ``frozenset()``（空集合）を渡す。``iroiro.toml`` の ``skip_records``
  は ``load_config`` 必須チェックを通すためだけに読むが、MCM 実行時には **使用しない**。
  （``load_config`` をそのまま使える = コード重複を避ける）
- ``rec_hints`` も ``rec=""`` のため全エントリでヒント不使用（``_build_user_message`` は
  ``source`` のみ返す）。

### 3.5 system_prompt の再利用（却下: MCM 独自 prompt）

**採用**: 既存 ``system_prompt`` をそのまま使用。

却下理由（MCM 独自 ``[iroiro.mcm]`` セクション）:
- `` `{N}` `` 保存は **トークン整合性検証が強制保証** する（プロンプトに依存しない）。
- プロンプト最適化は失敗率の改善であって正確性の保証ではない。v0.7 は最小実装とし、
  プロンプト分離は将来拡張（v0.8 候補）に残す。
- `` `{N}` `` 保存は ``escape.py`` のトークン整合性検証が **プロンプト非依存で強制保証** する
  ため、``iroiro.toml.example`` の ``system_prompt`` 編集は **本バージョンでは行わない**
  （AGENTS.md の「LLM 挙動中核デフォルト値編集時の同時更新ルール」が起動し
  ``tests/conftest.py:default_prompt_config`` / ``tests/test_cli.py:T168`` のカスケード更新が
  発生するのを避ける・WP-3 スコープを最小化）。``system_prompt`` への `` `{0}` `` 保存行追記は
  将来改善（v0.8 候補）に委ねる。

### 3.6 行モデル・インデックスセマンティクス（Codex review 指摘で明文化）

MCM TXT は「翻訳可能なキー付き行」と「パススルー行」が混在する。``parse_mcm`` は物理行を
**順序保存** で次の2種に分類する:

| 行種別 | 判定 | 扱 |
|---|---|---|
| キー付き行（translatable） | タブ `` `\t` `` を1個以上含む | ``StringEntry`` 化。``split("\t", 1)`` で ``edid=key`` / ``source=value``。2個目以降のタブは値の一部として保持。``$`` prefix は **要求しない**（実データは慣行で ``$`` 付きだが MCM 仕様上は必須でない・タブ有り非空行は全て翻訳対象） |
| 空行（passthrough） | ``strip() == ""`` | そのまま出力へ |
| 非空・タブ無し行（passthrough） | ``strip() != ""`` かつ `` `\t` `` を含まない | コメント・メタ行等と解釈・そのまま出力へ（翻訳しない） |
| `` `\t` `` 単独行 | ``line == "\t"`` | ``split("\t",1)`` → ``["",""]``・``edid=""`` ``source=""``・``is_translation_needed("")`` False → skip → ``new_dest=original_dest=""``・round-trip する（T-MCM-EMPTY-VAL で cover） |

**インデックスセマンティクス**: ``StringEntry.index`` は **翻訳可能エントリの通し番号**
（0,1,2,…・物理行番号ではない）。これにより ``ProgressWriter`` の index ベース resume が
XML と完全に対称に働く（``input_hash`` が入力変更を保証）。シリアライズは「行モデル」で
物理順序を復元し、各キー付き行の値に ``new_dest`` を書く。

**``new_dest=None`` fallback**（QA M1・xml_io と対称）: ``serialize_mcm`` は
``entry.new_dest is not None`` なら ``new_dest`` を、``None`` なら ``original_dest``
（= source = 英文）を書く。これは ``_apply_existing`` の ``retry_failed=True`` ブランチ
（``cli.py:415-418`` で ``new_dest`` を触らない）経由で ``None`` が serialize に達するのを
防御する。T-MCM-NEWDEST-NONE で検証。

**resume の正しさ**: パススルー行は ``index`` 空間に含まれないため、resume で entries を
読み込んでも物理行との対応が崩れない（T-MCM-RESUME で検証）。

### 3.7 エンコーディング受入（UTF-16 LE 正規・UTF-8 は import 便益）

Skyrim MCM 正規形式は UTF-16 LE + BOM。``parse_mcm`` は次の順で受入:

1. 先頭2バイト ``ff fe`` → UTF-16 LE（BOM あり）
2. 先頭2バイト ``fe ff`` → UTF-16 BE（念のため受入・実データでは未確認）
3. 先頭3バイト ``ef bb bf`` → UTF-8 BOM
4. それ以外 → UTF-8（BOM 無し）

**出力は入力エンコーディングを保存**（UTF-16 LE 入力 → UTF-16 LE 出力）。UTF-8 は
「import 便益」として受入のみ（公式には Skyrim は UTF-16 を要求）。T-MCM-ENC-* で検証。

### 3.8 実装方針・既知制限（QA M2/M4 で明文化）

**``_run_mcm`` の実装方針**（QA M4）: ``cli.py`` に ``_run_mcm`` を新設する。
``_translate_all`` は **そのまま再利用** する — MCM は ``rec=""`` ``skip_records=frozenset()``
のため ``if entry.rec in cfg.skip_records`` ブランチ（``cli.py:440``）は ``"" in frozenset()`` = 常に
False で no-op となり、MCM でも安全に働く。したがって ``_translate_all`` の一般化・引数化は
**行わない**（既存 XML 呼出側を1行も変えない・回帰リスクゼロ）。``_run_mcm`` は ``_run`` と
異なり (a) ``parse_mcm``/``serialize_mcm`` を呼ぶ、(b) 件数サマリのラベルが REC 型無し
（``スキップ（空/日本語混入）`` 等のみ）、の差分を持つ独立関数とする。

**既知制限: first-line-only post-processing**（QA M2）: ``Translator.translate_entry`` の
``_postprocess``（``translator.py:253-261``）は複数行 LLM 出力を最初の行のみ採用する。MCM 値は
本来単一行だが、長文 description 系で LLM が複数行返した場合は **2行目以降が黙って truncate**
される（XML と同じ挙動・既知制限）。``docs/usage.md`` の MCM トラブルシュートに1行載せる。

### 3.9 改行の CR-only 扱い（QA m3）

§3.2 の支配的改行判定は CRLF / LF の2種のみ。CR-only（古い Mac）改行のファイルは **非サポート**
（実データでは観測されない）。入力された場合は支配的改行判定の tie（`crlf_count=0`, `lf_only_count=0`）
で CRLF 扱いとなり CRLF へ正規化される（`\r`→`\n`→`\r\n`・明示的な CR-only 対応は Non-goals）。

---

## 4. スコープ・非ゴール

### スコープ

- ``iroiro/mcm_io.py`` 新設: ``parse_mcm`` / ``serialize_mcm`` / ``McmFormat`` dataclass
- ``iroiro/escape.py``: ``PROTECTED_TOKENS_RE`` に `` `\{\d+\}` `` 追加
- ``iroiro/cli.py``: ``mcm`` サブコマンド + ``_run_mcm`` 追加
- ``tests/test_mcm_io.py`` 新設・``tests/test_escape.py`` に `` `{N}` `` ケース追加
- ``tests/test_cli.py`` に ``mcm`` サブコマンド E2E 追加
- フィクスチャ: 小さな MCM TXT（UTF-16 LE BOM / CRLF / LF 混在 / `` `{0}` `` 含む）を自作
- ドキュメント: ``README.md`` / ``docs/usage.md``（MCM セクション + 失敗時英文保持のトラブルシュート・QA M2）/ ``docs/development.md`` 更新・本計画書・引き継ぎメモ
  - ※ ``iroiro.toml.example`` の ``system_prompt`` 編集は **行わない**（§3.5・将来扱い）

### 非ゴール

- 自動判別（拡張子・内容でのフォーマット推論）
- Fallout4 / Starfield MCM 実データ検証（構造同一を想定するが本計画では Skyrim のみ保証）
- MCM 独自プロンプト / ``[iroiro.mcm]`` 設定セクション
- ``--skip-records`` の MCM サポート（REC 概念無し）

---

## 5. テスト戦略

### 5.1 ユニット（``tests/test_mcm_io.py``・新設）

- T-MCM-01: UTF-16 LE BOM + CRLF の parse → entries（``$KEY`` / ``source=値`` / ``original_dest=source``）
- T-MCM-02: round-trip フォーマット保存（BOM / 支配的改行 / 末尾改行 有無 の保存）
- T-MCM-03: 改行混在（CRLF+LF）入力 → 支配的（CRLF）へ **意図的正規化** される（バイト同一を主張しない）
- T-MCM-04: `` `{0}` `` プレースホルダ含むエントリの parse
- T-MCM-05: タブ無し非空行・空行がパススルーされる（順序保存・未翻訳）
- T-MCM-06: ``serialize_mcm`` が entries の ``new_dest`` を値に書き出す・``$KEY`` 保存
- T-MCM-07: UTF-8（BOM 無し）入力にも寛容（§3.7 import 便益）
- T-MCM-VALUE-TABS: 値に追加タブを含む行が ``split("\t", 1)`` で key/value 分離・値内タブ保持
- T-MCM-EMPTY-VAL: `` `$KEY\t` ``（値空）の round-trip・未翻訳
- T-MCM-ENC-LE: UTF-16 LE BOM 出力バイトが ``ff fe`` 開始
- T-MCM-ENC-BE: UTF-16 BE BOM（``fe ff``）受入
- T-MCM-ENC-UTF8BOM: UTF-8 BOM（``ef bb bf``）受入
- T-MCM-TRAILING-OFF: 末尾改行なし入力 → 末尾改行なし出力
- T-MCM-TRAILING-ON: 末尾改行あり入力 → 末尾改行あり出力
- T-MCM-NEWDEST-NONE: ``serialize_mcm`` が ``new_dest=None`` の entry を ``original_dest`` で出力（QA M1）
- T-MCM-EMPTY-FILE: 0バイト / BOM だけの空ファイル → 空 entries・例外無し
- T-MCM-NO-ENTRIES: 空行とタブ無し行のみ・翻訳可能エントリ 0件 → dry-run で ``総エントリ数: 0``・serialize が入力と同じ構造を返す
- T-MCM-TAB-ONLY: `` `\t` `` 単独行の round-trip（``edid=""`` ``source=""``・QA m2）

### 5.2 escape 拡張（``tests/test_escape.py``に追加）

- T-ESC-N: `` `{0}` `` `` `{1}` `` `` `{12}` `` が ``extract_tokens`` で検出される
- T-ESC-N2: `` `{0}` `` 1個の原文 → 0個の訳文 で ``tokens_match`` が False（missing 報告）
- T-ESC-N3: 既存トークン（``<alias>`` / ``%{x}`` / ``#``）検出に **回帰無し**
- T-ESC-N4: `` `{{0}}` `` 過剰マッチ挙動の pin（安全バイアスとして受容・§3.3）
- T-ESC-N5: MCM 値に `` `\\n` ``（リテラル2文字）含む場合の検出・整合性（既存ルールが MCM でも働く）

### 5.3 CLI E2E（``tests/test_cli.py``に追加）

- T-CLI-MCM-01: ``iroiro mcm INPUT.txt --dry-run`` で件数表示・LLM 不呼出
- T-CLI-MCM-02: ``--resume`` で progress.json 読込・再開
- T-CLI-MCM-03: ``-o`` で出力パス指定
- T-CLI-MCM-04: ``httpx.MockTransport`` 注入で1エントリ翻訳 → 出力 TXT の ``$KEY`` 保存・値が訳文
- T-CLI-MCM-05: ``iroiro.toml`` 無しで dry-run エラー（``translate`` と同じ・v0.5 哲学）
- T-CLI-MCM-HELP: ``iroiro mcm --help`` に ``--skip-records`` が **無い** こと（§3.1）
- T-CLI-MCM-SKIP-RECORDS-REJECTED: ``iroiro mcm X --skip-records Y`` が typer により exit 2 で拒否される（実引数・QA M5）
- T-CLI-MCM-MAXCHARS-ZERO: ``--max-chars 0`` が全件 skip として働く（XML と対称・QA M5）
- T-MCM-FAIL: LLM 失敗時の出力値が **英文のまま**（空にならない・§3.2.1）
- T-MCM-LONG: ``--max-chars`` 超過スキップ時の出力値が **英文のまま**
- T-MCM-JP: 値に日本語混入のエントリがスキップされ **英文のまま** 出力
- T-MCM-RESUME: パススルー行（空行・タブ無し行）を挟んだ状態で resume し index 対応が正しい

### 5.4 フィクスチャ（``tests/fixtures/``に自作）

- ``mcm_tiny.txt``（UTF-16 LE BOM / CRLF / 数件 / `` `{0}` `` / 空行 / タブ無し行 含む）— 自作
- ``mcm_lf.txt``（LF / BOM 無し / 末尾改行あり）— 改行・BOM バリエーション

> フィクスチャは **実データ（第三者著作物）を使わない**（AGENTS.md のサンプル事故教訓）。
> ``sample/daymoyl_ENGLISH.txt`` はテストから参照しない（git 管理外・環境依存）。

---

## 6. 実装計画（Work Packages）

``normal`` の既定通り ``WP-1-tests`` → ``WP-2-core`` → ``WP-3-docs-handoff`` の直列。
ただし high-risk につき **並列化しない**（WP-1 → WP-2 → WP-3 の厳密直列・各 WP 後に PM 検証）。

### WP-1: テスト・フィクスチャ（test-first）

- Scope: ``tests/test_mcm_io.py`` 新設・``tests/test_escape.py``・``tests/test_cli.py`` 追記・
  ``tests/fixtures/mcm_*.txt`` 自作
- Acceptance: ``uv run pytest -k "mcm or ESC or CLI_MCM"`` が **red**（実装前に失敗）になること。
  ただし ``escape`` 拡張は WP-2 で入れるため T-ESC-* は WP-2 完了後に green。
- Allowed paths: ``tests/`` のみ

### WP-2: コア実装

- Scope: ``iroiro/mcm_io.py`` 新設・``iroiro/escape.py`` 拡張・``iroiro/cli.py`` に ``mcm`` サブコマンド
- Acceptance: ``uv run pytest`` 全 green・``uv run ruff check``・``uv run mypy iroiro`` クリーン
- Allowed paths: ``iroiro/`` のみ（``tests/`` 触らない・WP-1 で作ったテストを通す）

### WP-3: ドキュメント・引き継ぎ

- Scope: ``README.md`` / ``docs/usage.md``（MCM セクション + first-line-only 既知制限のトラブルシュート）/ ``docs/development.md`` / ``docs/handoff/007-mcm-translation.md``
  - ※ ``iroiro.toml.example`` の ``system_prompt`` は触らない（§3.5）
- Acceptance: CLI フラグ・使い方が実装と整合・sample コマンドが実行可能
- Allowed paths: ``README.md`` / ``docs/`` （``iroiro.toml.example`` は触らない）

---

## 7. リスク

| リスク | 影響 | 軽減 |
|---|---|---|
| skip/fail 時の出力値が空になる（data-loss） | **高** | ``original_dest=source`` で構築（§3.2.1）・T-MCM-FAIL/LONG/JP で検証。Codex review で指摘 |
| `` `{N}` `` regex 拡張が既存 XML テストを破る | 中 | WP-1 で T-ESC-N3 回帰テストを先に入れる。破壊時は即再診断 |
| UTF-16 + 混在改行の round-trip | 中 | 「フォーマット保存+正規化」契約で固定・T-MCM-02/03 で検証（バイト同一を主張しない） |
| MCM TXT にタブ無し行・``$`` 無し行が含まれる | 中 | §3.6 行モデルで固定（空行・非空タブ無し行はパススルー）・T-MCM-05 で検証 |
| resume で index ↔ 物理行の対応が崩れる | 中 | index = 翻訳可能エントリ通し番号（§3.6）・T-MCM-RESUME で検証 |
| ``load_config`` が MCM でも ``skip_records`` 必須エラーを出す | 低 | 仕様（MCM も ``iroiro.toml`` 必須・``translate`` と統一）。T-CLI-MCM-05 で検証 |
| サンプル事故（``sample/`` の第三者著作物を commit） | 高 | WP 検証で ``git status`` を毎回確認・フィクスチャは自作のみ |

---

## 8. 仮定台帳（assumption ledger）

| # | 仮定 | 根拠 | 反証条件 | 影響範囲 |
|---|---|---|---|---|
| A1 | ユーザーは ``iroiro mcm INPUT.txt`` サブコマンド形式を許容する | 「引数付きで対応で大丈夫」の申告・自動判別不要・ユーザー承認済 | — （確定） | — |
| A2 | 出力は同フォーマット（UTF-16 LE BOM・支配的改行）の翻訳 TXT | Skyrim MCM 翻訳ファイルの慣行・実データ構造・ユーザー承認済 | — （確定） | — |
| A3 | `` `{N}` `` は共有 ``escape.py`` regex で保護する | 安全方向の拡張・トークン検証の単一系統維持・ユーザー承認済 | — （確定） | — |
| A4 | MCM は ``rec=""`` ``skip_records=frozenset()`` で処理 | MCM に REC 概念無し | MCM 固有のスキップ要件が出る | skip 仕様追加（小） |
| A5 | 既存 ``system_prompt`` を MCM にも再利用 | `` `{N}` `` はトークン検証で強制保存・プロンプト非依存 | 失敗率が実用域を下回る | ``[iroiro.mcm]`` セクション追加（中・将来） |
| A6 | タブ無しの非空行はパススルー（未翻訳・そのまま保持） | MCM 形式の自然解釈・Codex review で行モデル明文化要求 | 実データにタブ無しの翻訳対象行が存在 | parse 仕様見直し（小） |
| A7 | skip/fail 時の出力値は英文（``original_dest=source``） | 既存回復経路 ``new_dest=original_dest`` との整合・Codex review blocking | — （blocking fix で確定） | — |
| A8 | 改行は支配的改行へ正規化（行ごと保存しない） | ``xml_io.py`` と対称・実用価値無し・Codex review で契約明文化要求 | Skyrim が行単位改行を厳密扱いする | 行ごと保存へ拡張（中） |

---

## 9. 検証完了条件（acceptance criteria）

1. ``uv run pytest``（208件 + MCM 追加分）が全 green
2. ``uv run ruff check iroiro/ tests/`` クリーン
3. ``uv run mypy iroiro`` クリーン
4. ``sample/daymoyl_ENGLISH.txt`` が存在する場合のみ ``uv run iroiro mcm sample/daymoyl_ENGLISH.txt --dry-run`` で件数表示（QA M3・sample は git 管理外なので新規 clone 環境では自作 fixtures で代替・既存 ``tests/test_xml_io.py`` の ``skipif not SAMPLE_XML.exists()`` パターンと対称）
5. 既存 XML ``translate`` パスに **回帰無し**（全テスト green で保証）
6. PM 全差分検査で禁止パス（``uv.lock`` / ``sample/`` / 既存 XML コードの破壊的変更）未触接を確認

---

## 10. レビューゲート（high-risk）

- ✅ GaOTTT recall（ambient 戻り無し・本計画が初回）
- ✅ 計画書（本ファイル）
- ✅ Codex CLI 計画レビュー（本ファイル + test strategy + impl plan）
- ✅ QA 計画レビュー（user-facing 新機能のため）
- ✅ test-first 委譲（WP-1）
- ✅ Codex テスト差分レビュー
- ✅ QA テスト差分レビュー（user-facing）
- ✅ 実装委譲（WP-2・WP-3）
- ✅ テスト実行
- ✅ PM 差分検査
- ✅ Codex 最終差分レビュー
- ✅ QA 最終レビュー
- ✅ GaOTTT writeback
