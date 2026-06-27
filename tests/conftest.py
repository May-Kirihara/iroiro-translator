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
