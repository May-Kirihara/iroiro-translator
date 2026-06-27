"""test_escape.py — プレースホルダ・トークン検証のテスト（T11-T18, T45）。

対象モジュール: `iroiro/escape.py`
シグネチャ契約（Plan §6.3）:
    PROTECTED_TOKENS_RE: re.Pattern[str]
    def extract_tokens(text: str) -> list[str]: ...
    def tokens_match(source_tokens: list[str], dest_tokens: list[str]) -> tuple[bool, str]: ...

検証ポリシー（Plan §5.6.3）:
  - 順序は問わない（日本語では語順が変わるため）
  - 各トークンの出現回数が一致することを検証
  - 不一致時: 警告ログ + state=failed + new_dest=original_dest（translator/CLI 側）

PROTECTED_TOKENS_RE（Plan §5.6.1）:
    <[A-Za-z]+=[A-Za-z0-9_\\-]+>   # <alias=NAME>, <Alias=NAME>, <alias=quest-giver>
    | <br\\s*/?>                     # <br>, <br/>
    | %\\{[^}]+\\}                   # %{name}
    | \\\\[nr]                       # \\n, \\r (リテラル2文字)
    | \\#                           # # (Skyrim 色コード等)

注記: テスト中の "\\n" は Python 文字列リテラルで「バックスラッシュ1文字 + n」の2文字。
"""
from __future__ import annotations

import re

from iroiro.escape import PROTECTED_TOKENS_RE, extract_tokens, tokens_match

# ===========================================================================
# T11: <alias=questgiver> 抽出
# ===========================================================================

def test_T11_extract_alias_questgiver() -> None:
    """T11: <alias=questgiver> を抽出する。"""
    text = "<alias=questgiver>からあなたに渡すものがある"
    tokens = extract_tokens(text)
    assert tokens == ["<alias=questgiver>"]


# ===========================================================================
# T12: <Alias=Questgiver> 大文字小文字混在
# ===========================================================================

def test_T12_extract_alias_case_insensitive_tag() -> None:
    """T12: <Alias=NAME>（大文字始まり）も抽出する。

    PROTECTED_TOKENS_RE の `<[A-Za-z]+=...>` は大小両方を許容。
    """
    text = "<Alias=QuestGiver>からアイテムを受け取った"
    tokens = extract_tokens(text)
    assert tokens == ["<Alias=QuestGiver>"]


# ===========================================================================
# T13: 1行に複数トークン <alias=a> と <alias=b>
# ===========================================================================

def test_T13_multiple_tokens_in_one_line() -> None:
    """T13: 1行に複数トークンが出現する場合は出現順に全て抽出する。"""
    text = "<alias=location2> にいる <alias=client2> に荷物を配達する"
    tokens = extract_tokens(text)
    assert tokens == ["<alias=location2>", "<alias=client2>"]


# ===========================================================================
# T14: 隣接日本語 <alias=client>に届ける
# ===========================================================================

def test_T14_alias_adjacent_to_japanese() -> None:
    """T14: <alias=client> に日本語が隣接していても抽出できる。"""
    text = "ハチミツ酒を<alias=client>に届けた"
    tokens = extract_tokens(text)
    assert tokens == ["<alias=client>"]


# ===========================================================================
# T15: <br>, %{name}, \n, # の各抽出
# ===========================================================================

def test_T15_extract_all_token_types() -> None:
    """T15: 各トークン種別（br/%{...}/\\n/#）を抽出する。"""
    # <br>, %{name}, \n (リテラル2文字), # を1行に混在
    text = "Line1<br>Line2%{name}END\\n#color"
    tokens = extract_tokens(text)
    # 出現順
    assert "<br>" in tokens
    assert "%{name}" in tokens
    assert "\\n" in tokens  # バックスラッシュ+n の2文字
    assert "#" in tokens
    # 順序確認
    assert tokens == ["<br>", "%{name}", "\\n", "#"]


def test_T15a_extract_br_variants() -> None:
    """T15 補足: <br>, <br/>, <br /> の各バリエーション。"""
    for br_variant in ["<br>", "<br/>", "<br />"]:
        tokens = extract_tokens(f"a{br_variant}b")
        assert tokens == [br_variant], f"{br_variant} が抽出される"


