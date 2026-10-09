"""test_mcm_io.py — MCM TXT I/O のテスト（Plan 007 §5.1）。

対象モジュール: ``iroiro/mcm_io.py``（WP-2 で新設されるまで本テストは RED）。

シグネチャ契約（Plan 007 §3.6 / §3.7）::

    @dataclass(slots=True)
    class McmFormat:
        has_bom: bool
        newline: Literal["\\r\\n", "\\n"]
        encoding: Literal["utf-16-le", "utf-16-be", "utf-8"]
        has_trailing_newline: bool

    def parse_mcm(path: Path) -> tuple[list[StringEntry], McmFormat, object]: ...
    def serialize_mcm(entries: list[StringEntry], lines: object, fmt: McmFormat) -> bytes: ...

テスト容易性のため:
  - ``parse_mcm`` 戻り値の ``lines``（行モデル）は **opaque** として扱う。
    テストは ``lines`` の内部構造を assert せず、``parse_mcm`` → ``serialize_mcm``
    の round-trip で振る舞いを検証する（Plan 007 §3.6）。
  - WP-1 段階では ``iroiro/mcm_io.py`` が未実装のため、各テストは **関数スコープ** で
    ``mcm_io`` を import する。これにより pytest の collection は成功し、個別テストが
    ``ImportError`` で fail する（test-first RED）。
"""
from __future__ import annotations

from pathlib import Path

# mcm_tiny.txt の parse 期待値（Plan 007 §5.4・フィクスチャ仕様と一致）。
# (edid, source) の index 順。original_dest == source, rec="", state="pending"。
_MCM_TINY_EXPECTED: list[tuple[str, str]] = [
    ("$MCM_TITLE", "Hello {0} World"),
    ("$MCM_OPT_YES", "Yes"),
    ("$MCM_DESC", "Toggle this option"),
    ("$MCM_MULTI", "key\twith\ttabs"),
    ("$MCM_EMPTY", ""),
    ("", ""),
    ("$MCM_JP", "これは日本語です"),
]


# ===========================================================================
# 補助: parse_mcm を関数スコープで import するヘルパー
# ===========================================================================

def _import_mcm_io():
    """``iroiro.mcm_io`` を import して主要シンボルを返す。

    WP-1 段階では ``ModuleNotFoundError`` になる（test-first RED）。
    各テストから呼ぶことで collection 段階の失敗を避け、個別テストの fail にする。
    """
    from iroiro.mcm_io import (  # type: ignore[attr-defined]
        McmFormat,
        parse_mcm,
        serialize_mcm,
    )
    return McmFormat, parse_mcm, serialize_mcm


def _assert_entry(entry, index: int, edid: str, source: str) -> None:
    """1エントリが期待通りか検証（Plan 007 §3.2.1 / §3.6）。

    MCM エントリの構築契約:
      - ``index``: 翻訳可能エントリ通し番号（物理行番号ではない）
      - ``edid``: キー（``$`` prefix 無しも可・``split("\\t",1)`` の左辺）
      - ``rec``: 常に ``""``（MCM に REC 概念は無い）
      - ``source``: 値（``split("\\t",1)`` の右辺）
      - ``original_dest``: ``source`` と同一（skip/fail 時の英文保持・§3.2.1）
      - ``new_dest``: ``None``（未処理）
      - ``state``: ``"pending"``
    """
    from iroiro.models import StringEntry

    assert isinstance(entry, StringEntry), f"entry は StringEntry: {type(entry)!r}"
    assert entry.index == index, f"index: {entry.index!r} != {index!r}"
    assert entry.edid == edid, f"edid: {entry.edid!r} != {edid!r}"
    assert entry.rec == "", f"rec は空文字: {entry.rec!r}"
    assert entry.source == source, f"source: {entry.source!r} != {source!r}"
    assert entry.original_dest == source, (
        f"original_dest は source と同一（§3.2.1 英文保持）: "
        f"{entry.original_dest!r} != {source!r}"
    )
    assert entry.new_dest is None, f"new_dest は None（未処理）: {entry.new_dest!r}"
    assert entry.state == "pending", f"state は pending: {entry.state!r}"


# ===========================================================================
# T-MCM-01: mcm_tiny.txt の parse → entries が期待値と一致
# ===========================================================================

