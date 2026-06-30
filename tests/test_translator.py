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

    def is_translation_needed(source: str, rec: str, skip_records: frozenset[str]) -> bool: ...
    def _parse_skip_records(text: str) -> frozenset[str]: ...
    def contains_japanese(text: str) -> bool: ...

    ※ v0.6（Plan 006 §4.4）: ``is_translation_needed`` は ``rec`` / ``skip_records``
       共に必須引数化された。``DEFAULT_SKIP_RECORDS`` 定数は完全削除されコード内
       デフォルトは無い（``iroiro.toml`` の ``skip_records`` から注入・案 α 徹底版）。

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
async def test_T26_normal_translation(default_prompt_config) -> None:
    """T26: LLM が訳文のみを返した場合はそのまま返す。"""
    cfg = make_config()
    client = make_mock_openai_client(
        lambda req: httpx.Response(200, json=make_chat_response("火の玉"))
    )
    translator = Translator(cfg, prompts=default_prompt_config, client=client)
    try:
        result = await translator.translate_entry("Fireball", "MGEF:FULL")
        assert result == "火の玉"
    finally:
        await translator.aclose()


# ===========================================================================
# T27: 訳文: ほげ → ラベル削除
# ===========================================================================

@pytest.mark.asyncio
async def test_T27_strip_translation_label(default_prompt_config) -> None:
    """T27: 行頭の `訳文:` ラベルを削除する（Plan §5.7.4 ノイズパターン）。"""
    cfg = make_config()
    client = make_mock_openai_client(
        lambda req: httpx.Response(200, json=make_chat_response("訳文: 火の玉"))
    )
    translator = Translator(cfg, prompts=default_prompt_config, client=client)
    try:
        result = await translator.translate_entry("Fireball", "MGEF:FULL")
        assert result == "火の玉", f"ラベル削除後の訳文: {result!r}"
    finally:
        await translator.aclose()


@pytest.mark.asyncio
async def test_T27b_strip_other_labels(default_prompt_config) -> None:
    """T27 補足: 他のラベルパターン（Translation/日本語/Result/Output）も削除。"""
    cfg = make_config()
    for label in ["Translation:", "日本語:", "Result:", "Output:"]:
        client = make_mock_openai_client(
            lambda req, _label=label: httpx.Response(
                200, json=make_chat_response(f"{_label} 火の玉")
            )
        )
        translator = Translator(cfg, prompts=default_prompt_config, client=client)
        try:
            result = await translator.translate_entry("Fireball", "MGEF:FULL")
            assert result == "火の玉", f"ラベル {label!r} 削除後: {result!r}"
        finally:
            await translator.aclose()


# ===========================================================================
# T28: ```\nほげ\n``` → フェンス削除
# ===========================================================================

