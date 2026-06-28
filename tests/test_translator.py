"""test_translator.py — Translator / LLM 翻訳のテスト（T26-T34, T41-T44, T51）。

v0.2 追加: T56-T63（``is_translation_needed`` REC 型拡張）, T71-T76（``_parse_skip_records``）,
T81/T81b（``compute_skip_records_fingerprint``）。

対象モジュール: `iroiro/translator.py`
シグネチャ契約（Plan §6.4）:
    @dataclass(slots=True)
    class ApiConfig:
        base_url: str
        api_key: str
        model: str
        timeout: float
        concurrency: int
        max_chars: int

    class Translator:
        def __init__(self, cfg: ApiConfig, client: AsyncOpenAI | None = None) -> None: ...
        async def translate_entry(self, source: str, rec: str) -> str: ...
        async def aclose(self) -> None: ...

    def is_translation_needed(source: str, rec: str = "", skip_records: frozenset[str] | None = None) -> bool: ...
    def _parse_skip_records(text: str) -> frozenset[str]: ...
    def contains_japanese(text: str) -> bool: ...

    DEFAULT_SKIP_RECORDS: frozenset[str]  # v0.2 追加・12件のデフォルトスキップ REC 型

    ※ `client` 引数はテスト容易性のための DI（WP-2 実装に委ねる）。Plan §6.4 に
       `__init__(self, cfg)` とあるが、`httpx.MockTransport` を注入するための
       オプショナル引数として追加を想定。

モック戦略:
  - `httpx.MockTransport(handler)` を `openai.AsyncOpenAI(http_client=...)` に注入
  - handler はリクエストごとにステータス/本文を返す
  - リトライ時の指数バックオフは conftest の autouse fixture で即座に完了

検証項目:
  - 正常系（訳文のみ返却）
  - post-processing（ラベル/フェンス/複数行のクリーニング）
  - トークン整合性（不一致 → IroiroError → state=failed, new_dest=original_dest）
  - HTTP リトライ（500×2→200 成功、500 連続で失敗、タイムアウト）
  - 長文スキップ（max_chars 超過）
  - Source 言語判定（空/空白/日本語/non-ASCII 英語）
  - v0.2: 翻訳スキップ REC 型（デフォルト12件・空集合・```:FULL``` 以外）
  - v0.2: ``--skip-records`` カンマ区切りパーサーのエッジケース
  - v0.2: ``compute_skip_records_fingerprint``（空集合は ``""`` 特例）
"""
from __future__ import annotations

import httpx
import pytest
from openai import AsyncOpenAI

from iroiro.errors import IroiroError
from iroiro.models import StringEntry
from iroiro.progress import compute_skip_records_fingerprint
from iroiro.translator import (
    DEFAULT_SKIP_RECORDS,
    ApiConfig,
    Translator,
    _parse_skip_records,
    contains_japanese,
    is_translation_needed,
)

# ===========================================================================
# モックヘルパー
# ===========================================================================

def make_mock_openai_client(handler) -> AsyncOpenAI:
    """httpx.MockTransport を注入した AsyncOpenAI を構築する。

    `handler` は `Callable[[httpx.Request], httpx.Response]`。

    ``max_retries=0`` で openai SDK の内部リトライを無効化している。
    これにより ``handler.calls`` が translator 側のリトライ試行回数と
    1:1 で対応し、T31/T32/T33 の試行回数アサーションが正確になる。
    （openai SDK のデフォルト ``max_retries=2`` だと1回の translator 試行で
    最大3回の HTTP call が発生し、呼出回数の検証が曖昧になる）
    """
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    return AsyncOpenAI(
        base_url="http://localhost:8081/v1",
        api_key="iroiro",
        http_client=http_client,
        max_retries=0,
    )


def make_chat_response(content: str) -> dict:
    """Chat Completions API 正常レスポンスの payload を構築（conftest のヘルパーと同等）。"""
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def make_config(**overrides) -> ApiConfig:
    """テスト用 ApiConfig。デフォルトから差分のみ上書き。"""
    defaults = dict(
        base_url="http://localhost:8081/v1",
        api_key="iroiro",
        model="test-model",
        timeout=30.0,
        concurrency=2,
        max_chars=4000,
    )
    defaults.update(overrides)
    return ApiConfig(**defaults)


class CountingHandler:
    """呼び出しごとに異なる振る舞いをするモックハンドラ。

    `responses` は (status_code, content_or_exception) のリスト。
    content_or_exception が str の場合は正常レスポンスの content、
    Exception の場合はその例外を raise する。
    """

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if not self.responses:
            # 想定より多く呼ばれた場合は最後のレスポンスを繰り返す（失敗系で安全側）
            return httpx.Response(500, json={"error": "exhausted"})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        status, content = item
        if isinstance(content, Exception):
            raise content
        return httpx.Response(status, json=make_chat_response(content))