def test_T_MCM_01_parse_entries(mcm_tiny_txt: Path) -> None:
    """T-MCM-01: mcm_tiny.txt を parse し entries が期待通り（edid/source/original_dest/state/rec=""）。"""
    _, parse_mcm, _ = _import_mcm_io()
    entries, _fmt, _lines = parse_mcm(mcm_tiny_txt)

    assert len(entries) == len(_MCM_TINY_EXPECTED), (
        f"翻訳可能エントリ数: {len(entries)} != {len(_MCM_TINY_EXPECTED)}"
    )
    for i, (edid, source) in enumerate(_MCM_TINY_EXPECTED):
        _assert_entry(entries[i], i, edid, source)


# ===========================================================================
# T-MCM-02: round-trip フォーマット保存（値未変更・論理同一バイト）
# ===========================================================================

def test_T_MCM_02_roundtrip_format_preserved(mcm_tiny_txt: Path) -> None:
    """T-MCM-02: entries を変更せず serialize すると入力バイトを再現する。

    値を1つも翻訳していないため、round-trip は論理的に入力と同一バイトになるはず
    （入力は既に CRLF 正規化済み・末尾改行無し・UTF-16 LE BOM）。fmt の各属性も保存。
    """
    _, parse_mcm, serialize_mcm = _import_mcm_io()
    entries, fmt, lines = parse_mcm(mcm_tiny_txt)
    out = serialize_mcm(entries, lines, fmt)

    original = mcm_tiny_txt.read_bytes()
    assert out == original, (
        "round-trip で入力バイトを再現する（値未変更・CRLF 正規化済入力）"
    )
    # fmt 属性の保存も明示的に確認
    assert fmt.has_bom is True
    assert fmt.newline == "\r\n"
    assert fmt.encoding == "utf-16-le"
    assert fmt.has_trailing_newline is False


# ===========================================================================
# T-MCM-03: 改行混在入力 → 支配的改行（CRLF）へ正規化（バイト同一を主張しない）
# ===========================================================================

def test_T_MCM_03_mixed_newline_normalized(tmp_path: Path) -> None:
    """T-MCM-03: CRLF + LF 混在入力を支配的改行（CRLF）へ正規化する（Plan 007 §3.2）。

    完全なバイト同一性は保証しない（意図的正規化）。混在入力を出力した結果、
    全ての改行が支配的（CRLF）に正規化されていることを assert する。
    LF-only 改行バイト（``0x0A`` not preceded by ``0x0D``）が残っていないことを検証。
    """
    _, parse_mcm, serialize_mcm = _import_mcm_io()

    # CRLF 2件 + LF-only 2件の混在ファイル（支配的は CRLF）を UTF-8 で作成
    mixed = tmp_path / "mixed.txt"
    content = "$A\tone\r\n$B\ttwo\n$C\tthree\r\n$D\tfour\n"
    mixed.write_text(content, encoding="utf-8")

    entries, fmt, lines = parse_mcm(mixed)
    assert fmt.newline == "\r\n", "支配的改行は CRLF（2件 vs 2件の場合 CRLF 優先）"

    out = serialize_mcm(entries, lines, fmt)
    decoded = out.decode("utf-8")

    # 正規化後は LF-only 改行（\r に先行されない \n）が存在しない
    # → 全ての \n は \r\n の一部でなければならない
    # ``replace("\r\n", "")`` した後に ``\n`` が残らないことを確認
    assert "\n" not in decoded.replace("\r\n", ""), (
        "混在改行は支配的 CRLF へ正規化される（LF-only は残らない）"
    )
    # 支配的改行で統一されているので CRLF を含む
    assert "\r\n" in decoded

    # 全論理行が生存していることの軽量 content assert
    # （正規化で行が消滅していないことの確認・Codex non-blocking 指摘）
    assert "$A\t" in decoded, f"$A 行が生存: {decoded!r}"
    assert "$B\t" in decoded, f"$B 行が生存: {decoded!r}"
    assert "$C\t" in decoded, f"$C 行が生存: {decoded!r}"
    assert "$D\t" in decoded, f"$D 行が生存: {decoded!r}"
    # 各行の値も保持（値が消滅・結合されていない）
    assert "one" in decoded and "two" in decoded
    assert "three" in decoded and "four" in decoded