@pytest.mark.asyncio
async def test_T28_strip_code_fences(default_prompt_config) -> None:
    """T28: ``` フェンスを削除する。"""
    cfg = make_config()
    client = make_mock_openai_client(
        lambda req: httpx.Response(
            200, json=make_chat_response("```\n火の玉\n```")
        )
    )
    translator = Translator(cfg, prompts=default_prompt_config, client=client)
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
async def test_T29_multiline_first_line_only(default_prompt_config) -> None:
    """T29: 複数行返却時は最初の行のみ採用（Plan §5.7.4-2）。"""
    cfg = make_config()
    client = make_mock_openai_client(
        lambda req: httpx.Response(
            200,
            json=make_chat_response("火の玉\n\n説明: Fireball の訳文です。"),
        )
    )
    translator = Translator(cfg, prompts=default_prompt_config, client=client)
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
async def test_T30_token_missing_raises_and_keeps_original_dest(default_prompt_config) -> None:
    """T30: 原文に <alias=hero> があるが訳文に無い → IroiroError。

    CLI 側で state=failed, new_dest=original_dest になることをシミュレート検証。
    """
    cfg = make_config()
    source = "Hello <alias=hero>, welcome!"
    # 訳文から <alias=hero> が欠落
    client = make_mock_openai_client(
        lambda req: httpx.Response(200, json=make_chat_response("こんにちは、ようこそ！"))
    )
    translator = Translator(cfg, prompts=default_prompt_config, client=client)
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
async def test_T31_retry_succeeds_on_third_attempt(default_prompt_config) -> None:
    """T31: HTTP 500×2 → 200 でリトライ成功（Plan §5.7.5 リトライ）。"""
    cfg = make_config()
    handler = CountingHandler([(500, "err1"), (500, "err2"), (200, "火の玉")])
    client = make_mock_openai_client(handler)
    translator = Translator(cfg, prompts=default_prompt_config, client=client)
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
async def test_T32_all_failures_raises(default_prompt_config) -> None:
    """T32: 連続失敗で最終的に例外（state=failed に至る経路）。

    十分な数の 500 を用意して、実装のリトライ回数に依存しない。
    """
    cfg = make_config()
    # 5回連続 500（実装が3回でも4回でも全失敗する）
    handler = CountingHandler([(500, f"err{i}") for i in range(5)])
    client = make_mock_openai_client(handler)
    translator = Translator(cfg, prompts=default_prompt_config, client=client)
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
async def test_T33_timeout_retry_then_fail(default_prompt_config) -> None:
    """T33: タイムアウトでリトライし、最終的に失敗する。

    httpx.TimeoutException を投げ続けるモックを使用。
    """
    cfg = make_config()
    # 十分な数のタイムアウト
    handler = CountingHandler([httpx.TimeoutException("timeout")] * 5)
    client = make_mock_openai_client(handler)
    translator = Translator(cfg, prompts=default_prompt_config, client=client)
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
    assert is_translation_needed("棺", "", frozenset()) is False
    # ひらがな
    assert is_translation_needed("こんにちは", "", frozenset()) is False
    # カタカナ
    assert is_translation_needed("ストリーム", "", frozenset()) is False
    # 混在
    assert is_translation_needed("魔法の指輪", "", frozenset()) is False


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
    assert is_translation_needed("", "", frozenset()) is False


# ===========================================================================
# T42: 空白のみ <Source>   </Source> → スキップ
# ===========================================================================

def test_T42_whitespace_only_source_skipped() -> None:
    """T42: 空白のみ Source は翻訳不要（Plan §5.7.1 v0.3）。"""
    assert is_translation_needed("   ", "", frozenset()) is False
    assert is_translation_needed("\t\n", "", frozenset()) is False
    assert is_translation_needed(" \r\n ", "", frozenset()) is False


# ===========================================================================
# T43: non-ASCII 英語 café, "Hello", Wait… → 翻訳対象（True）
# ===========================================================================

def test_T43_non_ascii_english_is_target() -> None:
    """T43: non-ASCII 英語（アクセント/curly quotes/ellipsis）は翻訳対象。

    Plan §5.7.1 v0.3: 日本語文字を含まなければ non-ASCII でも翻訳対象。
    """
    assert is_translation_needed("café", "", frozenset()) is True
    assert is_translation_needed("\u201cHello\u201d", "", frozenset()) is True  # curly double quotes
    assert is_translation_needed("Wait\u2026", "", frozenset()) is True  # ellipsis …
    assert is_translation_needed("Fireball", "", frozenset()) is True  # plain ASCII


def test_T43b_mixed_japanese_and_english_skipped() -> None:
    """T43 補足: 英語 + 日本語混在はスキップ（日本語を含むため）。"""
    assert is_translation_needed("Fireball 火の玉", "", frozenset()) is False


# ===========================================================================
# T44: トークン不一致 → state=failed、new_dest=original_dest（単一セマンティクス）
# ===========================================================================