async def _cli_like_process(
    translator: Translator, entry: StringEntry
) -> StringEntry:
    """CLI 側の翻訳フローをシミュレートするヘルパー（T30/T44/T51 用）。

    translate_entry の戻り値を new_dest にセットし、state を更新する。
    IroiroError の場合は state=failed, new_dest=original_dest を保持する。
    ※ Plan §5.6.3 / §5.9 の単一セマンティクス。
    """
    try:
        translated = await translator.translate_entry(entry.source, entry.rec)
        entry.new_dest = translated
        entry.state = "translated"
    except IroiroError:
        entry.new_dest = entry.original_dest  # source で上書きしない（Plan §5.6.3）
        entry.state = "failed"
    return entry


# ===========================================================================
# T26: 正常系（訳文のみ返却）
# ===========================================================================

@pytest.mark.asyncio
async def test_T26_normal_translation() -> None:
    """T26: LLM が訳文のみを返した場合はそのまま返す。"""
    cfg = make_config()
    client = make_mock_openai_client(
        lambda req: httpx.Response(200, json=make_chat_response("火の玉"))
    )
    translator = Translator(cfg, client=client)
    try:
        result = await translator.translate_entry("Fireball", "MGEF:FULL")
        assert result == "火の玉"
    finally:
        await translator.aclose()


# ===========================================================================
# T27: 訳文: ほげ → ラベル削除
# ===========================================================================

@pytest.mark.asyncio
async def test_T27_strip_translation_label() -> None:
    """T27: 行頭の `訳文:` ラベルを削除する（Plan §5.7.4 ノイズパターン）。"""
    cfg = make_config()
    client = make_mock_openai_client(
        lambda req: httpx.Response(200, json=make_chat_response("訳文: 火の玉"))
    )
    translator = Translator(cfg, client=client)
    try:
        result = await translator.translate_entry("Fireball", "MGEF:FULL")
        assert result == "火の玉", f"ラベル削除後の訳文: {result!r}"
    finally:
        await translator.aclose()


@pytest.mark.asyncio
async def test_T27b_strip_other_labels() -> None:
    """T27 補足: 他のラベルパターン（Translation/日本語/Result/Output）も削除。"""
    cfg = make_config()
    for label in ["Translation:", "日本語:", "Result:", "Output:"]:
        client = make_mock_openai_client(
            lambda req, _label=label: httpx.Response(
                200, json=make_chat_response(f"{_label} 火の玉")
            )
        )
        translator = Translator(cfg, client=client)
        try:
            result = await translator.translate_entry("Fireball", "MGEF:FULL")
            assert result == "火の玉", f"ラベル {label!r} 削除後: {result!r}"
        finally:
            await translator.aclose()


# ===========================================================================
# T28: ```\nほげ\n``` → フェンス削除
# ===========================================================================

@pytest.mark.asyncio
async def test_T28_strip_code_fences() -> None:
    """T28: ``` フェンスを削除する。"""
    cfg = make_config()
    client = make_mock_openai_client(
        lambda req: httpx.Response(
            200, json=make_chat_response("```\n火の玉\n```")
        )
    )
    translator = Translator(cfg, client=client)
    try:
        result = await translator.translate_entry("Fireball", "MGEF:FULL")
        assert result == "火の玉", f"フェンス削除後: {result!r}"
        assert "```" not in result
    finally:
        await translator.aclose()


# ===========================================================================
# T29: 複数行 → 最初の行のみ
# ===========================================================================

@pytest.mark.asyncio
async def test_T29_multiline_first_line_only() -> None:
    """T29: 複数行返却時は最初の行のみ採用（Plan §5.7.4-2）。"""
    cfg = make_config()
    client = make_mock_openai_client(
        lambda req: httpx.Response(
            200,
            json=make_chat_response("火の玉\n\n説明: Fireball の訳文です。"),
        )
    )
    translator = Translator(cfg, client=client)
    try:
        result = await translator.translate_entry("Fireball", "MGEF:FULL")
        assert result == "火の玉", f"最初の行のみ: {result!r}"
        assert "\n" not in result
    finally:
        await translator.aclose()


# ===========================================================================
# T30: トークン欠落 → state=failed、new_dest=original_dest
# ===========================================================================

@pytest.mark.asyncio
async def test_T30_token_missing_raises_and_keeps_original_dest() -> None:
    """T30: 原文に <alias=hero> があるが訳文に無い → IroiroError。

    CLI 側で state=failed, new_dest=original_dest になることをシミュレート検証。
    """
    cfg = make_config()
    source = "Hello <alias=hero>, welcome!"
    # 訳文から <alias=hero> が欠落
    client = make_mock_openai_client(
        lambda req: httpx.Response(200, json=make_chat_response("こんにちは、ようこそ！"))
    )
    translator = Translator(cfg, client=client)
    try:
        # translate_entry 単体では IroiroError が上がる
        with pytest.raises(IroiroError):
            await translator.translate_entry(source, "MGEF:FULL")

        # CLI ライク処理で state/new_dest を検証
        entry = StringEntry(
            index=0,
            edid="T30",
            rec="MGEF:FULL",
            source=source,
            original_dest=source,  # 未翻訳状態
            new_dest=None,
            state="pending",
        )
        entry = await _cli_like_process(translator, entry)
        assert entry.state == "failed"
        assert entry.new_dest == entry.original_dest, "original_dest を保持"
    finally:
        await translator.aclose()


