"""iroiro-translator テストスイート共通設定。

WP-1: テスト・フィクスチャ
WP-2: `iroiro/` パッケージ実装後にテストが green になることを想定。

主な役割:
  - フィクスチャ XML のパスを提供
  - テスト高速化のため `asyncio.sleep` を即座に完了させる（autouse）
  - 共通ヘルパー定数

注意:
  - `@pytest.mark.asyncio` デコレータを使用するため、WP-2 で `pytest-asyncio` が
    `pyproject.toml` に追加される前提。WP-1 単体では async テストは skip/error になる。
  - `iroiro/` パッケージが存在しない場合、import 系テストは収集エラーになるが、
    これは WP-1 の想定通り（WP-2 完了後に green 化）。
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

# tests/fixtures へのパス
FIXTURES_DIR = Path(__file__).parent / "fixtures"

# サンプル XML（実物）へのパス
SAMPLE_XML = Path(__file__).resolve().parents[1] / "sample" / "JobsofSkyrim_english_japanese.xml"


# ----- フィクスチャパス ---------------------------------------------------------

@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """フィクスチャディレクトリ。"""
    return FIXTURES_DIR


@pytest.fixture(scope="session")
def tiny_xml() -> Path:
    """tiny.xml: LF / no BOM / standalone="yes"。alias/br/%{}/#/空文字 含む。"""
    return FIXTURES_DIR / "tiny.xml"


@pytest.fixture(scope="session")
def tiny_crlf_bom_xml() -> Path:
    """tiny_crlf_bom.xml: UTF-8 BOM + CRLF + standalone="yes"。"""
    return FIXTURES_DIR / "tiny_crlf_bom.xml"


@pytest.fixture(scope="session")
def japanese_source_xml() -> Path:
    """japanese_source.xml: 既に日本語 Source を含む。"""
    return FIXTURES_DIR / "japanese_source.xml"


@pytest.fixture(scope="session")
def long_source_xml() -> Path:
    """long_source.xml: max_chars (4000) を超える長文 Source。"""
    return FIXTURES_DIR / "long_source.xml"


@pytest.fixture(scope="session")
def sample_xml() -> Path:
    """実物サンプル（679件）。T10 用。

    注: sample XML は第三者著作物のため git 管理外。ユーザー環境で用意された
    MOD XML へのパス（SAMPLE_XML）を返す。ファイルが無い場合は T10 が skipif で
    スキップされる。
    """
    return SAMPLE_XML


@pytest.fixture(scope="session")
def with_cdata_xml() -> Path:
    """with_cdata.xml: CDATA セクション含む（T52c 用）。"""
    return FIXTURES_DIR / "with_cdata.xml"


@pytest.fixture(scope="session")
def with_comment_xml() -> Path:
    """with_comment.xml: XMLコメント含む（T52b 用）。"""
    return FIXTURES_DIR / "with_comment.xml"


@pytest.fixture(scope="session")
def skip_records_xml() -> Path:
    """skip_records.xml: 複数 REC 型を含む小XML（v0.2 T56-T83 用）。

    構成（8エントリ）:
      - HDPT:FULL "Male Head"          → デフォルトスキップリスト（REC skip）
      - WEAP:FULL "Iron Sword"         → デフォルトスキップリスト外（翻訳対象）
      - MGEF:FULL "Fire Damage"        → デフォルトスキップリスト（REC skip）
      - RACE:FULL "Nord"               → デフォルトスキップリスト（REC skip）
      - BPTD:BPTN "Head"               → デフォルトスキップリスト（REC skip・```:FULL``` 以外）
      - ACTI:FULL "Wooden Door"        → デフォルトスキップリスト外（翻訳対象）
      - ACTI:FULL ""                   → 空文字（言語 skip）
      - WEAP:FULL "既存の日本語"       → 日本語（言語 skip）

    dry-run 集計の期待値（デフォルト動作）:
      - 翻訳対象: 2 (WEAP:FULL Iron Sword, ACTI:FULL Wooden Door)
      - スキップ（空/日本語混入）: 2 (ACTI:FULL 空, WEAP:FULL 日本語)
      - スキップ（REC 型）: 4 (HDPT, MGEF, RACE, BPTD)
      - スキップ（長文超過）: 0

    形式: BOM + CRLF + standalone="yes"（実データと同じ）。
    """
    return FIXTURES_DIR / "skip_records.xml"