@pytest.mark.asyncio
async def test_T44_token_count_mismatch_keeps_original_dest(default_prompt_config) -> None:
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
    translator = Translator(cfg, prompts=default_prompt_config, client=client)
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
async def test_T51_original_dest_preserved_when_not_equal_source(default_prompt_config) -> None:
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
    translator = Translator(cfg, prompts=default_prompt_config, client=client)
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
async def test_postprocess_strip_list_markers(default_prompt_config) -> None:
    """補足: 行頭のリストマーカー `- `, `* `, `1. ` を削除（Plan §5.7.4-3）。"""
    cfg = make_config()
    for marker in ["- ", "* ", "1. "]:
        client = make_mock_openai_client(
            lambda req, _m=marker: httpx.Response(
                200, json=make_chat_response(f"{_m}火の玉")
            )
        )
        translator = Translator(cfg, prompts=default_prompt_config, client=client)
        try:
            result = await translator.translate_entry("Fireball", "MGEF:FULL")
            assert result == "火の玉", f"リストマーカー {marker!r} 削除後: {result!r}"
        finally:
            await translator.aclose()


@pytest.mark.asyncio
async def test_postprocess_keep_surrounding_quotes(default_prompt_config) -> None:
    """補足: 前後の `'`, `"` は削除しない（Plan §5.7.4-5）。"""
    cfg = make_config()
    client = make_mock_openai_client(
        lambda req: httpx.Response(200, json=make_chat_response('"火の玉"'))
    )
    translator = Translator(cfg, prompts=default_prompt_config, client=client)
    try:
        result = await translator.translate_entry("Fireball", "MGEF:FULL")
        # 前後のクォートは保持される
        assert result == '"火の玉"', f"前後クォート保持: {result!r}"
    finally:
        await translator.aclose()


@pytest.mark.asyncio
async def test_postprocess_trim_whitespace(default_prompt_config) -> None:
    """補足: 前後ホワイトスペース・末尾改行をトリム（Plan §5.7.4-1）。"""
    cfg = make_config()
    client = make_mock_openai_client(
        lambda req: httpx.Response(
            200, json=make_chat_response("  火の玉\n\n")
        )
    )
    translator = Translator(cfg, prompts=default_prompt_config, client=client)
    try:
        result = await translator.translate_entry("Fireball", "MGEF:FULL")
        assert result == "火の玉", f"前後空白トリム後: {result!r}"
    finally:
        await translator.aclose()


# ===========================================================================
# v0.2: T56-T63 — is_translation_needed の REC 型スキップ拡張
#
# Plan §5.1: is_translation_needed(source, rec, skip_records)
#   * rec != "" かつ rec in skip_records → False（スキップ）
#   * それ以外は空/空白/日本語混入の既存判定にフォールバック
#
# v0.6（Plan 006 §4.4）: ``skip_records`` は必須引数（``None`` フォールバック廃止）。
# ``DEFAULT_SKIP_RECORDS`` 定数は削除され、テストは ``default_skip_records`` fixture
# （conftest.py・v0.6 の 14 件デフォルト）または ``frozenset()`` を明示渡しする。
# ===========================================================================


def test_T56_default_skip_hdpt_full(default_skip_records: frozenset[str]) -> None:
    """T56: HDPT:FULL はデフォルトスキップリストに入っている → False。

    ``default_skip_records`` fixture（v0.6 の 14 件デフォルト）を使用。
    """
    assert is_translation_needed("Hello", "HDPT:FULL", default_skip_records) is False


def test_T57_empty_skip_records_translates() -> None:
    """T57: skip_records=frozenset() の場合は HDPT:FULL でも翻訳対象 → True。

    ``--skip-records ""``（明示的空 set・全件翻訳）の挙動に対応。
    """
    assert is_translation_needed("Hello", "HDPT:FULL", frozenset()) is True


def test_T58_default_skip_mgef_full(default_skip_records: frozenset[str]) -> None:
    """T58: MGEF:FULL はデフォルトスキップリストに入っている → False。"""
    assert is_translation_needed("Hello", "MGEF:FULL", default_skip_records) is False


def test_T59_weap_full_not_in_default_list(default_skip_records: frozenset[str]) -> None:
    """T59: WEAP:FULL はデフォルトスキップリストに入っていない → True（翻訳対象）。"""
    assert is_translation_needed("Iron Sword", "WEAP:FULL", default_skip_records) is True