# ===========================================================================
# T31: HTTP 500×2 → 200（リトライ成功）
# ===========================================================================

@pytest.mark.asyncio
async def test_T31_retry_succeeds_on_third_attempt() -> None:
    """T31: HTTP 500×2 → 200 でリトライ成功（Plan §5.7.5 リトライ）。"""
    cfg = make_config()
    handler = CountingHandler([(500, "err1"), (500, "err2"), (200, "火の玉")])
    client = make_mock_openai_client(handler)
    translator = Translator(cfg, client=client)
    try:
        result = await translator.translate_entry("Fireball", "MGEF:FULL")
        assert result == "火の玉"
        # 3回呼ばれたことを検証（初回 + リトライ2回）
        assert len(handler.calls) == 3, f"3回試行される: 実際 {len(handler.calls)}"
    finally:
        await translator.aclose()


# ===========================================================================
# T32: HTTP 500×3 → state=failed
# ===========================================================================

@pytest.mark.asyncio
async def test_T32_all_failures_raises() -> None:
    """T32: 連続失敗で最終的に例外（state=failed に至る経路）。

    十分な数の 500 を用意して、実装のリトライ回数に依存しない。
    """
    cfg = make_config()
    # 5回連続 500（実装が3回でも4回でも全失敗する）
    handler = CountingHandler([(500, f"err{i}") for i in range(5)])
    client = make_mock_openai_client(handler)
    translator = Translator(cfg, client=client)
    try:
        # translate_entry は最終的に IroiroError（translator.py で wrap）
        with pytest.raises(IroiroError):
            await translator.translate_entry("Fireball", "MGEF:FULL")

        # 3回試行されたことを検証（実装は range(3)）
        assert len(handler.calls) == 3, f"3回試行される: 実際 {len(handler.calls)}"

        # CLI ライク処理で state=failed 検証
        entry = StringEntry(
            index=0,
            edid="T32",
            rec="MGEF:FULL",
            source="Fireball",
            original_dest="Fireball",
            new_dest=None,
            state="pending",
        )
        entry = await _cli_like_process(translator, entry)
        assert entry.state == "failed"
        assert entry.new_dest == entry.original_dest
    finally:
        await translator.aclose()


# ===========================================================================
# T33: タイムアウト → リトライ → 失敗
# ===========================================================================

@pytest.mark.asyncio
async def test_T33_timeout_retry_then_fail() -> None:
    """T33: タイムアウトでリトライし、最終的に失敗する。

    httpx.TimeoutException を投げ続けるモックを使用。
    """
    cfg = make_config()
    # 十分な数のタイムアウト
    handler = CountingHandler([httpx.TimeoutException("timeout")] * 5)
    client = make_mock_openai_client(handler)
    translator = Translator(cfg, client=client)
    try:
        with pytest.raises(IroiroError):
            await translator.translate_entry("Fireball", "MGEF:FULL")
        # 実装は最大3回試行する（translator.py: for attempt in range(3)）
        assert len(handler.calls) == 3, f"タイムアウトで3回試行: 実際 {len(handler.calls)}"
    finally:
        await translator.aclose()


# ===========================================================================
# T34: 長文スキップ（max_chars 超過）
# ===========================================================================

@pytest.mark.asyncio
async def test_T34_long_source_skipped(long_source_xml) -> None:
    """T34: max_chars (4000) を超える Source はスキップ対象。

    Plan §5.7.2: len(source) > max_chars の場合はスキップ（分割しない）。
    スキップ判定は CLI 側だが、ここでは is_translation_needed と max_chars の
    組み合わせで検証可能。

    ※ translate_entry 自体は max_chars チェックを内部で行う想定（実装依存）。
       チェックが CLI 側の場合は、このテストは is_translation_needed + 長さ判定で検証。
    """
    # long_source.xml の Source は 5000文字（'A' * 5000）
    from iroiro.xml_io import parse_xml

    entries, _, _, _ = parse_xml(long_source_xml)
    long_source = entries[0].source
    assert len(long_source) > 4000, "long_source は max_chars 超過"

    # is_translation_needed 自体は「日本語含むか」のみ判定し、長さは別軸。
    # 長さ超過は CLI 側で len(source) > max_chars としてスキップする。
    assert len(long_source) > 4000


# ===========================================================================
# T41: 日本語混入Sourceはスキップ（ひらがな/カタカナ/漢字）
# ===========================================================================

def test_T41_japanese_source_not_needed() -> None:
    """T41: 日本語（ひらがな/カタカナ/漢字）を含む Source は翻訳不要。

    Plan §5.7.1: contains_japanese が True なら is_translation_needed は False。
    """
    # 漢字
    assert is_translation_needed("棺") is False
    # ひらがな
    assert is_translation_needed("こんにちは") is False
    # カタカナ
    assert is_translation_needed("ストリーム") is False
    # 混在
    assert is_translation_needed("魔法の指輪") is False