def test_T15b_extract_hash_color_codes() -> None:
    """T15 補足: Skyrim 色コード `#` は出現回数分抽出される。"""
    text = "#Steel Armor#"
    tokens = extract_tokens(text)
    # `#` が2個 → 2回マッチ
    assert tokens == ["#", "#"]


# ===========================================================================
# T16: トークン順序違いはOK（tokens_match True）
# ===========================================================================

def test_T16_token_order_does_not_matter() -> None:
    """T16: <alias=a><alias=b> と <alias=b><alias=a> は一致（順序問わず）。

    Plan §5.6.3: 日本語では語順が変わるため、順序は問わない。
    """
    source = "<alias=a>と<alias=b>"
    dest = "<alias=b>と<alias=a>"
    src_tokens = extract_tokens(source)
    dst_tokens = extract_tokens(dest)
    ok, reason = tokens_match(src_tokens, dst_tokens)
    assert ok, f"順序違いはOK であるべき: {reason}"


# ===========================================================================
# T17: トークン欠落はNG（tokens_match False）
# ===========================================================================

def test_T17_missing_token_fails() -> None:
    """T17: 原文に <alias=a><alias=b> があるが訳文に <alias=a> しか無い → 不一致。"""
    source = "<alias=a>と<alias=b>"
    dest = "<alias=a>のみ"  # <alias=b> 欠落
    src_tokens = extract_tokens(source)
    dst_tokens = extract_tokens(dest)
    ok, reason = tokens_match(src_tokens, dst_tokens)
    assert not ok, "トークン欠落は不一致"
    assert reason, "不一致理由が返される"


# ===========================================================================
# T18: トークン回数不一致はNG
# ===========================================================================

def test_T18_count_mismatch_fails() -> None:
    """T18: 原文に <alias=a> が1個、訳文に2個 → 回数不一致で NG。"""
    source = "<alias=a>"
    dest = "<alias=a>と<alias=a>"
    src_tokens = extract_tokens(source)
    dst_tokens = extract_tokens(dest)
    ok, reason = tokens_match(src_tokens, dst_tokens)
    assert not ok, "回数不一致は NG"
    assert reason


def test_T18b_same_tokens_same_count_matches() -> None:
    """T18 補足: 同トークン同数は一致。"""
    source = "<alias=a><alias=a>"
    dest = "<alias=a><alias=a>"
    ok, _ = tokens_match(extract_tokens(source), extract_tokens(dest))
    assert ok


# ===========================================================================
# T45: ハイフン含む alias <alias=quest-giver> → 許容・抽出される
# ===========================================================================

def test_T45_hyphen_in_alias_name() -> None:
    """T45: <alias=quest-giver>（ハイフン含む）を許容・抽出する。

    Plan §5.6.1: `[A-Za-z0-9_\\-]` でハイフンを許容。
    """
    text = "<alias=quest-giver>が話しかけてきた"
    tokens = extract_tokens(text)
    assert tokens == ["<alias=quest-giver>"], "ハイフン含む alias を抽出"


def test_T45b_no_tokens_returns_empty() -> None:
    """T45 補足: トークン無しのテキストは空リスト。"""
    assert extract_tokens("plain english text") == []
    assert extract_tokens("") == []


def test_T45c_tokens_match_both_empty() -> None:
    """T45 補足: 両方空リストは一致。"""
    ok, _ = tokens_match([], [])
    assert ok


# ===========================================================================
# PROTECTED_TOKENS_RE の直接検証（補助）
# ===========================================================================

def test_protected_tokens_re_compiled() -> None:
    """PROTECTED_TOKENS_RE が re.Pattern として定義されている。"""
    assert isinstance(PROTECTED_TOKENS_RE, re.Pattern)
    # VERBOSE フラグが入っているか（空白無視）
    # 直接フラグ検証は実装依存だが、少なくともマッチ可能であること
    assert PROTECTED_TOKENS_RE.search("<alias=hero>")
    assert PROTECTED_TOKENS_RE.search("<br>")
    assert PROTECTED_TOKENS_RE.search("%{name}")
    assert PROTECTED_TOKENS_RE.search("\\n")
    assert PROTECTED_TOKENS_RE.search("#")