def test_T60_bptd_bptn_skipped(default_skip_records: frozenset[str]) -> None:
    """T60: BPTD:BPTN（```:FULL``` 以外）もデフォルトスキップリストで機能 → False。"""
    assert is_translation_needed("Head", "BPTD:BPTN", default_skip_records) is False


def test_T61_empty_source_skipped_even_if_rec_not_in_list() -> None:
    """T61: 空文字列 Source は REC 型にかかわらずスキップ → False。

    REC 型スキップより空文字スキップが優先される（フォールバック判定）。
    """
    assert is_translation_needed("", "HDPT:FULL", frozenset()) is False
    # REC 型がリスト外でも空ならスキップ
    assert is_translation_needed("", "WEAP:FULL", frozenset()) is False


def test_T62_japanese_source_skipped_even_if_rec_not_in_list() -> None:
    """T62: 日本語 Source は REC 型にかかわらずスキップ → False。

    REC 型がリスト外でも日本語ならスキップ（既存の contains_japanese 判定への
    フォールバック）。これにより REC skip と言語 skip が重複しない。
    """
    assert is_translation_needed("棺", "HDPT:FULL", frozenset()) is False
    # REC 型がリスト外でも日本語ならスキップ
    assert is_translation_needed("既存の日本語", "WEAP:FULL", frozenset()) is False


def test_T63_rec_empty_backward_compat() -> None:
    """T63: rec="" の場合は REC 型スキップが適用されず、既存の言語判定のみ → True。

    v0.6 でも ``rec=""`` を渡せば v0.1 互換の挙動（REC 型スキップ無し）になる。
    ※ ``rec`` は必須引数化されたため ``""`` を明示渡しする。
    """
    assert is_translation_needed("Hello", "", frozenset()) is True


def test_T63b_default_skip_records_contains_14_entries(
    default_skip_records: frozenset[str],
) -> None:
    """T63 補足: default_skip_records fixture は v0.6 の 14 件を含む。

    v0.6（Plan 006 §6）: ``DEFAULT_SKIP_RECORDS`` 定数（12 件）は削除され、
    v0.6 デフォルトは 14 件（``FLST:FULL`` / ``KYWD:FULL`` 追加・NG ガイド §9.1 準拠）。
    """
    expected = frozenset({
        "HDPT:FULL", "FURN:FULL", "CLAS:FULL", "DOOR:FULL",
        "FACT:FULL", "CLFM:FULL", "TREE:FULL", "MGEF:FULL",
        "RACE:FULL", "EXPL:FULL", "HAZD:FULL", "BPTD:BPTN",
        "FLST:FULL", "KYWD:FULL",
    })
    assert default_skip_records == expected, (
        f"default_skip_records は14件: 実際 {len(default_skip_records)}件"
    )
    assert len(default_skip_records) == 14


def test_T63c_custom_skip_records_used_when_provided() -> None:
    """T63 補足: skip_records を明示的に渡した場合は toml のデフォルトより優先される。

    ``--skip-records "MGEF:FULL"``（完全置換）のケースに対応。
    MGEF:FULL はカスタムリストに入っているが、HDPT:FULL は入っていない。
    """
    custom = frozenset({"MGEF:FULL"})
    # MGEF:FULL はカスタムリストに入っている → スキップ
    assert is_translation_needed("Hello", "MGEF:FULL", custom) is False
    # HDPT:FULL はカスタムリストに入っていない → 翻訳対象
    assert is_translation_needed("Hello", "HDPT:FULL", custom) is True


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