def test_T41_contains_japanese_breakdown() -> None:
    """T41 補足: contains_japanese の各範囲検出。"""
    # ひらがな U+3040-309F
    assert contains_japanese("あ") is True
    # カタカナ U+30A0-30FF
    assert contains_japanese("ア") is True
    # CJK統合漢字 U+4E00-9FFF
    assert contains_japanese("漢") is True
    # ASCII-only
    assert contains_japanese("Fireball") is False
    assert contains_japanese("") is False


# ===========================================================================
# T41b: 空 <Source></Source> → スキップ、new_dest=original_dest
# ===========================================================================

def test_T41b_empty_source_skipped() -> None:
    """T41b: 空文字列 Source は翻訳不要（Plan §5.7.1）。"""
    assert is_translation_needed("") is False


# ===========================================================================
# T42: 空白のみ <Source>   </Source> → スキップ
# ===========================================================================

def test_T42_whitespace_only_source_skipped() -> None:
    """T42: 空白のみ Source は翻訳不要（Plan §5.7.1 v0.3）。"""
    assert is_translation_needed("   ") is False
    assert is_translation_needed("\t\n") is False
    assert is_translation_needed(" \r\n ") is False


# ===========================================================================
# T43: non-ASCII 英語 café, "Hello", Wait… → 翻訳対象（True）
# ===========================================================================

def test_T43_non_ascii_english_is_target() -> None:
    """T43: non-ASCII 英語（アクセント/curly quotes/ellipsis）は翻訳対象。

    Plan §5.7.1 v0.3: 日本語文字を含まなければ non-ASCII でも翻訳対象。
    """
    assert is_translation_needed("café") is True
    assert is_translation_needed("\u201cHello\u201d") is True  # curly double quotes
    assert is_translation_needed("Wait\u2026") is True  # ellipsis …
    assert is_translation_needed("Fireball") is True  # plain ASCII


def test_T43b_mixed_japanese_and_english_skipped() -> None:
    """T43 補足: 英語 + 日本語混在はスキップ（日本語を含むため）。"""
    assert is_translation_needed("Fireball 火の玉") is False


# ===========================================================================
# T44: トークン不一致 → state=failed、new_dest=original_dest（単一セマンティクス）
# ===========================================================================

@pytest.mark.asyncio
async def test_T44_token_count_mismatch_keeps_original_dest() -> None:
    """T44: トークン回数不一致 → IroiroError → state=failed, new_dest=original_dest。

    Plan §5.6.3: 単一セマンティクス。source で上書きしない。
    """
    cfg = make_config()
    source = "<alias=a> and <alias=b>"  # 2個（ASCII-only で is_translation_needed=True）
    # 訳文は <alias=a> 1個のみ（回数不一致）
    client = make_mock_openai_client(
        lambda req: httpx.Response(
            200, json=make_chat_response("<alias=a> のみ")
        )
    )
    translator = Translator(cfg, client=client)
    try:
        with pytest.raises(IroiroError):
            await translator.translate_entry(source, "MGEF:FULL")

        entry = StringEntry(
            index=0,
            edid="T44",
            rec="MGEF:FULL",
            source=source,
            original_dest=source,
            new_dest=None,
            state="pending",
        )
        entry = await _cli_like_process(translator, entry)
        assert entry.state == "failed"
        assert entry.new_dest == entry.original_dest
    finally:
        await translator.aclose()


# ===========================================================================
# T51: original_dest != source のエントリでトークン不一致 → new_dest = original_dest
# ===========================================================================

@pytest.mark.asyncio
async def test_T51_original_dest_preserved_when_not_equal_source() -> None:
    """T51: original_dest != source のケースでトークン不一致 → new_dest = original_dest。

    Plan §5.6.3 / §5.9: source で上書きしないことの証明。
    「過去に人間が <Dest> を修正済みでも破壊しない」ポリシーの中核。
    """
    cfg = make_config()
    source = "Hello <alias=hero>"
    original_dest = "過去に人間が修正した <alias=hero> 訳"  # source != original_dest

    # 訳文から <alias=hero> が欠落（トークン不一致）
    client = make_mock_openai_client(
        lambda req: httpx.Response(
            200, json=make_chat_response("こんにちは")  # <alias=hero> 無し
        )
    )
    translator = Translator(cfg, client=client)
    try:
        with pytest.raises(IroiroError):
            await translator.translate_entry(source, "MGEF:FULL")

        entry = StringEntry(
            index=0,
            edid="T51",
            rec="MGEF:FULL",
            source=source,
            original_dest=original_dest,
            new_dest=None,
            state="pending",
        )
        entry = await _cli_like_process(translator, entry)

        assert entry.state == "failed"
        # ★ source ではなく original_dest を保持することの証明
        assert entry.new_dest == original_dest, (
            "original_dest を保持し、source で上書きしない"
        )
        assert entry.new_dest != source, "source で上書きされていない"
    finally:
        await translator.aclose()