# ----- テスト高速化 -------------------------------------------------------------

@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """リトライ時の指数バックオフ `asyncio.sleep` を即座に完了させる。

    translator のリトライ（1s, 2s, 4s）でテストが遅くなるのを防ぐ。
    httpx の内部で asyncio.sleep が呼ばれても即座に返るため実害無し。
    T33（タイムアウト）ではモックが即座に TimeoutException を返すので影響しない。
    """
    async def _instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _instant)


# ----- v0.5 PromptConfig helper ----------------------------------------------
# Plan 005 §4.2 / B7: 実装コードからデフォルト値を import しない（案 α の一貫性）。
# テストヘルパーとして ``default_prompt_config`` fixture を提供する。
# ``iroiro/translator.py`` に ``PromptConfig`` が追加された後に利用可能。

@pytest.fixture
def default_prompt_config():
    """v0.5 既存テスト（T26-T51, T85-T87 等）用の標準 ``PromptConfig``。

    ``PromptConfig`` は WP-2 で ``iroiro/translator.py`` に追加される dataclass。
    テストは本 fixture を経由して ``Translator(cfg, prompts=default_prompt_config, ...)`` に渡す。

    本 fixture は「既存テストが従来の ``_SYSTEM_PROMPT`` / ``REJECT_PHRASES`` /
    ``_REC_HINTS`` ハードコード定数と **意味的に同等** の挙動」を再現するため、
    テスト本体を変更せずに v0.5 signature に追従できる（B6 指摘の吸収）。
    """
    from iroiro.translator import PromptConfig  # WP-2 で追加される dataclass

    return PromptConfig(
        system_prompt=(
            "Skyrim MOD の英文を日本語に翻訳する。"
            "固有名詞・ <alias=...> 等のプレースホルダ・ <br>・改行文字・ # 記号は "
            "**そのまま維持** すること。"
            "簡潔で自然な日本語。**訳文のみ** 出力し、"
            "説明・マークダウン・ラベル・複数行は禁止。"
        ),
        rec_hints={
            "MGEF:FULL": "魔法の効果名。1〜4語程度の簡潔な表現。",
            "MGEF:DESC": "魔法の効果の説明文。自然な日本語の文章。",
            "ARMO:FULL": "防具の名称。1〜4語程度。",
            "ARMO:DESC": "防具の説明文。",
            "BOOK:FULL": "書籍のタイトル。簡潔な表現。",
            "BOOK:DESC": "書籍の本文。物語風の自然な日本語。",
            "WEAP:FULL": "武器の名称。1〜4語程度。",
            "SPEL:FULL": "スペル（能力）の名称。",
            "ACTI:FULL": "アクティベータ（家具/看板等）の名称。",
            "ALCH:FULL": "錬金術素材/薬の名称。",
            "ENCH:FULL": "エンチャント（効果）の名称。",
            "INGR:FULL": "錬金術素材の名称。",
            "NPC_:FULL": "NPC の名称。固有名詞として扱う。",
            "FACT:FULL": "派閥（ファクション）の名称。",
            "INFO:RNAM": "NPC のセリフ（会話の応答）。自然な会話文。",
            "QUST:FULL": "クエストのタイトル。",
            "RACE:FULL": "種族の名称。",
            "CLAS:FULL": "クラス（職業）の名称。",
        },
        reject_phrases=frozenset({
            "了解", "了解しました", "了解いたしました",
            "承知", "承知いたしました", "承知しております",
            "かしこまりました",
            "翻訳", "翻訳します", "翻訳しました", "翻訳結果", "翻訳文",
            "訳文", "訳しました", "訳します",
            "以下に訳します", "訳文を示します",
            "以下の通りです", "以下の通りとなります", "次のようになります",
            "上記の通りです",
        }),
    )