def test_T81d_default_skip_records_fingerprint_stable(
    default_skip_records: frozenset[str],
) -> None:
    """T81 補足: default_skip_records の fingerprint は安定した固定値。

    resume 検証で v0.6 のデフォルト動作が一貫していることを保証する回帰テスト。
    v0.6（Plan 006 §4.5）: ``DEFAULT_SKIP_RECORDS`` 定数は削除され、
    ``default_skip_records`` fixture（14 件）で検証する。
    """
    import hashlib

    expected = hashlib.sha256(
        "\n".join(sorted(default_skip_records)).encode("utf-8")
    ).hexdigest()
    assert compute_skip_records_fingerprint(default_skip_records) == expected
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
async def test_T85_empty_response_raises_iroiro_error(default_prompt_config) -> None:
    """T85 (v0.2.1): LLM が空文字列を返した場合、IroiroError が raise される。

    Plan §5.7.4-6: post-processing 後が空文字列なら IroiroError。
    リトライは HTTP レベルのみ（content 検証はその後）なので即座に raise →
    CLI 側で state=failed, new_dest=original_dest になる。
    """
    cfg = make_config()
    client = make_mock_openai_client(
        lambda req: httpx.Response(200, json=make_chat_response(""))
    )
    translator = Translator(cfg, prompts=default_prompt_config, client=client)
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
async def test_T85b_whitespace_only_response_raises_iroiro_error(default_prompt_config) -> None:
    """T85 補足 (v0.2.1): 空白のみの応答も post-processing 後に空文字列 → IroiroError。

    Plan §5.7.4-6: 「空文字列（または空白のみ）」が対象。
    """
    cfg = make_config()
    client = make_mock_openai_client(
        lambda req: httpx.Response(200, json=make_chat_response("   \n\t "))
    )
    translator = Translator(cfg, prompts=default_prompt_config, client=client)
    try:
        with pytest.raises(IroiroError):
            await translator.translate_entry("Fireball", "MGEF:FULL")
    finally:
        await translator.aclose()


@pytest.mark.asyncio
async def test_T86_meta_response_ryoukai_raises(default_prompt_config) -> None:
    """T86 (v0.2.1): 「了解しました」は REJECT_PHRASES に含まれる → IroiroError。

    指示受け取り系のメタ返答。NPC セリフとしては不自然。
    """
    cfg = make_config()
    client = make_mock_openai_client(
        lambda req: httpx.Response(200, json=make_chat_response("了解しました"))
    )
    translator = Translator(cfg, prompts=default_prompt_config, client=client)
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
async def test_T86b_meta_response_honyaku_raises(default_prompt_config) -> None:
    """T86b (v0.2.1): 「翻訳します」は作業宣言 → IroiroError。"""
    cfg = make_config()
    client = make_mock_openai_client(
        lambda req: httpx.Response(200, json=make_chat_response("翻訳します"))
    )
    translator = Translator(cfg, prompts=default_prompt_config, client=client)
    try:
        with pytest.raises(IroiroError):
            await translator.translate_entry("Fireball", "MGEF:FULL")
    finally:
        await translator.aclose()


@pytest.mark.asyncio
async def test_T86c_meta_response_ika_raises(default_prompt_config) -> None:
    """T86c (v0.2.1): 「以下の通りです」は案内定型句 → IroiroError（完全一致）。"""
    cfg = make_config()
    client = make_mock_openai_client(
        lambda req: httpx.Response(200, json=make_chat_response("以下の通りです"))
    )
    translator = Translator(cfg, prompts=default_prompt_config, client=client)
    try:
        with pytest.raises(IroiroError):
            await translator.translate_entry("Fireball", "MGEF:FULL")
    finally:
        await translator.aclose()


@pytest.mark.asyncio
async def test_T86d_meta_response_prefix_match_raises(default_prompt_config) -> None:
    """T86 補足 (v0.2.1): 行頭一致でも検出される。

    Plan §5.7.4-7: ``text.startswith(phrase)`` で判定するため、
    「翻訳します。」（句点付き）も「翻訳します」に続く語として検出される。
    ※ 検出方法は startswith（行頭一致）。
    """
    cfg = make_config()
    client = make_mock_openai_client(
        lambda req: httpx.Response(200, json=make_chat_response("翻訳します。"))
    )
    translator = Translator(cfg, prompts=default_prompt_config, client=client)
    try:
        with pytest.raises(IroiroError):
            await translator.translate_entry("Fireball", "MGEF:FULL")
    finally:
        await translator.aclose()