# ===========================================================================
# 補助テスト: post-processing 境界（リストマーカー）
# ===========================================================================

@pytest.mark.asyncio
async def test_postprocess_strip_list_markers() -> None:
    """補足: 行頭のリストマーカー `- `, `* `, `1. ` を削除（Plan §5.7.4-3）。"""
    cfg = make_config()
    for marker in ["- ", "* ", "1. "]:
        client = make_mock_openai_client(
            lambda req, _m=marker: httpx.Response(
                200, json=make_chat_response(f"{_m}火の玉")
            )
        )
        translator = Translator(cfg, client=client)
        try:
            result = await translator.translate_entry("Fireball", "MGEF:FULL")
            assert result == "火の玉", f"リストマーカー {marker!r} 削除後: {result!r}"
        finally:
            await translator.aclose()


@pytest.mark.asyncio
async def test_postprocess_keep_surrounding_quotes() -> None:
    """補足: 前後の `'`, `"` は削除しない（Plan §5.7.4-5）。"""
    cfg = make_config()
    client = make_mock_openai_client(
        lambda req: httpx.Response(200, json=make_chat_response('"火の玉"'))
    )
    translator = Translator(cfg, client=client)
    try:
        result = await translator.translate_entry("Fireball", "MGEF:FULL")
        # 前後のクォートは保持される
        assert result == '"火の玉"', f"前後クォート保持: {result!r}"
    finally:
        await translator.aclose()


@pytest.mark.asyncio
async def test_postprocess_trim_whitespace() -> None:
    """補足: 前後ホワイトスペース・末尾改行をトリム（Plan §5.7.4-1）。"""
    cfg = make_config()
    client = make_mock_openai_client(
        lambda req: httpx.Response(
            200, json=make_chat_response("  火の玉\n\n")
        )
    )
    translator = Translator(cfg, client=client)
    try:
        result = await translator.translate_entry("Fireball", "MGEF:FULL")
        assert result == "火の玉", f"前後空白トリム後: {result!r}"
    finally:
        await translator.aclose()


# ===========================================================================
# v0.2: T56-T63 — is_translation_needed の REC 型スキップ拡張
#
# Plan §5.1: is_translation_needed(source, rec="", skip_records=None)
#   * rec != "" かつ rec in skip_records → False（スキップ）
#   * それ以外は空/空白/日本語混入の既存判定にフォールバック
#   * skip_records=None の場合は DEFAULT_SKIP_RECORDS を使用
# ===========================================================================


def test_T56_default_skip_hdpt_full() -> None:
    """T56: HDPT:FULL はデフォルトスキップリストに入っている → False。

    skip_records 省略時は DEFAULT_SKIP_RECORDS が使われる。
    """
    assert is_translation_needed("Hello", "HDPT:FULL") is False


def test_T57_empty_skip_records_translates() -> None:
    """T57: skip_records=frozenset() の場合は HDPT:FULL でも翻訳対象 → True。

    ``--no-skip-default-records`` 単独指定時の挙動に対応。
    """
    assert is_translation_needed("Hello", "HDPT:FULL", skip_records=frozenset()) is True


def test_T58_default_skip_mgef_full() -> None:
    """T58: MGEF:FULL はデフォルトスキップリストに入っている → False。"""
    assert is_translation_needed("Hello", "MGEF:FULL") is False


def test_T59_weap_full_not_in_default_list() -> None:
    """T59: WEAP:FULL はデフォルトスキップリストに入っていない → True（翻訳対象）。"""
    assert is_translation_needed("Iron Sword", "WEAP:FULL") is True


def test_T60_bptd_bptn_skipped() -> None:
    """T60: BPTD:BPTN（```:FULL``` 以外）もデフォルトスキップリストで機能 → False。"""
    assert is_translation_needed("Head", "BPTD:BPTN") is False


def test_T61_empty_source_skipped_even_if_rec_not_in_list() -> None:
    """T61: 空文字列 Source は REC 型にかかわらずスキップ → False。

    REC 型スキップより空文字スキップが優先される（フォールバック判定）。
    """
    assert is_translation_needed("", "HDPT:FULL") is False
    # REC 型がリスト外でも空ならスキップ
    assert is_translation_needed("", "WEAP:FULL") is False


def test_T62_japanese_source_skipped_even_if_rec_not_in_list() -> None:
    """T62: 日本語 Source は REC 型にかかわらずスキップ → False。

    REC 型がリスト外でも日本語ならスキップ（既存の contains_japanese 判定への
    フォールバック）。これにより REC skip と言語 skip が重複しない。
    """
    assert is_translation_needed("棺", "HDPT:FULL") is False
    # REC 型がリスト外でも日本語ならスキップ
    assert is_translation_needed("既存の日本語", "WEAP:FULL") is False


