"""XML I/O — BOM/CRLF/宣言保存戦略。

Plan §5.5 / §6.2 で規定される ``parse_xml`` / ``serialize_xml`` を実装する。

設計の要点:
    * **二重エスケープ防止**: アプリ側でエスケープ処理を入れない。lxml が parse 時に
      XMLエスケープを解除し、serialize 時に再エスケープする。
    * **フォーマット保存**: XML宣言/BOM/改行コード/空白テキストノード/属性 を
      バイトレベルで保持する。
    * **空要素展開**: ``<X/>`` を ``<X></X>`` に展開する。
      第一戦略は木構造アプローチ（``elem.text = ""``）。第二戦略は regex フォールバック。
    * **CDATA/comment 非サポート**: 検出した場合は ``IroiroError`` で停止する。
      xTranslator 形式では出現しないため（サンプル実査済み）。
"""

from __future__ import annotations

import re
from pathlib import Path

from lxml import etree

from iroiro.errors import IroiroError
from iroiro.models import FileFormat, StringEntry

# Plan §5.5.3 step 4: 自己閉じ空要素の展開（regex フォールバック）。
# タグ名は [A-Za-z][A-Za-z0-9_\-\.]*。コロン : は非サポート（名前空間無し）。
_SELF_CLOSING_RE: re.Pattern[bytes] = re.compile(
    rb"<([A-Za-z][A-Za-z0-9_\-\.]*)(\s[^<>]*?)?/>"
)

# XML 宣言の encoding= 属性を抽出する regex。
_ENCODING_RE: re.Pattern[bytes] = re.compile(
    rb"""<\?xml[^>]*?encoding=["']([^"']+)["']"""
)

# XML 宣言全体にマッチする regex（クォート正規化用）。
# lxml 6.x は encoding=str/bytes に関わらず ``standalone='yes'`` のように
# シングルクォートで出力するため、ダブルクォートに正規化する。
_XML_DECL_RE: re.Pattern[bytes] = re.compile(rb"<\?xml[^?]*\?>")


def _detect_format(raw: bytes) -> FileFormat:
    """バイト列から ``FileFormat`` を検出する。

    * BOM: 先頭3バイト ``EF BB BF``。
    * 改行: 最初の改行バイト列で判定（CRLF/LF/CR 単独）。
    * encoding: XML 宣言の ``encoding=`` 属性。無ければ UTF-8。
    * CDATA: ``b"<![CDATA["`` の生バイトスキャン。
    * has_comment は ``parse_xml`` 側で ``root.iter()`` から設定する。
    """
    has_bom = raw.startswith(b"\xef\xbb\xbf")

    newline: str
    crlf_pos = raw.find(b"\r\n")
    lf_pos = raw.find(b"\n")
    cr_pos = raw.find(b"\r")
    # 最初の改行種別を決定: CRLF > LF > CR の優先度で、出現位置が最も早いもの
    candidates: list[tuple[int, str]] = []
    if crlf_pos >= 0:
        candidates.append((crlf_pos, "\r\n"))
    if lf_pos >= 0:
        candidates.append((lf_pos, "\n"))
    if cr_pos >= 0:
        # CR 単独は CRLF の一部でない位置を探す
        # 簡易実装: CRLF 開始位置と一致しなければ CR 単独として扱う
        candidates.append((cr_pos, "\r"))
    if candidates:
        # 出現位置が最小のものを採用。同位置の場合は CRLF > LF > CR の順序で
        candidates.sort(key=lambda x: (x[0], {"\r\n": 0, "\n": 1, "\r": 2}[x[1]]))
        newline = candidates[0][1]
    else:
        newline = "\n"

    encoding = "UTF-8"
    m = _ENCODING_RE.search(raw)
    if m:
        try:
            encoding = m.group(1).decode("ascii")
        except UnicodeDecodeError:
            encoding = "UTF-8"

    has_cdata = b"<![CDATA[" in raw

    return FileFormat(
        has_bom=has_bom,
        newline=newline,  # type: ignore[arg-type]
        encoding=encoding,
        has_cdata=has_cdata,
        has_comment=False,  # parse_xml で更新
    )