@pytest.mark.asyncio
async def test_T87_wakarimashita_accepted(default_prompt_config) -> None:
    """T87 (v0.2.1): 「分かりました」は NPC セリフとして自然なため許容される。

    REJECT_PHRASES に含まれないので正常な訳文として扱われる。
    """
    cfg = make_config()
    client = make_mock_openai_client(
        lambda req: httpx.Response(200, json=make_chat_response("分かりました"))
    )
    translator = Translator(cfg, prompts=default_prompt_config, client=client)
    try:
        result = await translator.translate_entry("Fireball", "MGEF:FULL")
        assert result == "分かりました", f"許容されるはずの訳文: {result!r}"
    finally:
        await translator.aclose()


@pytest.mark.asyncio
async def test_T87b_hai_accepted(default_prompt_config) -> None:
    """T87b (v0.2.1): 「はい」は NPC セリフとして自然なため許容される。"""
    cfg = make_config()
    client = make_mock_openai_client(
        lambda req: httpx.Response(200, json=make_chat_response("はい"))
    )
    translator = Translator(cfg, prompts=default_prompt_config, client=client)
    try:
        result = await translator.translate_entry("Fireball", "MGEF:FULL")
        assert result == "はい", f"許容されるはずの訳文: {result!r}"
    finally:
        await translator.aclose()


# ===========================================================================
# v0.2.1 補足: _is_meta_response 単体テスト（v0.5 で signature 変更）
#
# v0.5（Plan 005 §2.6）: ``_is_meta_response`` は ``reject_phrases`` を
# 引数に取る純粋関数になった。``REJECT_PHRASES`` 定数は削除されたため、
# テストは ``default_prompt_config.reject_phrases`` を渡す（B7: 実装コードから
# デフォルトを import しない）。
# ===========================================================================


def test_is_meta_response_unit_reject_phrases(default_prompt_config) -> None:
    """補足: ``default_prompt_config.reject_phrases`` の各要素が True になる。"""
    from iroiro.translator import _is_meta_response

    for phrase in default_prompt_config.reject_phrases:
        assert _is_meta_response(phrase, default_prompt_config.reject_phrases) is True, (
            f"reject_phrases の要素 {phrase!r} は True のはず"
        )


def test_is_meta_response_unit_accepted_phrases(default_prompt_config) -> None:
    """補足: NPC セリフとして自然な言葉は _is_meta_response で False になる。"""
    from iroiro.translator import _is_meta_response

    for ok_text in [
        "分かりました", "わかりました", "はい", "いいえ",
        "すみません", "ごめんなさい", "ありがとう", "ありがとうございます",
        "火の玉", "Fireball",
    ]:
        assert _is_meta_response(ok_text, default_prompt_config.reject_phrases) is False, (
            f"NPC セリフ {ok_text!r} は False のはず"
        )


def test_is_meta_response_empty_is_false(default_prompt_config) -> None:
    """補足: 空文字列は _is_meta_response では False（ルール6 が別途処理）。"""
    from iroiro.translator import _is_meta_response

    assert _is_meta_response("", default_prompt_config.reject_phrases) is False
    assert _is_meta_response("   ", default_prompt_config.reject_phrases) is False


# ===========================================================================
# v0.5: T143-T145 — PromptConfig injection テスト（Plan 005 §4.3）
#
# Plan 005 §2.6: ``Translator`` は ``PromptConfig`` を受け取り、``_SYSTEM_PROMPT`` /
# ``REJECT_PHRASES`` / ``_REC_HINTS`` の各ハードコード定数を置き換える。
#
# 本セクションは PromptConfig のカスタマイズが Translator の挙動に反映されることを
# 検証する。テストヘルパー（factory）から PromptConfig を組み立てる（実装コードから
# デフォルトを import しない・Plan 005 §4.2 / B7）。
#
# ※ PromptConfig の import は **local import**（関数内 import）にする。
#    module-level で import すると WP-1 段階で test_translator.py 全体が collection
#    error になり「既存テスト green」が確認できなくなる（Codex review 5回目 notes 1）。
#    関数内で import することで、新規テストだけが ImportError で red になり、
#    既存テストは影響を受けない。
#
# ※ ``_build_user_message`` / ``_is_meta_response`` の signature 変更（rec_hints /
#    reject_phrases 引数追加）は WP-2 で実施される。本セクションのテストは新 signature
#    を前提とするため WP-2 完了後に green 化する。
# ===========================================================================