# ===========================================================================
# T-MCM-04: {0} プレースホルダ含むエントリの parse
# ===========================================================================

def test_T_MCM_04_placeholder_entry(mcm_tiny_txt: Path) -> None:
    """T-MCM-04: ``{0}`` プレースホルダを含むエントリ（index 0）が正しく parse される。"""
    _, parse_mcm, _ = _import_mcm_io()
    entries, _fmt, _lines = parse_mcm(mcm_tiny_txt)

    assert entries[0].source == "Hello {0} World"
    assert "{0}" in entries[0].source


# ===========================================================================
# T-MCM-05: 空行・コメント行が lines モデル経由で serialize 後も保持される
# ===========================================================================

def test_T_MCM_05_passthrough_lines_preserved(mcm_tiny_txt: Path) -> None:
    """T-MCM-05: 空行・タブ無し非空行（コメント）が serialize 後も保持される（Plan 007 §3.6）。

    lines モデルは opaque だが、round-trip 結果のバイト（UTF-16 LE として decode）
    にコメント行文字列と空行構造が残っていることを検証する。
    """
    _, parse_mcm, serialize_mcm = _import_mcm_io()
    entries, fmt, lines = parse_mcm(mcm_tiny_txt)
    out = serialize_mcm(entries, lines, fmt)

    decoded = out[2:].decode("utf-16-le")  # BOM (ff fe) を除外
    assert "# this is a comment line (tabless, passthrough)" in decoded, (
        "コメント行（タブ無し非空行）は serialize 後も保持される"
    )
    # 空行も保持（CRLF が連続する箇所 = 空行）
    assert "\r\n\r\n" in decoded, "空行が保持される"


# ===========================================================================
# T-MCM-06: serialize_mcm が new_dest を値に書く（$KEY 保存）
# ===========================================================================

def test_T_MCM_06_serialize_writes_new_dest(mcm_tiny_txt: Path) -> None:
    """T-MCM-06: ``new_dest`` を設定した entry の値が訳文で書き出される（``$KEY`` 保存）。

    index 1（``$MCM_OPT_YES`` → ``Yes``）の ``new_dest`` を ``はい`` に設定し、
    serialize 結果に ``$MCM_OPT_YES\\tはい`` 行が含まれることを検証。
    他の行の ``$KEY`` はそのまま保持される。
    """
    _, parse_mcm, serialize_mcm = _import_mcm_io()
    entries, fmt, lines = parse_mcm(mcm_tiny_txt)

    # index 1 を翻訳済にする
    entries[1].new_dest = "はい"
    entries[1].state = "translated"

    out = serialize_mcm(entries, lines, fmt)
    decoded = out[2:].decode("utf-16-le")

    assert "$MCM_OPT_YES\tはい" in decoded, "new_dest が値に書かれる"
    # 他行の $KEY と値も保持
    assert "$MCM_TITLE\tHello {0} World" in decoded
    assert "$MCM_DESC\tToggle this option" in decoded


# ===========================================================================
# T-MCM-07: mcm_lf.txt（UTF-8 BOM 無し）の parse → encoding="utf-8", has_bom=False
# ===========================================================================

def test_T_MCM_07_utf8_no_bom(mcm_lf_txt: Path) -> None:
    """T-MCM-07: UTF-8 BOM 無し入力を寛容に受入（§3.7 import 便益）。"""
    _, parse_mcm, _ = _import_mcm_io()
    entries, fmt, _lines = parse_mcm(mcm_lf_txt)

    assert fmt.encoding == "utf-8"
    assert fmt.has_bom is False
    assert fmt.newline == "\n"
    assert fmt.has_trailing_newline is True
    assert len(entries) == 2
    assert entries[0].edid == "$MCM_LF_A"
    assert entries[0].source == "First"
    assert entries[1].edid == "$MCM_LF_B"
    assert entries[1].source == "Second {1}"


# ===========================================================================
# T-MCM-VALUE-TABS: 値に追加タブ → split("\t",1) で値内タブ保持
# ===========================================================================

