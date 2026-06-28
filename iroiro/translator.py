"""翻訳エンジン — OpenAI 互換 LLM クライアント。

Plan §5.7 / §6.4 で規定される ``Translator`` と ``ApiConfig``、および
``is_translation_needed`` / ``contains_japanese`` を実装する。

設計の要点:
    * 非同期: ``openai.AsyncOpenAI`` を使用し ``Semaphore`` で同時リクエストを制限する。
    * Source 言語判定: 空/空白/日本語混入 はスキップ（``is_translation_needed`` が False）。
    * 長文スキップ: ``len(source) > max_chars`` は CLI 側でスキップ（translator は呼ばれない）。
    * post-processing: strip → フェンス削除 → 最初の行 → ラベル削除 → リストマーカー削除。
    * トークン整合性: 不一致なら ``IroiroError`` を raise（呼出側で state=failed にする）。
    * リトライ: 最大3回試行、指数バックオフ ``[1, 2]``（失敗時 ``IroiroError`` で wrap）。
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

import httpx
import openai

from iroiro.errors import IroiroError
from iroiro.escape import extract_tokens, tokens_match

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 設定 dataclass
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ApiConfig:
    """API 呼び出し設定（Plan §6.4）。

    Attributes:
        base_url: OpenAI 互換 API のベース URL。
        api_key: API キー。llama.cpp では検証されないが ``Authorization: Bearer`` で送信。
        model: モデル名。
        timeout: 1リクエストの読み出しタイムアウト（秒）。
        concurrency: 同時リクエスト数上限。
        max_chars: 1エントリあたりの最大文字数。超過時スキップ。
    """

    base_url: str
    api_key: str
    model: str
    timeout: float
    concurrency: int
    max_chars: int


# ---------------------------------------------------------------------------
# Source 言語判定
# ---------------------------------------------------------------------------


# ひらがな U+3040-309F / カタカナ U+30A0-30FF / CJK統合漢字 U+4E00-9FFF
_JAPANESE_RE: re.Pattern[str] = re.compile(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]")


def contains_japanese(text: str) -> bool:
    """ひらがな/カタカナ/CJK統合漢字 を含むか（Plan §5.7.1）。

    ※ CJK Extension B/C/D 等 (U+20000-) は v0.1 では非サポート。
    """
    return _JAPANESE_RE.search(text) is not None


DEFAULT_SKIP_RECORDS: frozenset[str] = frozenset({
    "HDPT:FULL",  # Head Part name
    "FURN:FULL",  # Furniture name
    "CLAS:FULL",  # Class name
    "DOOR:FULL",  # Door name
    "FACT:FULL",  # Faction name
    "CLFM:FULL",  # Color Form name
    "TREE:FULL",  # Tree name
    "MGEF:FULL",  # Magic Effect name
    "RACE:FULL",  # Race name
    "EXPL:FULL",  # Explosion name
    "HAZD:FULL",  # Hazard name
    "BPTD:BPTN",  # Body Part Data name
})


def is_translation_needed(
    source: str,
    rec: str = "",
    skip_records: frozenset[str] | None = None,
) -> bool:
    """翻訳が必要か（Plan §5.7.1 v0.3 + v0.2 REC 型スキップ拡張）。

    Args:
        source: ``<Source>`` の生文字列。
        rec: ``<REC>`` の値（例: ``"HDPT:FULL"``）。空文字列も可（後方互換性）。
        skip_records: スキップ対象 REC 型のセット。``None`` の場合は
            :data:`DEFAULT_SKIP_RECORDS` を使用。

    Returns:
        ``True`` = 翻訳対象, ``False`` = スキップ。

    判定順序:

    1. ``rec`` が ``skip_records`` に含まれる → ``False``（REC 型スキップ）
    2. 空 または 空白のみ → ``False``
    3. ひらがな・カタカナ・漢字を含む → ``False``
    4. それ以外（ASCIIのみ、non-ASCII 英語含む）→ ``True``

    後方互換性: ``rec=""`` の場合は REC 型スキップが適用されず、
    v0.1 の ``is_translation_needed(source)`` と同じ挙動。
    """
    if skip_records is None:
        skip_records = DEFAULT_SKIP_RECORDS
    if rec and rec in skip_records:
        return False
    if source is None or not source or not source.strip():
        return False
    if contains_japanese(source):
        return False
    return True


def _parse_skip_records(text: str) -> frozenset[str]:
    """``--skip-records`` のカンマ区切りテキストを :class:`frozenset` に変換。

    仕様（Plan §5.2b）:

    * カンマで分割
    * 各要素は strip（前後空白を許容）
    * 空文字列要素は無視（``"A,,B"`` → ``{A, B}``）
    * 重複は自動で排除（frozenset の性質）
    * 大文字小文字は区別しない（``hdpt:full`` → ``HDPT:FULL`` に正規化）
        ※ REC 型は Skyrim 側で大文字で定義されているため
    """
    if not text.strip():
        return frozenset()
    parts = [p.strip().upper() for p in text.split(",")]
    return frozenset(p for p in parts if p)


# ---------------------------------------------------------------------------
# プロンプト（Plan §5.7.3）
# ---------------------------------------------------------------------------


_SYSTEM_PROMPT = (
    "Skyrim MOD の英文を日本語に翻訳する。"
    "固有名詞・ <alias=...> 等のプレースホルダ・ <br>・改行文字・ # 記号は "
    "**そのまま維持** すること。"
    "簡潔で自然な日本語。**訳文のみ** 出力し、"
    "説明・マークダウン・ラベル・複数行は禁止。"
)


# ``<REC>`` 別のプロンプトヒント（Plan §5.7.3 user message）。
# ヒントが無い REC は汎用メッセージを使う。
_REC_HINTS: dict[str, str] = {
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
}


def _build_user_message(source: str, rec: str) -> str:
    """``<REC>`` 別のヒント + 原文 で user メッセージを構築する。"""
    hint = _REC_HINTS.get(rec)
    if hint:
        return f"{hint}\n\n{source}"
    return source


# ---------------------------------------------------------------------------
# post-processing（Plan §5.7.4）
# ---------------------------------------------------------------------------


# 行頭の「訳文:」「Translation:」等のラベル。: の前後に空白を許容。
_LABEL_RE: re.Pattern[str] = re.compile(
    r"^(訳文|Translation|日本語|Result|Output)\s*[:：]\s*",
    re.IGNORECASE,
)
# 行頭のリストマーカー（``-``/``*``/``数字.`` + 空白）。
_LIST_MARKER_RE: re.Pattern[str] = re.compile(r"^([-*]|\d+\.)\s+")
# 前後の ``` フェンス（言語指定付きも許容）。
_FENCE_START_RE: re.Pattern[str] = re.compile(r"^```[^\n]*\n?")
_FENCE_END_RE: re.Pattern[str] = re.compile(r"\n?```\s*$")
# 行内の ``` 単体（先頭/末尾以外に出現した場合）。
_FENCE_LINE_RE: re.Pattern[str] = re.compile(r"^\s*```\s*$")


def _postprocess(raw: str) -> str:
    """LLM 出力の post-processing（Plan §5.7.4）。

    順序（T27/T28/T29 等のテストを全て通すための重要な順序）:
        1. 前後 whitespace・末尾改行を strip。
        2. `` ``` `` フェンスを削除（行頭/行末/行内）。
        3. 最初の行のみ採用（複数行返却時）。
        4. 行頭のラベル（``訳文:`` 等）を削除。
        5. 行頭のリストマーカー（``- ``/``* ``/``1. ``）を削除。

    ※ 前後の ``'``/``"`` は削除しない（Plan §5.7.4-5）。
    """
    text = raw.strip()

    # フェンス削除: 先頭/末尾/行内
    text = _FENCE_START_RE.sub("", text)
    text = _FENCE_END_RE.sub("", text)
    text = text.strip()

    # 複数行の場合は最初の行のみ採用
    if "\n" in text:
        first_line = text.split("\n", 1)[0].strip()
        # フェンスのみの行をスキップした後に最初の実質行を取り直す
        lines = [ln.strip() for ln in text.split("\n")]
        non_fence = [ln for ln in lines if not _FENCE_LINE_RE.match(ln)]
        if non_fence:
            text = non_fence[0]
        else:
            text = first_line

    text = text.strip()

    # ラベル削除
    text = _LABEL_RE.sub("", text).strip()

    # リストマーカー削除
    text = _LIST_MARKER_RE.sub("", text).strip()

    return text


# ---------------------------------------------------------------------------
# Translator
# ---------------------------------------------------------------------------


# リトライ対象例外（Plan §5.7.5）
_RETRYABLE_EXC: tuple[type[BaseException], ...] = (
    openai.APIError,
    httpx.TimeoutException,
    httpx.NetworkError,
)


class Translator:
    """OpenAI 互換 LLM で英文を日本語訳する（Plan §5.7 / §6.4）。

    Args:
        cfg: API 設定。
        client: ``openai.AsyncOpenAI`` インスタンス。``None`` の場合は ``cfg`` から構築する。
            テスト容易性のため DI 可能（``httpx.MockTransport`` を注入）。

    Usage:
        translator = Translator(cfg)
        try:
            translated = await translator.translate_entry(source, rec)
        finally:
            await translator.aclose()
    """

    def __init__(
        self,
        cfg: ApiConfig,
        client: openai.AsyncOpenAI | None = None,
    ) -> None:
        self._cfg = cfg
        if client is None:
            self._client = openai.AsyncOpenAI(
                base_url=cfg.base_url,
                api_key=cfg.api_key,
                timeout=httpx.Timeout(
                    connect=10.0,
                    read=cfg.timeout,
                    write=10.0,
                    pool=10.0,
                ),
            )
        else:
            self._client = client
        self._sem = asyncio.Semaphore(max(1, cfg.concurrency))

    async def translate_entry(self, source: str, rec: str) -> str:
        """1エントリを翻訳する。

        Args:
            source: 翻訳元文字列（``<Source>`` の値、XMLエスケープ解除済）。
            rec: ``<REC>`` の値（プロンプトヒント用）。

        Returns:
            翻訳後文字列（post-processing 済）。この値を ``<Dest>.text`` にセットする。

        Raises:
            IroiroError: トークン不一致、またはリトライ最終失敗。
        """
        # 呼出側でのスキップを前提とするが、念のため空/空白はそのまま返す
        # ※ REC 型スキップ・日本語スキップは CLI 側で判定する（Plan §5.2・申送り#7）。
        #    Translator は is_translation_needed を呼ばない（MGEF:FULL 等の REC skip が
        #    translator 内で発動すると単体テストが破綻するため）。
        if source is None or not source.strip():
            return source

        async with self._sem:
            raw = await self._translate_with_retry(source, rec)

        cleaned = _postprocess(raw)

        # トークン整合性検証（Plan §5.6.3 / §5.7.4-4）
        src_tokens = extract_tokens(source)
        dst_tokens = extract_tokens(cleaned)
        ok, reason = tokens_match(src_tokens, dst_tokens)
        if not ok:
            _logger.warning(
                "token mismatch for rec=%s source=%r raw=%r cleaned=%r: %s",
                rec,
                source,
                raw,
                cleaned,
                reason,
            )
            raise IroiroError(f"token mismatch ({reason})")

        return cleaned

    async def _translate_with_retry(self, source: str, rec: str) -> str:
        """LLM へのリクエストを最大3回試行する（Plan §5.7.5）。

        リトライ対象: ``openai.APIError``, ``httpx.TimeoutException``, ``httpx.NetworkError``。
        backoff: ``[1, 2]`` 秒（``asyncio.sleep`` 経由、テストで即座化される）。
        最終失敗時: ``IroiroError`` で wrap して raise。
        """
        # 初回 + リトライ2回 = 計3回試行
        delays = (1.0, 2.0)
        last_exc: BaseException | None = None
        for attempt in range(3):
            try:
                resp = await self._client.chat.completions.create(
                    model=self._cfg.model,
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": _build_user_message(source, rec)},
                    ],
                )
                content = resp.choices[0].message.content
                return content or ""
            except _RETRYABLE_EXC as e:
                last_exc = e
                _logger.info(
                    "translation attempt %d failed for rec=%s: %s",
                    attempt + 1,
                    rec,
                    e,
                )
                if attempt < len(delays):
                    await asyncio.sleep(delays[attempt])

        raise IroiroError(
            f"translation failed after {3} attempts for rec={rec}"
        ) from last_exc

    async def aclose(self) -> None:
        """内部 HTTP クライアントを閉じる。"""
        # openai.AsyncOpenAI の close は coro
        close = getattr(self._client, "close", None)
        if close is not None:
            result = close()
            if asyncio.iscoroutine(result):
                await result