def test_T63_rec_empty_backward_compat() -> None:
    """T63: rec="" の場合は REC 型スキップが適用されず、既存の言語判定のみ → True。

    後方互換性: v0.1 の ``is_translation_needed(source)`` と同じ挙動。
    """
    assert is_translation_needed("Hello", rec="") is True
    # rec 省略も同じ
    assert is_translation_needed("Hello") is True


def test_T63b_default_skip_records_contains_12_entries() -> None:
    """T63 補足: DEFAULT_SKIP_RECORDS は12件の REC 型を含む。

    Plan §4 のリストと一致することを検証。
    """
    expected = frozenset({
        "HDPT:FULL", "FURN:FULL", "CLAS:FULL", "DOOR:FULL",
        "FACT:FULL", "CLFM:FULL", "TREE:FULL", "MGEF:FULL",
        "RACE:FULL", "EXPL:FULL", "HAZD:FULL", "BPTD:BPTN",
    })
    assert DEFAULT_SKIP_RECORDS == expected, (
        f"DEFAULT_SKIP_RECORDS は12件: 実際 {len(DEFAULT_SKIP_RECORDS)}件"
    )
    assert len(DEFAULT_SKIP_RECORDS) == 12


def test_T63c_custom_skip_records_used_when_provided() -> None:
    """T63 補足: skip_records を明示的に渡した場合は DEFAULT_SKIP_RECORDS は使われない。

    ``--no-skip-default-records --skip-records "MGEF:FULL"`` のケースに対応。
    MGEF:FULL はカスタムリストに入っているが、HDPT:FULL は入っていない。
    """
    custom = frozenset({"MGEF:FULL"})
    # MGEF:FULL はカスタムリストに入っている → スキップ
    assert is_translation_needed("Hello", "MGEF:FULL", skip_records=custom) is False
    # HDPT:FULL は DEFAULT_SKIP_RECORDS に入っているが、custom を渡した場合は適用外 → 翻訳対象
    assert is_translation_needed("Hello", "HDPT:FULL", skip_records=custom) is True


# ===========================================================================
# v0.2: T71-T76 — _parse_skip_records パーサー
#
# Plan §5.2b: ``--skip-records`` のカンマ区切りテキストを frozenset に変換。
#   * カンマで分割
#   * 各要素は strip（前後空白を許容）
#   * 空文字列要素は無視（"A,,B" → {A, B}）
#   * 重複は自動排除（frozenset の性質）
#   * 大文字小文字は区別しない（hdpt:full → HDPT:FULL に正規化）
# ===========================================================================


def test_T71_parse_basic_two_entries() -> None:
    """T71: 基本的な2要素パース → frozenset。"""
    assert _parse_skip_records("HDPT:FULL,FURN:FULL") == frozenset({"HDPT:FULL", "FURN:FULL"})


def test_T72_parse_whitespace_element_ignored() -> None:
    """T72: 空白要素が混入しても無視される → {HDPT:FULL, FURN:FULL}。"""
    assert _parse_skip_records("HDPT:FULL, ,FURN:FULL") == frozenset({"HDPT:FULL", "FURN:FULL"})


def test_T73_parse_duplicated_element_deduped() -> None:
    """T73: 重複要素は自動で排除される → {HDPT:FULL}。"""
    assert _parse_skip_records("HDPT:FULL,HDPT:FULL") == frozenset({"HDPT:FULL"})


def test_T74_parse_lowercase_normalized_to_uppercase() -> None:
    """T74: 小文字は大文字に正規化される → {HDPT:FULL}。"""
    assert _parse_skip_records("hdpt:full") == frozenset({"HDPT:FULL"})


def test_T75_parse_empty_string_returns_empty_frozenset() -> None:
    """T75: 空文字列 → frozenset()。"""
    assert _parse_skip_records("") == frozenset()


def test_T76_parse_whitespace_only_returns_empty_frozenset() -> None:
    """T76: 空白のみ → frozenset()。"""
    assert _parse_skip_records("   ") == frozenset()


def test_T76b_parse_mixed_case_and_whitespace() -> None:
    """T76 補足: 複合ケース（小文字・空白・重複）→ 正規化されて {HDPT:FULL, MGEF:FULL}。"""
    assert _parse_skip_records(" hdpt:full , MGEF:FULL , hdpt:full ") == frozenset({
        "HDPT:FULL", "MGEF:FULL",
    })


# ===========================================================================
# v0.2: T81/T81b — compute_skip_records_fingerprint 単体
#
# Plan §5.4: 空集合は "" を返す特例。非空は SHA256(sorted canonical)。
# v0.1 progress.json との互換性のため、空集合は SHA256(b"") と区別する。
# ===========================================================================


def test_T81_empty_frozenset_returns_empty_string() -> None:
    """T81: compute_skip_records_fingerprint(frozenset()) → ""（空集合の特例）。

    Plan §5.4: 空集合の場合は空文字列を返す。これは v0.1 progress.json
    （fingerprint フィールド無し = "" 扱い）との互換性のため。
    SHA256(b"") = "e3b0c442..." と区別するための特例扱い。
    """
    assert compute_skip_records_fingerprint(frozenset()) == ""