def test_T_MCM_VALUE_TABS(mcm_tiny_txt: Path) -> None:
    """T-MCM-VALUE-TABS: ``$MCM_MULTI\\tkey\\twith\\ttabs`` の source が ``key\\twith\\ttabs``。

    ``split("\\t", 1)`` で最初のタブのみで分割し、値内の追加タブは保持される（§3.6）。
    """
    _, parse_mcm, _ = _import_mcm_io()
    entries, _fmt, _lines = parse_mcm(mcm_tiny_txt)

    multi = next(e for e in entries if e.edid == "$MCM_MULTI")
    assert multi.source == "key\twith\ttabs", (
        f"値内の追加タブは保持: {multi.source!r}"
    )


# ===========================================================================
# T-MCM-EMPTY-VAL: $MCM_EMPTY の source == ""
# ===========================================================================

def test_T_MCM_EMPTY_VAL(mcm_tiny_txt: Path) -> None:
    """T-MCM-EMPTY-VAL: ``$MCM_EMPTY\\t``（値空）の source が空文字・round-trip で保持。

    parse で ``source == ""`` になるだけでなく、serialize round-trip で
    ``$MCM_EMPTY\\t``（値空の行）が出力に残ることを検証する（§3.6）。値が空でも
    タブとキーが保存され、空行やキーだけの行に崩れない。
    """
    _, parse_mcm, serialize_mcm = _import_mcm_io()
    entries, fmt, lines = parse_mcm(mcm_tiny_txt)

    empty = next(e for e in entries if e.edid == "$MCM_EMPTY")
    assert empty.source == ""
    assert empty.original_dest == ""

    # serialize round-trip で $MCM_EMPTY\t（値空の行）が残る
    out = serialize_mcm(entries, lines, fmt)
    decoded = out[2:].decode("utf-16-le")
    # 行頭 $MCM_EMPTY + タブが存在（値が空でもキーとタブは保存）
    assert "$MCM_EMPTY\t" in decoded, (
        f"$MCM_EMPTY\\t（値空の行）が round-trip で残る: {decoded!r}"
    )
    # 値が空であることの確認: $MCM_EMPTY\t の直後に改行が来る（値文字列無し）
    # （CRLF 正規化済みのため \\r\\n で終わる行）
    assert "$MCM_EMPTY\t\r\n" in decoded, (
        f"$MCM_EMPTY 行は値空（タブ直後に CRLF）: {decoded!r}"
    )


# ===========================================================================
# T-MCM-TAB-ONLY: \t 単独行 → edid="" source=""
# ===========================================================================

def test_T_MCM_TAB_ONLY(mcm_tiny_txt: Path) -> None:
    """T-MCM-TAB-ONLY: ``\\t`` 単独行が ``edid=""`` ``source=""`` で round-trip する（§3.6）。

    ``line == "\\t"`` は ``split("\\t",1)`` → ``["",""]``。``edid=""`` ``source=""``。
    ``is_translation_needed("")`` が False → skip 対象だが、parse 時点では pending。
    serialize round-trip でも ``\\t`` 単独行が崩れずに残ることを検証する。
    """
    _, parse_mcm, serialize_mcm = _import_mcm_io()
    entries, fmt, lines = parse_mcm(mcm_tiny_txt)

    # ``\t`` 行エントリ（index 5）を特定: edid="" かつ source=""
    tab_only = [e for e in entries if e.edid == "" and e.source == ""]
    assert len(tab_only) == 1, f"``\\t`` 単独行エントリが1件: {len(tab_only)}"

    # serialize round-trip で \t 単独行が残る（CRLF 正規化済み）
    out = serialize_mcm(entries, lines, fmt)
    decoded = out[2:].decode("utf-16-le")
    # 行分割して \t 単独の物理行が存在することを確認
    # （$MCM_MULTI 行もタブを含むが「タブのみの行」ではないため弁別できる）
    physical_lines = decoded.split("\r\n")
    assert "\t" in physical_lines, (
        f"\\t 単独行が round-trip で残る（タブのみの物理行が存在）: {physical_lines!r}"
    )


# ===========================================================================
# T-MCM-ENC-LE: mcm_tiny.txt parse → encoding="utf-16-le", has_bom=True
# ===========================================================================