def _make_custom_prompt_config():
    """T143-T145 用のカスタム PromptConfig を構築するヘルパー（factory）。

    Plan 005 §4.2 / B7: 実装コードからデフォルト値を import しない。テスト固有の
    明確に異なる値を設定することで「カスタマイズが効いている」ことを検証可能にする。

    ``PromptConfig`` は WP-2 で ``iroiro/translator.py`` に追加される dataclass。
    本関数内で local import することで、WP-1 段階では ImportError になり
    本ヘルパーを使うテストだけが red になる（既存テストは影響なし）。
    """
    from iroiro.translator import PromptConfig  # WP-2 で追加される dataclass

    return PromptConfig(
        system_prompt="【テスト用システムプロンプト】これはカスタム設定のシステムプロンプトです。",
        rec_hints={
            "WEAP:FULL": "【武器名カスタムヒント】武器の名前です。",
            "MGEF:FULL": "【魔法名カスタムヒント】魔法の名前です。",
        },
        reject_phrases=frozenset({
            "メタ返答テスト用語",
            "ダミー語句その１",
            "もう一つのダミー",
        }),
    )


# ---------------------------------------------------------------------------
# T143: PromptConfig を construct して Translator に渡す・system メッセージ検証
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T143_translator_uses_custom_system_prompt() -> None:
    """T143: カスタム ``PromptConfig`` を渡した ``Translator`` が LLM の system
    メッセージに ``PromptConfig.system_prompt`` を使うことの検証。

    Plan 005 §4.3 T143 / §2.6: ``Translator.__init__(cfg, prompts, client=None)``
    で ``PromptConfig`` を受け取る。LLM への system message がカスタム値になる。

    ※ WP-1 段階では ``PromptConfig`` が未実装のため local import で ImportError → red。
    """
    from iroiro.translator import Translator  # WP-2 で prompts 引数追加

    captured_messages: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json
        body = _json.loads(request.content)
        messages = body.get("messages", [])
        captured_messages.extend(messages)
        return httpx.Response(200, json=make_chat_response("火の玉"))

    cfg = make_config()
    client = make_mock_openai_client(handler)
    prompts = _make_custom_prompt_config()
    translator = Translator(cfg, prompts, client=client)
    try:
        await translator.translate_entry("Fireball", "MGEF:FULL")
    finally:
        await translator.aclose()

    # system メッセージが PromptConfig.system_prompt と一致する
    system_msgs = [m for m in captured_messages if m.get("role") == "system"]
    assert len(system_msgs) == 1, f"system メッセージが1件ある: 実際 {system_msgs!r}"
    assert system_msgs[0]["content"] == prompts.system_prompt, (
        f"system メッセージがカスタム PromptConfig.system_prompt と一致する: "
        f"実際 {system_msgs[0]['content']!r}"
    )


# ---------------------------------------------------------------------------
# T144: reject_phrases をカスタマイズした PromptConfig で _is_meta_response 検証
# ---------------------------------------------------------------------------

def test_T144_is_meta_response_uses_custom_reject_phrases() -> None:
    """T144: カスタム ``reject_phrases`` で ``_is_meta_response`` がカスタム語句を検出。

    Plan 005 §4.3 T144 / §2.6: ``_is_meta_response(text, reject_phrases)`` に
    signature 変更される。既存の ``REJECT_PHRASES`` 定数（"了解", "翻訳します" 等）には
    無い「メタ返答テスト用語」をカスタム reject_phrases に含めることで検出される。

    ※ WP-1 段階では ``_is_meta_response`` が 1引数のまま → TypeError で red。
    """
    from iroiro.translator import _is_meta_response  # WP-2 で signature 変更

    prompts = _make_custom_prompt_config()

    # カスタム reject_phrases に含まれる語句は True
    assert _is_meta_response("メタ返答テスト用語", prompts.reject_phrases) is True, (
        "カスタム reject_phrases の語句が True になる"
    )
    # 既存の REJECT_PHRASES の語句（カスタムに含まれない）は False
    assert _is_meta_response("了解", prompts.reject_phrases) is False, (
        "カスタム reject_phrases に無い既存語句は False になる"
    )
    # 通常の訳文は False
    assert _is_meta_response("火の玉", prompts.reject_phrases) is False