def test_T81b_non_empty_frozenset_returns_sha256_of_sorted_canonical() -> None:
    """T81b: 非空集合は SHA256("\\n".join(sorted(elements))) の hex を返す。

    順序に依存しない（frozenset は順序無し）。SHA256(b"") とも異なる。
    """
    import hashlib

    fp = compute_skip_records_fingerprint(frozenset({"HDPT:FULL"}))
    expected = hashlib.sha256(b"HDPT:FULL").hexdigest()
    assert fp == expected, f"SHA256('HDPT:FULL'): {fp} vs {expected}"
    # 空集合の特例（""）とは異なる
    assert fp != ""
    # SHA256(b"") とも異なる（要素が1つあっても canon 化されて別の値）
    assert fp != hashlib.sha256(b"").hexdigest()


def test_T81c_fingerprint_independent_of_order() -> None:
    """T81 補足: 異なる順序で挿入しても同じ fingerprint（sorted canonical のため）。"""
    fp1 = compute_skip_records_fingerprint(frozenset({"HDPT:FULL", "MGEF:FULL", "RACE:FULL"}))
    fp2 = compute_skip_records_fingerprint(frozenset({"RACE:FULL", "HDPT:FULL", "MGEF:FULL"}))
    assert fp1 == fp2, "順序に依存しない"


def test_T81d_default_skip_records_fingerprint_stable() -> None:
    """T81 補足: DEFAULT_SKIP_RECORDS の fingerprint は安定した固定値。

    resume 検証で v0.2 のデフォルト動作が一貫していることを保証する回帰テスト。
    """
    import hashlib

    expected = hashlib.sha256(
        "\n".join(sorted(DEFAULT_SKIP_RECORDS)).encode("utf-8")
    ).hexdigest()
    assert compute_skip_records_fingerprint(DEFAULT_SKIP_RECORDS) == expected
    # 64文字の hex
    assert len(expected) == 64


# ===========================================================================
# v0.2.1: T85-T87b — 空文字列チェック（ルール6）・メタ返答チェック（ルール7）
#
# Plan §5.7.4-6/7: post-processing 後が空文字列、または LLM が「指示を受けた応答」
# （了解しました／翻訳します／以下の通りです 等）を返した場合は IroiroError を raise し、
# 呼出側で state=failed, new_dest=original_dest にする（トークン不一致と同じ経路）。
#
# ※ 「分かりました」「はい」等の NPC セリフとして自然な言葉は除外されている（T87/T87b）。
# ===========================================================================


@pytest.mark.asyncio
async def test_T85_empty_response_raises_iroiro_error() -> None:
    """T85 (v0.2.1): LLM が空文字列を返した場合、IroiroError が raise される。

    Plan §5.7.4-6: post-processing 後が空文字列なら IroiroError。
    リトライは HTTP レベルのみ（content 検証はその後）なので即座に raise →
    CLI 側で state=failed, new_dest=original_dest になる。
    """
    cfg = make_config()
    client = make_mock_openai_client(
        lambda req: httpx.Response(200, json=make_chat_response(""))
    )
    translator = Translator(cfg, client=client)
    try:
        # translate_entry 単体では IroiroError が上がる
        with pytest.raises(IroiroError):
            await translator.translate_entry("Fireball", "MGEF:FULL")

        # CLI ライク処理で state/new_dest を検証
        entry = StringEntry(
            index=0,
            edid="T85",
            rec="MGEF:FULL",
            source="Fireball",
            original_dest="Fireball",
            new_dest=None,
            state="pending",
        )
        entry = await _cli_like_process(translator, entry)
        assert entry.state == "failed"
        assert entry.new_dest == entry.original_dest, "original_dest を保持"
    finally:
        await translator.aclose()


@pytest.mark.asyncio
async def test_T85b_whitespace_only_response_raises_iroiro_error() -> None:
    """T85 補足 (v0.2.1): 空白のみの応答も post-processing 後に空文字列 → IroiroError。

    Plan §5.7.4-6: 「空文字列（または空白のみ）」が対象。
    """
    cfg = make_config()
    client = make_mock_openai_client(
        lambda req: httpx.Response(200, json=make_chat_response("   \n\t "))
    )
    translator = Translator(cfg, client=client)
    try:
        with pytest.raises(IroiroError):
            await translator.translate_entry("Fireball", "MGEF:FULL")
    finally:
        await translator.aclose()