def test_T_MCM_ENC_LE(mcm_tiny_txt: Path) -> None:
    """T-MCM-ENC-LE: UTF-16 LE BOM ファイルの encoding と BOM 検出。

    さらに serialize bytes が ``ff fe``（UTF-16 LE BOM）で始まることを検証し、
    出力も入力エンコーディングを保存することを確認する（§3.7）。
    """
    _, parse_mcm, serialize_mcm = _import_mcm_io()
    entries, fmt, lines = parse_mcm(mcm_tiny_txt)

    assert fmt.encoding == "utf-16-le"
    assert fmt.has_bom is True

    # serialize bytes が ff fe (UTF-16 LE BOM) で始まる
    out = serialize_mcm(entries, lines, fmt)
    assert out[:2] == b"\xff\xfe", (
        f"serialize bytes は UTF-16 LE BOM (ff fe) で始まる: 実際 {out[:2]!r}"
    )


# ===========================================================================
# T-MCM-ENC-UTF8BOM: UTF-8 BOM (ef bb bf) 受入
# ===========================================================================

def test_T_MCM_ENC_UTF8BOM(tmp_path: Path) -> None:
    """T-MCM-ENC-UTF8BOM: UTF-8 BOM（``ef bb bf``）付きファイルを受入（§3.7）。

    encoding="utf-8", has_bom=True として検出される。serialize bytes も
    ``ef bb bf`` で始まる（入力エンコーディング保存）。
    """
    _, parse_mcm, serialize_mcm = _import_mcm_io()

    p = tmp_path / "utf8bom.txt"
    data = b"\xef\xbb\xbf$KEY\tvalue\n"
    p.write_bytes(data)

    entries, fmt, lines = parse_mcm(p)
    assert fmt.encoding == "utf-8"
    assert fmt.has_bom is True

    # serialize bytes が ef bb bf (UTF-8 BOM) で始まる
    out = serialize_mcm(entries, lines, fmt)
    assert out[:3] == b"\xef\xbb\xbf", (
        f"serialize bytes は UTF-8 BOM (ef bb bf) で始まる: 実際 {out[:3]!r}"
    )


# ===========================================================================
# T-MCM-ENC-BE: UTF-16 BE BOM (fe ff) 受入
# ===========================================================================

def test_T_MCM_ENC_BE(tmp_path: Path) -> None:
    """T-MCM-ENC-BE: UTF-16 BE BOM（``fe ff``）ファイルを受入（§3.7）。

    encoding="utf-16-be" として検出される。実データでは未確認だが念のため受入。
    serialize bytes も ``fe ff`` で始まる（入力エンコーディング保存）。
    """
    _, parse_mcm, serialize_mcm = _import_mcm_io()

    p = tmp_path / "utf16be.txt"
    text = "$KEY\tvalue\n"
    data = b"\xfe\xff" + text.encode("utf-16-be")
    p.write_bytes(data)

    entries, fmt, lines = parse_mcm(p)
    assert fmt.encoding == "utf-16-be"
    assert len(entries) == 1
    assert entries[0].source == "value"

    # serialize bytes が fe ff (UTF-16 BE BOM) で始まる
    out = serialize_mcm(entries, lines, fmt)
    assert out[:2] == b"\xfe\xff", (
        f"serialize bytes は UTF-16 BE BOM (fe ff) で始まる: 実際 {out[:2]!r}"
    )


# ===========================================================================
# T-MCM-TRAILING-OFF: mcm_tiny.txt parse → has_trailing_newline == False
# ===========================================================================

def test_T_MCM_TRAILING_OFF(mcm_tiny_txt: Path) -> None:
    """T-MCM-TRAILING-OFF: 末尾改行なし入力 → has_trailing_newline=False・出力も末尾改行無し。

    serialize した bytes が末尾改行（CRLF/LF いずれも）で **終わらない** ことを検証する。
    entries を変更せず round-trip するため、末尾改行無しの入力形質が保存される（§3.2）。
    """
    _, parse_mcm, serialize_mcm = _import_mcm_io()
    entries, fmt, lines = parse_mcm(mcm_tiny_txt)

    assert fmt.has_trailing_newline is False

    # entries を変更せず serialize → bytes が末尾改行無しで終わる
    out = serialize_mcm(entries, lines, fmt)
    assert not out.endswith(b"\r\n"), (
        f"末尾改行無し（CRLF で終わらない）: out[-2:]={out[-2:]!r}"
    )
    assert not out.endswith(b"\n"), (
        f"末尾バイトは改行でない（LF/CR いずれも不可）: out[-1:]={out[-1:]!r}"
    )
    assert out[-1:] not in (b"\n", b"\r"), (
        f"末尾バイトが改行文字でない: out[-1:]={out[-1:]!r}"
    )


