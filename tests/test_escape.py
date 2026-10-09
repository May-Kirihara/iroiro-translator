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


# ===========================================================================
# v0.7: MCM 数値プレースホルダ ``{N}`` 保護拡張（Plan 007 §3.3 / §5.2）
#
# WP-2 で ``PROTECTED_TOKENS_RE`` に ``\{\d+\}``（``{0}`` / ``{1}`` / ``{12}`` 等）
# を追加する。本テスト群は実装前なので T-ESC-N / N2 / N4 は RED・N3（既存トークン回帰）
# は GREEN。N5 は既存ルール（``\n`` リテラル2文字）が MCM 値でも働くことを検証。
# ``{N}`` は Skyrim MCM の GlobalVariable 置換で、出現回数を完全保存しないと MCM 表示が
# 崩れるため保護対象に追加する（安全方向の厳密化）。
# ===========================================================================

def test_T_ESC_N_extract_numeric_placeholders() -> None:
    """T-ESC-N: ``{0}`` ``{12}`` 等の数値プレースホルダを抽出する（Plan 007 §3.3）。

    ``extract_tokens("a {0} b {12}")`` が ``["{0}", "{12}"]`` を返す。
    順序は出現順だが、set 比較で OK とする（順序非依存）。
    """
    tokens = extract_tokens("a {0} b {12}")
    assert set(tokens) == {"{0}", "{12}"}, f"数値プレースホルダを抽出: {tokens!r}"
    # 2個とも検出
    assert len(tokens) == 2


def test_T_ESC_N2_tokens_match_missing_placeholder() -> None:
    """T-ESC-N2: 原文の ``{0}`` 1個が訳文で欠落 → ``tokens_match`` が False（missing 報告）。

    MCM の ``{N}`` 保存はトークン整合性検証が強制保証する（§3.3）。
    """
    source = "Hello {0} World"
    dest = "こんにちは世界"  # {0} 欠落
    ok, reason = tokens_match(extract_tokens(source), extract_tokens(dest))
    assert not ok, "``{0}`` 欠落は不一致"
    assert "missing" in reason, f"missing 報告: {reason!r}"


def test_T_ESC_N3_existing_tokens_regression() -> None:
    """T-ESC-N3: 既存トークン（``<alias>`` / ``%{x}`` / ``#`` / ``\\n``）検出に回帰無し。

    ``{N}`` regex 拡張が既存トークン種別を壊さないことを検証する（Plan 007 §7 リスク）。
    本テストは WP-1 完了時点でも GREEN（既存 ``PROTECTED_TOKENS_RE`` で検出可能）。
    """
    text = "<alias=hero> <br/> %{x} # \\n"
    tokens = extract_tokens(text)
    token_set = set(tokens)
    # 既存トークン種別が全て検出される
    assert "<alias=hero>" in token_set
    assert "<br/>" in token_set
    assert "%{x}" in token_set
    assert "#" in token_set
    assert "\\n" in token_set


def test_T_ESC_N4_double_brace_overmatch_pinned() -> None:
    """T-ESC-N4: ``{{0}}`` 過剰マッチ挙動の pin（Plan 007 §3.3・安全バイアス）。

    単純な ``\\{\\d+\\}`` は ``{{0}}`` の内側の ``{0}`` にもマッチする。
    これは安全バイアス（保護しすぎる方向）として受容する。両辺で同数なら整合 OK になる。
    WP-2 完了後は ``{{0}}`` から ``{0}`` 1個が抽出されることを期待して挙動を pin する。
    """
    tokens = extract_tokens("{{0}}")
    # ``{{0}}`` の内側 ``{0}`` を1個として抽出する（過剰マッチ・安全バイアス）
    assert tokens == ["{0}"], (
        f"``{{{{0}}}}`` は内側の ``{{0}}`` を1個として抽出（pin）: {tokens!r}"
    )


def test_T_ESC_N5_literal_backslash_n_in_mcm_value() -> None:
    """T-ESC-N5: MCM 値に ``\\n``（リテラル2文字）含む場合の検出（既存ルール）。

    既存の ``\\\\[nr]`` ルールが MCM 値でもそのまま働くことを検証。
    抽出だけでなく ``tokens_match`` の整合性検証も併せて確認する
    （Codex non-blocking 指摘: 抽出だけでは不十分・整合性検証までカバー）。
    """
    # ``\n`` は Python ソースでは「バックスラッシュ1文字 + n」の2文字（リテラル）
    value = "Line1\\nLine2"
    tokens = extract_tokens(value)
    assert "\\n" in tokens, f"リテラル ``\\\\n`` を検出: {tokens!r}"

    # tokens_match 整合性検証: 同じテキスト同士は一致
    ok, reason = tokens_match(extract_tokens(value), extract_tokens(value))
    assert ok, f"同じテキスト同士は整合 OK: {reason}"

    # ``\\n`` を欠落させた訳文は不一致（整合性検証が機能する証拠）
    dest_no_token = "Line1Line2"
    ok2, reason2 = tokens_match(
        extract_tokens(value), extract_tokens(dest_no_token)
    )
    assert not ok2, f"\\n トークン欠落は不一致: {reason2!r}"
    assert reason2, "不一致理由が返される"


def test_T_ESC_N6_positive_match() -> None:
    """T-ESC-N6: ``{0}`` が両辺に同数あれば ``tokens_match`` が ``(True, "")``（陽性 pin）。

    T-ESC-N2 は陰性（``{0}`` 欠落で不一致）のみ pin する。本テストは陽性 pin として
    ``tokens_match(["{0}"], ["{0}"])`` が ``(True, "")`` を返すことを検証し、
    ``{N}`` 抽出（T-ESC-N）だけでなく整合性検証の陽性ケースをカバーする
    （Plan 007 §3.3）。明示リストを渡すため ``PROTECTED_TOKENS_RE`` の ``{N}`` 拡張
    有無に依存せず、``tokens_match`` の multiset 比較ロジックを直接 pin する。
    """
    ok, reason = tokens_match(["{0}"], ["{0}"])
    assert ok, f"``{{0}}`` 同数は整合 OK: {reason}"
    assert reason == "", f"整合時の理由は空文字: {reason!r}"