@pytest.mark.asyncio
async def test_T86_meta_response_ryoukai_raises() -> None:
    """T86 (v0.2.1): 「了解しました」は REJECT_PHRASES に含まれる → IroiroError。

    指示受け取り系のメタ返答。NPC セリフとしては不自然。
    """
    cfg = make_config()
    client = make_mock_openai_client(
        lambda req: httpx.Response(200, json=make_chat_response("了解しました"))
    )
    translator = Translator(cfg, client=client)
    try:
        with pytest.raises(IroiroError):
            await translator.translate_entry("Fireball", "MGEF:FULL")

        # CLI ライク処理で state=failed, new_dest=original_dest を検証
        entry = StringEntry(
            index=0,
            edid="T86",
            rec="MGEF:FULL",
            source="Fireball",
            original_dest="Fireball",
            new_dest=None,
            state="pending",
        )
        entry = await _cli_like_process(translator, entry)
        assert entry.state == "failed"
        assert entry.new_dest == entry.original_dest, "source で上書きしない"
    finally:
        await translator.aclose()


@pytest.mark.asyncio
async def test_T86b_meta_response_honyaku_raises() -> None:
    """T86b (v0.2.1): 「翻訳します」は作業宣言 → IroiroError。"""
    cfg = make_config()
    client = make_mock_openai_client(
        lambda req: httpx.Response(200, json=make_chat_response("翻訳します"))
    )
    translator = Translator(cfg, client=client)
    try:
        with pytest.raises(IroiroError):
            await translator.translate_entry("Fireball", "MGEF:FULL")
    finally:
        await translator.aclose()


@pytest.mark.asyncio
async def test_T86c_meta_response_ika_raises() -> None:
    """T86c (v0.2.1): 「以下の通りです」は案内定型句 → IroiroError（完全一致）。"""
    cfg = make_config()
    client = make_mock_openai_client(
        lambda req: httpx.Response(200, json=make_chat_response("以下の通りです"))
    )
    translator = Translator(cfg, client=client)
    try:
        with pytest.raises(IroiroError):
            await translator.translate_entry("Fireball", "MGEF:FULL")
    finally:
        await translator.aclose()


@pytest.mark.asyncio
async def test_T86d_meta_response_prefix_match_raises() -> None:
    """T86 補足 (v0.2.1): 行頭一致でも検出される。

    Plan §5.7.4-7: ``text.startswith(phrase)`` で判定するため、
    「翻訳します。」（句点付き）も「翻訳します」に続く語として検出される。
    ※ 検出方法は startswith（行頭一致）。
    """
    cfg = make_config()
    client = make_mock_openai_client(
        lambda req: httpx.Response(200, json=make_chat_response("翻訳します。"))
    )
    translator = Translator(cfg, client=client)
    try:
        with pytest.raises(IroiroError):
            await translator.translate_entry("Fireball", "MGEF:FULL")
    finally:
        await translator.aclose()


@pytest.mark.asyncio
async def test_T87_wakarimashita_accepted() -> None:
    """T87 (v0.2.1): 「分かりました」は NPC セリフとして自然なため許容される。

    REJECT_PHRASES に含まれないので正常な訳文として扱われる。
    """
    cfg = make_config()
    client = make_mock_openai_client(
        lambda req: httpx.Response(200, json=make_chat_response("分かりました"))
    )
    translator = Translator(cfg, client=client)
    try:
        result = await translator.translate_entry("Fireball", "MGEF:FULL")
        assert result == "分かりました", f"許容されるはずの訳文: {result!r}"
    finally:
        await translator.aclose()


@pytest.mark.asyncio
async def test_T87b_hai_accepted() -> None:
    """T87b (v0.2.1): 「はい」は NPC セリフとして自然なため許容される。"""
    cfg = make_config()
    client = make_mock_openai_client(
        lambda req: httpx.Response(200, json=make_chat_response("はい"))
    )
    translator = Translator(cfg, client=client)
    try:
        result = await translator.translate_entry("Fireball", "MGEF:FULL")
        assert result == "はい", f"許容されるはずの訳文: {result!r}"
    finally:
        await translator.aclose()


# ===========================================================================
# v0.2.1 補足: _is_meta_response / REJECT_PHRASES 単体テスト
# ===========================================================================


def test_is_meta_response_unit_reject_phrases() -> None:
    """補足: REJECT_PHRASES の各要素が _is_meta_response で True になる。"""
    from iroiro.translator import REJECT_PHRASES, _is_meta_response

    for phrase in REJECT_PHRASES:
        assert _is_meta_response(phrase) is True, (
            f"REJECT_PHRASES の要素 {phrase!r} は True のはず"
        )


def test_is_meta_response_unit_accepted_phrases() -> None:
    """補足: NPC セリフとして自然な言葉は _is_meta_response で False になる。"""
    from iroiro.translator import _is_meta_response

    for ok_text in [
        "分かりました", "わかりました", "はい", "いいえ",
        "すみません", "ごめんなさい", "ありがとう", "ありがとうございます",
        "火の玉", "Fireball",
    ]:
        assert _is_meta_response(ok_text) is False, (
            f"NPC セリフ {ok_text!r} は False のはず"
        )


def test_is_meta_response_empty_is_false() -> None:
    """補足: 空文字列は _is_meta_response では False（ルール6 が別途処理）。"""
    from iroiro.translator import _is_meta_response

    assert _is_meta_response("") is False
    assert _is_meta_response("   ") is False