def parse_xml(
    path: Path,
) -> tuple[list[StringEntry], FileFormat, etree._Element, dict[str, str]]:
    """XML ファイルを読み込み、エントリ・フォーマット・ルート・Params メタを返す。

    Plan §5.5.1 / §6.2 参照。

    Returns:
        ``(entries, fmt, root, params_meta)`` のタプル。
        * ``entries``: ``<Content>/<String>`` の出現順リスト。
        * ``fmt``: 検出済み ``FileFormat``。``has_comment`` も設定済み。
        * ``root``: ``etree.fromstring()`` の戻り値（``_Element``）。
          ``serialize_xml`` に渡して差し替え再利用する。
        * ``params_meta``: ``<Params>`` 配下の ``{tag: text}`` 辞書。
          README/handoff 用メタ情報。serialize には使用しない。
    """
    raw = path.read_bytes()
    fmt = _detect_format(raw)

    parser = etree.XMLParser(
        remove_blank_text=False,
        strip_cdata=False,
        load_dtd=False,           # DTD 読み込み拒否（XXE 対策）
        no_network=True,          # 外部ネットワークアクセス拒否
        resolve_entities=False,   # entity 展開無効化（billion laughs 対策）
    )
    root = etree.fromstring(raw, parser=parser)

    # Plan §5.5.2: コメント検出。root.iter() は _Comment ノードを含む（lxml 6.x 実機検証済み）。
    fmt.has_comment = any(isinstance(n, etree._Comment) for n in root.iter())

    # <Params> メタ情報の読み込み
    params_meta: dict[str, str] = {}
    params_elem = root.find(".//Params")
    if params_elem is not None:
        for child in params_elem:
            if isinstance(child.tag, str):
                params_meta[child.tag] = child.text or ""

    # <Content>/<String> の列挙と index 振り
    entries: list[StringEntry] = []
    strings = root.findall(".//String")
    for i, s in enumerate(strings):
        edid = s.findtext("EDID") or ""
        rec = s.findtext("REC") or ""
        source = s.findtext("Source")
        source = "" if source is None else source
        dest = s.findtext("Dest")
        dest = "" if dest is None else dest
        entries.append(
            StringEntry(
                index=i,
                edid=edid,
                rec=rec,
                source=source,
                original_dest=dest,
                new_dest=None,
                state="pending",
            )
        )

    return entries, fmt, root, params_meta


def serialize_xml(
    entries: list[StringEntry],
    root: etree._Element,
    fmt: FileFormat,
) -> bytes:
    """BOM/CRLF/宣言を保持したバイト列を返す。

    Plan §5.5.3 / §6.2 参照。

    Args:
        entries: ``parse_xml`` で取得したエントリ。``new_dest`` を反映する。
            ``new_dest is None`` の場合は ``original_dest`` を使う（Plan §5.9）。
        root: ``parse_xml`` で取得したルート要素。直接 ``<Dest>.text`` を差し替える。
        fmt: ``parse_xml`` で取得したフォーマット。

    Raises:
        IroiroError: ``fmt.has_cdata`` または ``fmt.has_comment`` の場合（v0.1 では非サポート）。
        IroiroError: ``entries`` と ``root`` 内の ``<String>`` 数が不一致の場合。
    """
    # ---- step 0: CDATA/comment 事前検証 ----
    if fmt.has_cdata or fmt.has_comment:
        parts: list[str] = []
        if fmt.has_cdata:
            parts.append("CDATA")
        if fmt.has_comment:
            parts.append("comments")
        raise IroiroError(
            f"Input XML contains {' and '.join(parts)}. "
            "v0.1 does not support these (regex post-process would corrupt them)."
        )

    # ---- step 1: <String>/<Dest>.text の差し替え ----
    strings = root.findall(".//String")
    if len(strings) != len(entries):
        raise IroiroError(
            f"entries/strings count mismatch: entries={len(entries)} strings={len(strings)}"
        )
    for entry, s in zip(entries, strings, strict=True):
        dest_elem = s.find("Dest")
        if dest_elem is None:
            continue
        # new_dest が無い場合は original_dest を保持（Plan §5.9 の失敗/スキップ保護）
        new_text = entry.new_dest if entry.new_dest is not None else entry.original_dest
        dest_elem.text = new_text

    # ---- step 2: 空要素の展開（木構造アプローチ、第一戦略） ----
    # lxml 6.x は elem.text = "" をセットすると <X></X> 形式で出力する（実機検証済み）。
    # root.iter() は _Comment ノードを含むため isinstance チェックで除外する。
    for elem in root.iter():
        if isinstance(elem, etree._Comment):
            continue
        if not isinstance(elem.tag, str):
            # コメント・処理命令等はスキップ
            continue
        if len(elem) == 0 and elem.text is None:
            elem.text = ""

    # ---- step 3: etree.tostring ----
    # encoding=str を渡すと standalone='yes'（シングルクォート）になるので、
    # bytes で渡してダブルクォートを保証する。
    encoding_bytes = fmt.encoding.encode("ascii", errors="replace")
    out = etree.tostring(
        root,
        xml_declaration=True,
        encoding=encoding_bytes,
        standalone=True,
    )

    # ---- step 3b: XML 宣言のクォートをダブルに正規化 ----
    # lxml 6.x は encoding=str/bytes に関わらず ``version='1.0' ... standalone='yes'``
    # のようにシングルクォートで出力する。xTranslator 互換のためダブルクォートに統一する。
    # 宣言は先頭1行のみ。宣言内にシングルクォートを含む値は無い（version/encoding/standalone）。
    out = _XML_DECL_RE.sub(
        lambda m: m.group(0).replace(b"'", b'"'), out, count=1
    )

    # ---- step 4: regex フォールバック（自己閉じ要素の展開） ----
    # step 0 で CDATA/comment を排除済みなので、regex は安全。
    out = _SELF_CLOSING_RE.sub(rb"<\1\2></\1>", out)

    # ---- step 5: 改行コード正規化（LF に統一 → 指定 newline に変換） ----
    out = out.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    if fmt.newline == "\r\n":
        out = out.replace(b"\n", b"\r\n")
    elif fmt.newline == "\r":
        out = out.replace(b"\n", b"\r")

    # ---- step 6: BOM 付与 ----
    if fmt.has_bom:
        out = b"\xef\xbb\xbf" + out

    return out
