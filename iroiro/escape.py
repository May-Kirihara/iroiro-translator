"""プレースホルダ・トークンの検出・検証。

Plan §5.6 / §6.3 で規定される保護対象トークンの検出と、原文/訳文間の
トークン整合性検証を行う。

設計原則（Plan §5.6）:
    * アプリ側で XML エスケープ/アンエスケープはしない（lxml 任せ）。
    * 順序は問わない（日本語では語順が変わるため）。
    * 各トークンの「出現回数」が一致することを検証する。
"""

from __future__ import annotations

import re
from collections import Counter

# Plan §5.6.1: 保護対象トークンの汎用定義。
# alias 名は [A-Za-z0-9_\-]（英数字・アンダースコア・ハイフン）。
# ドット . とコロン : は v0.1 では非サポート。
PROTECTED_TOKENS_RE: re.Pattern[str] = re.compile(
    r"""
    <[A-Za-z]+=[A-Za-z0-9_\-]+>   # <alias=NAME>, <Alias=NAME>, <alias=quest-giver>
    | <br\s*/?>                     # <br>, <br/>, <br />
    | %\{[^}]+\}                    # %{name}
    | \\[nr]                        # \n, \r (リテラル2文字)
    | \#                            # # (Skyrim 色コード等)
    """,
    re.VERBOSE,
)


def extract_tokens(text: str) -> list[str]:
    """出現順にトークンを抽出する（重複含む）。

    Args:
        text: 検索対象文字列。
    Returns:
        マッチしたトークンのリスト（出現順）。マッチ無しは空リスト。
    """
    return [m.group(0) for m in PROTECTED_TOKENS_RE.finditer(text)]


def tokens_match(source_tokens: list[str], dest_tokens: list[str]) -> tuple[bool, str]:
    """原文/訳文のトークン出現回数が一致するか検証する。

    順序は問わない。各トークンの出現回数（multiset）が等しければ一致とみなす。

    Args:
        source_tokens: 原文から抽出したトークン列。
        dest_tokens: 訳文から抽出したトークン列。
    Returns:
        ``(ok, reason)``。``ok=True`` なら ``reason`` は空文字列。
        ``ok=False`` なら ``reason`` に欠落/過剰の内容を記述する。
    """
    src_counts: Counter[str] = Counter(source_tokens)
    dst_counts: Counter[str] = Counter(dest_tokens)
    if src_counts == dst_counts:
        return True, ""

    missing = src_counts - dst_counts
    extra = dst_counts - src_counts
    reasons: list[str] = []
    if missing:
        reasons.append(f"missing in dest: {dict(missing)}")
    if extra:
        reasons.append(f"extra in dest: {dict(extra)}")
    return False, "; ".join(reasons)