# ===========================================================================
# T-MCM-TRAILING-ON: mcm_lf.txt parse → has_trailing_newline == True
# ===========================================================================

def test_T_MCM_TRAILING_ON(mcm_lf_txt: Path) -> None:
    """T-MCM-TRAILING-ON: 末尾改行あり入力 → has_trailing_newline=True・出力も末尾改行あり。

    mcm_lf.txt は LF 入力のため、serialize bytes は ``\\n`` で終わる（``\\r\\n`` でなく）。
    末尾改行の有無が round-trip で保存されることを検証する（§3.2）。
    """
    _, parse_mcm, serialize_mcm = _import_mcm_io()
    entries, fmt, lines = parse_mcm(mcm_lf_txt)

    assert fmt.has_trailing_newline is True

    # serialize bytes が末尾改行あり（\n）で終わる（LF 入力だから \r\n でなく \n）
    out = serialize_mcm(entries, lines, fmt)
    assert out.endswith(b"\n"), (
        f"末尾改行あり (\\n): out[-1:]={out[-1:]!r}"
    )
    assert not out.endswith(b"\r\n"), (
        f"LF 入力のため CRLF ではなく LF で終わる: out[-2:]={out[-2:]!r}"
    )


# ===========================================================================
# T-MCM-NEWDEST-NONE: new_dest=None のまま serialize → original_dest が書かれる
# ===========================================================================

def test_T_MCM_NEWDEST_NONE(mcm_tiny_txt: Path) -> None:
    """T-MCM-NEWDEST-NONE: ``new_dest=None`` を ``original_dest`` で出力（QA M1・§3.6）。

    ``_apply_existing`` の ``retry_failed=True`` ブランチ（``new_dest`` を触らない）経由で
    ``None`` が serialize に達するのを防御する。``new_dest is None`` なら ``original_dest``
    （= source = 英文）を書く。
    """
    _, parse_mcm, serialize_mcm = _import_mcm_io()
    entries, fmt, lines = parse_mcm(mcm_tiny_txt)

    # new_dest を触らず None のまま（retry_failed=True ブランチ相当）
    for e in entries:
        assert e.new_dest is None

    out = serialize_mcm(entries, lines, fmt)
    decoded = out[2:].decode("utf-16-le")

    # 全エントリの original_dest（= source）が値として書かれる
    assert "$MCM_TITLE\tHello {0} World" in decoded
    assert "$MCM_OPT_YES\tYes" in decoded


# ===========================================================================
# T-MCM-EMPTY-FILE: 0バイトファイル parse → entries == [], 例外無し
# ===========================================================================

def test_T_MCM_EMPTY_FILE(tmp_path: Path) -> None:
    """T-MCM-EMPTY-FILE: 0バイトファイルを例外なく空 entries で parse する。"""
    _, parse_mcm, _ = _import_mcm_io()

    p = tmp_path / "empty.txt"
    p.write_bytes(b"")

    entries, fmt, _lines = parse_mcm(p)
    assert entries == []
    # 空ファイルの fmt は実装依存だが、例外無しで返ることだけ保証


# ===========================================================================
# T-MCM-NO-ENTRIES: 空行とタブ無し行のみ → entries == []
# ===========================================================================

def test_T_MCM_NO_ENTRIES(tmp_path: Path) -> None:
    """T-MCM-NO-ENTRIES: 翻訳可能エントリ0件（空行・タブ無し非空行のみ）。

    タブを含む行が無いため entries は空。lines モデルはパススルー行として保持。
    """
    _, parse_mcm, serialize_mcm = _import_mcm_io()

    p = tmp_path / "no_entries.txt"
    # 空行 + コメント行のみ（タブ含む行なし）
    content = "\n# comment\n\n# another\n"
    p.write_text(content, encoding="utf-8")

    entries, fmt, lines = parse_mcm(p)
    assert entries == [], f"翻訳可能エントリ0件: {entries!r}"

    # serialize しても構造（コメント行・空行）が保持される
    out = serialize_mcm(entries, lines, fmt)
    decoded = out.decode("utf-8")
    assert "# comment" in decoded
    assert "# another" in decoded