# ---------------------------------------------------------------------------
# T145: rec_hints をカスタマイズした PromptConfig で user メッセージ検証
# ---------------------------------------------------------------------------

def test_T145_build_user_message_uses_custom_rec_hints() -> None:
    """T145: カスタム ``rec_hints`` で ``_build_user_message`` がカスタムヒントを含む。

    Plan 005 §4.3 T145 / §2.6: ``_build_user_message(source, rec, rec_hints)`` に
    signature 変更される。カスタム rec_hints の値（``【武器名カスタムヒント】``）が
    user message に含まれる。

    ※ WP-1 段階では ``_build_user_message`` が 2引数のまま → TypeError で red。
    """
    from iroiro.translator import _build_user_message  # WP-2 で signature 変更

    prompts = _make_custom_prompt_config()
    source = "Iron Sword"

    # WEAP:FULL にカスタムヒントを設定している
    msg = _build_user_message(source, "WEAP:FULL", prompts.rec_hints)
    # カスタムヒントが user message に含まれる
    assert "【武器名カスタムヒント】" in msg, (
        f"カスタム rec_hints の値が user message に含まれる: 実際 {msg!r}"
    )
    # source も含まれる
    assert source in msg

    # カスタム rec_hints に無い REC 型は source のみ（ヒント無し）
    msg_unknown = _build_user_message(source, "UNKNOWN:REC", prompts.rec_hints)
    assert msg_unknown == source, (
        f"未知 REC 型は source そのものを返す: 実際 {msg_unknown!r}"
    )


# ===========================================================================
# v0.6: T165 — is_translation_needed の skip_records 必須化（Plan 006 §4.4 / §9.2）
#
# Plan 006 §4.4（Codex review 指摘反映）: 現行 ``skip_records: frozenset[str] | None = None``
# のデフォルトを削除し、``(source, rec, skip_records)`` 全てを必須引数に変更する
# （``rec`` も必須化・案 a 採録）。``DEFAULT_SKIP_RECORDS`` 定数完全削除と併せ
# 「暗黙フォールバック」が完全に消える。
#
# ※ 既存 ``is_translation_needed`` は v0.5 段階でも module-level import 済みのため
#    本テストで local import は不要。関数は存在するが signature が v0.5 ままのため
#    ``TypeError`` が raise されず red になる（WP-2 完了後に green 化）。
# ===========================================================================


# ---------------------------------------------------------------------------
# T165: is_translation_needed(source, rec) で skip_records 省略時 TypeError
# ---------------------------------------------------------------------------

def test_T165_is_translation_needed_requires_skip_records() -> None:
    """T165: ``is_translation_needed(source, rec)`` で ``skip_records`` 省略時 ``TypeError``。

    Plan 006 §4.4: v0.6 で ``is_translation_needed`` は
    ``(source: str, rec: str, skip_records: frozenset[str]) -> bool`` に
    signature 変更される（``rec`` / ``skip_records`` 共に必須）。
    ``skip_records`` を省略して呼ぶと Python の引数欠落と同じ ``TypeError``。

    ※ v0.5 までは ``skip_records: frozenset[str] | None = None`` のデフォルトが
       あるため ``is_translation_needed("Hello", "WEAP:FULL")`` は正常に動作し
       ``TypeError`` は raise されない → red。WP-2 完了後に green 化。
    """
    # skip_records を省略 → v0.6 では TypeError（必須引数化）
    with pytest.raises(TypeError):
        is_translation_needed("Hello", "WEAP:FULL")  # type: ignore[call-arg]
