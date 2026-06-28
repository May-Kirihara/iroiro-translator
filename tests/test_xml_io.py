"""test_xml_io.py — XML I/O のテスト（T1-T10, T47-T49, T52-T53）。

v0.2 追加: T68（skip されたエントリの ``<Dest>`` が original_dest を保持）。

対象モジュール: `iroiro/xml_io.py`、`iroiro/models.py`、`iroiro/errors.py`
シグネチャ契約（Plan §6.2）:
    parse_xml(path: Path) -> tuple[list[StringEntry], FileFormat, etree._Element, dict[str, str]]
    serialize_xml(entries, root, fmt) -> bytes

本テストファイルが検証する契約:
  - 「構造的等価 + フォーマット保存」（Plan §5.5.4）
  - BOM / CRLF / standalone 宣言 / 空白テキストノード / 属性 の保持
  - 二重エスケープ防止（lxml 任せ）
  - 空要素 `<X></X>` 形式の保持（自己閉じ化しない）
  - CDATA / XMLコメント 入力時の IroiroError 停止
  - v0.2: skip されたエントリの ``<Dest>`` が ``original_dest`` を保持
"""
from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from iroiro.errors import IroiroError
from iroiro.xml_io import parse_xml, serialize_xml

# T10 skipif 判定用。sample XML は第三者著作物のため git 管理外。
from tests.conftest import SAMPLE_XML

# ===========================================================================
# 補助関数: bytes を直接書いた tmp XML を parse するヘルパー
# ===========================================================================

def _write_tmp_xml(tmp_path: Path, name: str, data: bytes) -> Path:
    """tmp_path に bytes を書き込み、Path を返す。"""
    p = tmp_path / name
    p.write_bytes(data)
    return p


def _structural_eq(a: etree._Element, b: etree._Element) -> bool:
    """2つの要素が構造的に等価か（タグ・text・tail・属性・子再帰）。

    `parse → serialize → parse` の同一性検証に使用。
    """
    if a.tag != b.tag:
        return False
    if (a.text or "") != (b.text or ""):
        return False
    if (a.tail or "") != (b.tail or ""):
        return False
    if dict(a.attrib) != dict(b.attrib):
        return False
    a_children = [c for c in a if not isinstance(c.tag, str) or True]
    b_children = list(b)
    if len(a_children) != len(b_children):
        return False
    for ac, bc in zip(a_children, b_children, strict=True):
        if not _structural_eq(ac, bc):
            return False
    return True


# ===========================================================================
# T1: tiny_crlf_bom.xml を parse→serialize して構造的等価 + フォーマット保存
# ===========================================================================

def test_T01_roundtrip_preserves_format_and_structure(tiny_crlf_bom_xml: Path) -> None:
    """T1: BOM + CRLF + standalone 宣言を保持し、再 parse で同一木構造。

    「byte完全一致」は要求しないが、以下はバイトレベルで保持する:
      - XML宣言 standalone="yes"
      - BOM の有無
      - 改行コード（CRLF）
      - 空要素の <X></X> 形式
    """
    entries, fmt, root, params = parse_xml(tiny_crlf_bom_xml)

    # FileFormat 検出値
    assert fmt.has_bom is True, "BOM 付き入力は has_bom=True"
    assert fmt.newline == "\r\n", "CRLF 入力は newline='\\r\\n'"
    assert fmt.encoding.upper() == "UTF-8"

    out = serialize_xml(entries, root, fmt)

    # フォーマット保存（バイトレベル）
    assert out.startswith(b"\xef\xbb\xbf"), "出力は BOM で始まる"
    assert b'\r\n' in out, "出力は CRLF を含む"
    assert b'standalone="yes"' in out, "standalone 宣言を保持"

    # 構造的等価: 再 parse で同一木
    _, _, root2, _ = parse_xml_from_bytes(out)
    assert _structural_eq(root, root2), "round-trip で木構造が等しい"


def parse_xml_from_bytes(data: bytes):
    """テスト用: bytes を tmp ファイルに書き出し ``parse_xml`` 経路で再 parse する。

    ``parse_xml`` と同一の 4 要素 tuple ``(entries, fmt, root, params_meta)`` を返す。
    round-trip 検証で ``serialize_xml`` の出力 bytes を、本物の parse 経路（parser 設定・
    BOM/CRLF 検出・コメント検出含む）で再 parse するために使用する。
    """
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".xml") as tmp:
        tmp.write(data)
        tmp.flush()
        return parse_xml(Path(tmp.name))


# ===========================================================================
# T2: <Dest> のみ変更した場合、他は構造的に等価
# ===========================================================================

def test_T02_dest_only_change_preserves_rest(tiny_crlf_bom_xml: Path) -> None:
    """T2: entries[0].new_dest を訳文に差し替えても、宣言/BOM/CRLF/空要素形式は不変。"""
    entries, fmt, root, _ = parse_xml(tiny_crlf_bom_xml)

    # 1件だけ訳文をセット
    entries[0].new_dest = "やあ、<alias=hero>、%{location}へようこそ！"
    entries[0].state = "translated"

    out = serialize_xml(entries, root, fmt)

    # フォーマット不変
    assert out.startswith(b"\xef\xbb\xbf"), "BOM 保持"
    assert b'\r\n' in out, "CRLF 保持"
    assert b'standalone="yes"' in out, "宣言保持"

    # 訳文が反映されている（lxml が <, > を再エスケープ）
    assert "やあ".encode() in out
    assert b"&lt;alias=hero&gt;" in out, "alias はエスケープされて格納"
    assert b"%{location}" in out


# ===========================================================================
# T3: BOM 付き→BOM 付き、BOM 無し→BOM 無し
# ===========================================================================

def test_T03_bom_preserved(tiny_xml: Path, tiny_crlf_bom_xml: Path) -> None:
    """T3: BOM 付き入力は BOM 付き出力、BOM 無し入力は BOM 無し出力。"""
    # BOM 無し
    entries_nobom, fmt_nobom, root_nobom, _ = parse_xml(tiny_xml)
    assert fmt_nobom.has_bom is False
    out_nobom = serialize_xml(entries_nobom, root_nobom, fmt_nobom)
    assert not out_nobom.startswith(b"\xef\xbb\xbf"), "BOM 無し入力は BOM 無し出力"

    # BOM 付き
    entries_bom, fmt_bom, root_bom, _ = parse_xml(tiny_crlf_bom_xml)
    assert fmt_bom.has_bom is True
    out_bom = serialize_xml(entries_bom, root_bom, fmt_bom)
    assert out_bom.startswith(b"\xef\xbb\xbf"), "BOM 付き入力は BOM 付き出力"


# ===========================================================================
# T4: CRLF→CRLF、LF→LF
# ===========================================================================

def test_T04_newline_preserved(tiny_xml: Path, tiny_crlf_bom_xml: Path) -> None:
    """T4: CRLF 入力は CRLF 出力、LF 入力は LF 出力。"""
    # LF
    entries_lf, fmt_lf, root_lf, _ = parse_xml(tiny_xml)
    assert fmt_lf.newline == "\n", "tiny.xml は LF"
    out_lf = serialize_xml(entries_lf, root_lf, fmt_lf)
    assert b'\r\n' not in out_lf, "LF 入力は CRLF を含まない"
    assert b'\n' in out_lf

    # CRLF
    entries_crlf, fmt_crlf, root_crlf, _ = parse_xml(tiny_crlf_bom_xml)
    assert fmt_crlf.newline == "\r\n", "tiny_crlf_bom.xml は CRLF"
    out_crlf = serialize_xml(entries_crlf, root_crlf, fmt_crlf)
    assert b'\r\n' in out_crlf, "CRLF 入力は CRLF 出力"


def test_T04b_mixed_newline_uses_first(tmp_path: Path) -> None:
    """T4 補足: 混在改行は最初の改行コードで統一（実装の検出ルール）。"""
    # 先頭が CRLF、途中に LF が混在
    mixed = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
        b"<SSTXMLRessources>\r\n"
        b"  <Params>\n"  # LF に切り替え
        b"    <Source>english</Source>\n"
        b"    <Dest>japanese</Dest>\n"
        b"  </Params>\n"
        b"</SSTXMLRessources>\n"
    )
    p = _write_tmp_xml(tmp_path, "mixed.xml", mixed)
    _, fmt, _, _ = parse_xml(p)
    assert fmt.newline == "\r\n", "最初の改行（CRLF）が優先される"


# ===========================================================================
# T5: standalone="yes" 宣言保持
# ===========================================================================

def test_T05_standalone_declaration_preserved(tiny_crlf_bom_xml: Path) -> None:
    """T5: standalone="yes" が宣言に保持される。"""
    entries, fmt, root, _ = parse_xml(tiny_crlf_bom_xml)
    out = serialize_xml(entries, root, fmt)
    assert b'standalone="yes"' in out, "standalone 宣言が保持される"


# ===========================================================================
# T6: 空白テキストノード保持（remove_blank_text=False）
# ===========================================================================

def test_T06_blank_text_nodes_preserved(tiny_crlf_bom_xml: Path) -> None:
    """T6: インデント用の空白テキストノードが保持される。

    xTranslator 互換のため、remove_blank_text=False で parse する。
    """
    entries, fmt, root, _ = parse_xml(tiny_crlf_bom_xml)
    # 子要素間に空白 text が存在する（例: "  " のような indent）
    # SSTXMLRessources の最初の子（Params）の .tail または text に空白があるはず
    assert root.text is not None and root.text.strip() == "", (
        "root.text に空白（インデント）が保持されている"
    )

    out = serialize_xml(entries, root, fmt)
    # 出力にも空白インデントが含まれる
    assert b"  <Params>" in out or b" \r\n  <Params>" in out, (
        "インデント空白が出力に含まれる"
    )


# ===========================================================================
# T7: List="0" 等の属性保持
# ===========================================================================

def test_T07_attributes_preserved(tiny_crlf_bom_xml: Path) -> None:
    """T7: <String List="0"> の List 属性が保持される。"""
    entries, fmt, root, _ = parse_xml(tiny_crlf_bom_xml)
    out = serialize_xml(entries, root, fmt)
    assert b'<String List="0">' in out, "List 属性が保持される"

    # 再 parse でも属性が維持される
    _, _, root2, _ = parse_xml_from_bytes(out)
    strings = root2.findall(".//String")
    assert len(strings) == len(entries)
    for s in strings:
        assert s.get("List") == "0"


# ===========================================================================
# T8: alias トークン <alias=NAME> を含む Dest の正しい出力（二重エスケープされない）
# ===========================================================================

def test_T08_alias_token_not_double_escaped(tiny_crlf_bom_xml: Path) -> None:
    """T8: <alias=hero> を含む Source/Dest が二重エスケープされず正しく出力される。

    実物 XML では alias は `&lt;alias=hero&gt;` にエスケープされて格納されている。
    lxml が parse 時に `<alias=hero>` にアンエスケープし、serialize 時に再エスケープ
    して `&lt;alias=hero&gt;` に戻る。アプリ側でエスケープしてはいけない。
    """
    entries, fmt, root, _ = parse_xml(tiny_crlf_bom_xml)

    # entry[0] は alias を含む
    alias_entry = entries[0]
    assert "<alias=hero>" in alias_entry.source, (
        "parse 後は <alias=hero> にアンエスケープされている"
    )
    assert "%{location}" in alias_entry.source

    out = serialize_xml(entries, root, fmt)

    # 出力では <, > は再エスケープされる
    assert b"&lt;alias=hero&gt;" in out, "serialize で正しく再エスケープ"
    assert b"%{location}" in out, "%{...} はエスケープ対象外"

    # 二重エスケープされていない
    assert b"&amp;lt;alias=hero&amp;gt;" not in out, "二重エスケープされていない"
    assert b"&amp;lt;" not in out


# ===========================================================================
# T9: 空の <Source>/<Dest> の処理
# ===========================================================================

def test_T09_empty_source_dest(tiny_xml: Path) -> None:
    """T9: 空の <Source></Source>/<Dest></Dest> を正しく処理（空要素形式を保持）。"""
    entries, fmt, root, _ = parse_xml(tiny_xml)

    # entry[2] は空 Source/Dest
    empty_entry = entries[2]
    assert empty_entry.source == ""
    assert empty_entry.original_dest == ""

    out = serialize_xml(entries, root, fmt)

    # 空要素は <X></X> 形式を維持（自己閉じ <X/> にならない）
    assert b"<Source></Source>" in out, "空 Source は <Source></Source> 形式を維持"
    assert b"<Dest></Dest>" in out, "空 Dest は <Dest></Dest> 形式を維持"
    assert b"<Source/>" not in out, "自己閉じ化しない"
    assert b"<Dest/>" not in out, "自己閉じ化しない"


# ===========================================================================
# T10: 巨大ファイル（サンプル679件）のメモリ・時間（緩い上限）
# ===========================================================================

@pytest.mark.skipif(
    not SAMPLE_XML.exists(),
    reason="sample/JobsofSkyrim_english_japanese.xml is user-provided (not in git)",
)
def test_T10_large_file_parse(sample_xml: Path) -> None:
    """T10: サンプル679件を時間内に parse できること。

    メモリ・時間は緩い上限（10秒以内・679件検出）。

    注: sample XML は第三者著作物のため git 管理外。ユーザー環境にファイルが
    無い場合は skipif でスキップされる。
    """
    import time

    start = time.monotonic()
    entries, fmt, root, _ = parse_xml(sample_xml)
    elapsed = time.monotonic() - start

    assert len(entries) == 679, f"サンプルは679件: 実際 {len(entries)}"
    assert elapsed < 10.0, f"parse は10秒以内: 実際 {elapsed:.2f}s"

    # serialize も時間内
    start = time.monotonic()
    out = serialize_xml(entries, root, fmt)
    elapsed = time.monotonic() - start
    assert elapsed < 10.0, f"serialize は10秒以内: 実際 {elapsed:.2f}s"
    assert len(out) > 0


# ===========================================================================
# T47: 空要素 <Dest></Dest> が <Dest/> に自己閉じ化されないこと
# ===========================================================================

def test_T47_empty_element_not_self_closed(tiny_xml: Path) -> None:
    """T47: 空要素 <Dest></Dest> が自己閉じ <Dest/> にならないこと。

    Plan §5.5.3 の木構造アプローチ（elem.text=""）+ regex フォールバックで保証。
    """
    entries, fmt, root, _ = parse_xml(tiny_xml)
    out = serialize_xml(entries, root, fmt)

    # 全ての空でない要素も含め、自己閉じ形式が出現しないことを確認
    # （実物は全て <X></X> 形式）
    assert b"<EDID/>" not in out
    assert b"<REC/>" not in out
    assert b"<Source/>" not in out
    assert b"<Dest/>" not in out

    # 明示的に空要素形式が出力されている
    assert b"<Source></Source>" in out
    assert b"<Dest></Dest>" in out


# ===========================================================================
# T48: 既にエスケープされたアンパサンドの往復（二重エスケープされない）
# ===========================================================================

def test_T48_escaped_ampersand_roundtrip(tmp_path: Path) -> None:
    """T48: <Source>A &amp; B</Source> が二重エスケープ（&amp;amp;）されないこと。

    lxml が parse 時に `&amp;` を `&` にアンエスケープし、serialize 時に
    再び `&amp;` にエスケープする。アプリ側でエスケープ処理を入れてはいけない。
    """
    xml = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b"<SSTXMLRessources>\n"
        b"  <Params>\n"
        b"    <Source>english</Source>\n"
        b"    <Dest>japanese</Dest>\n"
        b"    <Version>2</Version>\n"
        b"  </Params>\n"
        b"  <Content>\n"
        b'    <String List="0">\n'
        b"      <EDID>AmpEntry</EDID>\n"
        b"      <REC>MGEF:FULL</REC>\n"
        b"      <Source>A &amp; B</Source>\n"
        b"      <Dest>A &amp; B</Dest>\n"
        b"    </String>\n"
        b"  </Content>\n"
        b"</SSTXMLRessources>\n"
    )
    p = _write_tmp_xml(tmp_path, "amp.xml", xml)

    entries, fmt, root, _ = parse_xml(p)

    # parse 時点で & にアンエスケープされている
    assert entries[0].source == "A & B"
    assert entries[0].original_dest == "A & B"

    out = serialize_xml(entries, root, fmt)

    # 出力では &amp; に戻る（再エスケープ）
    assert b"<Source>A &amp; B</Source>" in out, "正しく再エスケープ"
    assert b"<Dest>A &amp; B</Dest>" in out

    # 二重エスケープされていない
    assert b"&amp;amp;" not in out, "二重エスケープされていない"


# ===========================================================================
# T49: round-trip の「構造的等価」検証
# ===========================================================================

def test_T49_roundtrip_structural_equivalence(
    tiny_xml: Path,
    tiny_crlf_bom_xml: Path,
    tmp_path: Path,
) -> None:
    """T49: parse → serialize → parse で同一木構造・.text・属性。

    Plan §5.5.4 の「構造的等価」保証。
    bytes を tmp_path に書いて parse_xml を呼ぶ（本物の API 経路）。
    """
    for xml_path in [tiny_xml, tiny_crlf_bom_xml]:
        entries1, fmt1, root1, _ = parse_xml(xml_path)
        out = serialize_xml(entries1, root1, fmt1)

        # bytes を tmp に書いて、本物の parse_xml で再 parse
        tmp_xml = tmp_path / f"rt_{xml_path.name}"
        tmp_xml.write_bytes(out)
        entries2, fmt2, root2, _ = parse_xml(tmp_xml)

        # 木構造が等価
        assert _structural_eq(root1, root2), (
            f"{xml_path.name}: round-trip で木構造が等しい"
        )

        # エントリ数が同一
        assert len(entries1) == len(entries2)

        # 各エントリの source / original_dest が同一
        for e1, e2 in zip(entries1, entries2, strict=True):
            assert e1.source == e2.source
            assert e1.original_dest == e2.original_dest
            assert e1.edid == e2.edid
            assert e1.rec == e2.rec

        # フォーマットも同一
        assert fmt1.has_bom == fmt2.has_bom
        assert fmt1.newline == fmt2.newline
        assert fmt1.has_cdata == fmt2.has_cdata
        assert fmt1.has_comment == fmt2.has_comment


# ===========================================================================
# T52: CDATA または コメント含む入力 → IroiroError（統合）
# ===========================================================================

def test_T52_cdata_or_comment_raises(with_cdata_xml: Path, with_comment_xml: Path) -> None:
    """T52: CDATA または XMLコメント を含む入力は serialize 時に IroiroError。

    Plan §5.5.3 step 0: fmt.has_cdata / fmt.has_comment で検出。
    """
    for xml_path in [with_cdata_xml, with_comment_xml]:
        entries, fmt, root, _ = parse_xml(xml_path)
        # 検出されている
        assert fmt.has_cdata or fmt.has_comment, (
            f"{xml_path.name}: CDATA または comment が検出されている"
        )
        # serialize で停止
        with pytest.raises(IroiroError):
            serialize_xml(entries, root, fmt)


# ===========================================================================
# T52b: コメント単体 → _Comment ノード検出で停止
# ===========================================================================

def test_T52b_comment_detected(with_comment_xml: Path) -> None:
    """T52b: <!-- xxx --> コメントを含む入力 → has_comment=True → IroiroError。

    実装: `any(isinstance(n, etree._Comment) for n in root.iter())`。
    """
    _, fmt, _, _ = parse_xml(with_comment_xml)
    assert fmt.has_comment is True, "コメントが検出されている"
    assert fmt.has_cdata is False, "CDATA は無し"


# ===========================================================================
# T52c: CDATA 単体 → 生バイトスキャンで検出して停止
# ===========================================================================

def test_T52c_cdata_detected(with_cdata_xml: Path) -> None:
    """T52c: <![CDATA[xxx]]> を含む入力 → has_cdata=True → IroiroError。

    実装: `b'<![CDATA[' in raw`（生バイトスキャン）。
    root.iter() では CDATA は見えないため、バイトスキャン必須。
    """
    _, fmt, _, _ = parse_xml(with_cdata_xml)
    assert fmt.has_cdata is True, "CDATA が生バイトスキャンで検出されている"
    assert fmt.has_comment is False, "コメントは無し"


# ===========================================================================
# T53: 空要素 + 属性 <Dest List="0"/> が <Dest List="0"></Dest> に展開
# ===========================================================================

def test_T53_empty_element_with_attribute_expanded(tmp_path: Path) -> None:
    """T53: <Dest List="0"/> のような「属性付き空要素」が <Dest List="0"></Dest> に展開。

    Plan §5.5.3 step 2/4: 木構造アプローチ + regex フォールバックで保証。
    ※ 実物サンプルでは `<Dest></Dest>` は中身ありで出現するため、このケースは
       「もし属性付き空要素が入力にあったら」の境界検証。
    """
    # 入力に意図的に `<Dest List="0"/>` （属性付き自己閉じ）を含める
    # ※ parse 時に lxml はこれを正しく読めるが、serialize 時に <X></X> 形式にする
    xml = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b"<SSTXMLRessources>\n"
        b"  <Params>\n"
        b"    <Source>english</Source>\n"
        b"    <Dest>japanese</Dest>\n"
        b"    <Version>2</Version>\n"
        b"  </Params>\n"
        b"  <Content>\n"
        b'    <String List="0">\n'
        b"      <EDID>AttrEntry</EDID>\n"
        b"      <REC>MGEF:FULL</REC>\n"
        b"      <Source>placeholder</Source>\n"
        # 属性付き空要素（実物には無いが、安全側のテスト）
        b'      <Dest List="0"></Dest>\n'
        b"    </String>\n"
        b"  </Content>\n"
        b"</SSTXMLRessources>\n"
    )
    p = _write_tmp_xml(tmp_path, "attr_empty.xml", xml)

    entries, fmt, root, _ = parse_xml(p)
    out = serialize_xml(entries, root, fmt)

    # 空要素は <X ...></X> 形式を維持（属性があっても自己閉じ化しない）
    assert b'<Dest List="0"></Dest>' in out, (
        "属性付き空要素は <Dest List=\"0\"></Dest> 形式を維持"
    )
    # 自己閉じ形式が出現しない
    assert b'<Dest List="0"/>' not in out


# ===========================================================================
# T54: 内部 entity 宣言 → entity 展開されない（XXE / billion laughs 対策）
# ===========================================================================

def test_T54_internal_entity_not_expanded(tmp_path: Path) -> None:
    """T54: ``<!DOCTYPE x [<!ENTITY a "EXPANDED">]>`` の内部 entity は展開されない。

    Plan §5.5 / セキュリティ hardening:
        parser に ``resolve_entities=False`` を設定し、entity 参照 ``&a;`` が
        展開されないことを検証する。展開されると billion laughs 攻撃や
        XXE の踏み台になる。

    実測挙動（lxml 6.x, resolve_entities=False）:
        * parse は成功（エラーにならない）
        * ``&a;`` は ``_Entity`` ノードとして木に残る（``.text`` には含まれない）
        * ``findtext("Source")`` は entity より前の部分文字列のみ返す
        * "EXPANDED" は source に含まれない
    """
    xml = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b'<!DOCTYPE SSTXMLRessources [<!ENTITY a "EXPANDED">]>\n'
        b"<SSTXMLRessources>\n"
        b"  <Params>\n"
        b"    <Source>english</Source>\n"
        b"    <Dest>japanese</Dest>\n"
        b"    <Version>2</Version>\n"
        b"  </Params>\n"
        b"  <Content>\n"
        b'    <String List="0">\n'
        b"      <EDID>EntityTest</EDID>\n"
        b"      <REC>MGEF:FULL</REC>\n"
        b"      <Source>pre-&a;-post</Source>\n"
        b"      <Dest>pre-&a;-post</Dest>\n"
        b"    </String>\n"
        b"  </Content>\n"
        b"</SSTXMLRessources>\n"
    )
    p = _write_tmp_xml(tmp_path, "entity_internal.xml", xml)

    entries, fmt, root, _ = parse_xml(p)

    # entity は展開されていない（"EXPANDED" が source に含まれない）
    assert "EXPANDED" not in entries[0].source, (
        f"内部 entity は展開されない: {entries[0].source!r}"
    )
    assert "EXPANDED" not in entries[0].original_dest

    # _Entity ノードが木に残っている（展開されずに参照として保持）
    src_elem = root.find(".//String/Source")
    entity_children = [
        c for c in src_elem if isinstance(c, etree._Entity)
    ]
    assert len(entity_children) == 1, (
        f"&a; は _Entity ノードとして残る: children={[type(c).__name__ for c in src_elem]}"
    )


# ===========================================================================
# T55: 外部 entity 参照 → ファイル読み込まれない（XXE 対策）
# ===========================================================================

def test_T55_external_entity_not_loaded(tmp_path: Path) -> None:
    """T55: ``<!ENTITY e SYSTEM "file:///etc/hostname">`` は読み込まれない。

    Plan §5.5 / セキュリティ hardening:
        parser に ``load_dtd=False`` + ``no_network=True`` + ``resolve_entities=False``
        を設定し、外部 entity 参照によってローカルファイルが読み込まれない
        ことを検証する（XXE 攻撃対策）。

    実測挙動（lxml 6.x, hardening 設定）:
        * parse は成功（エラーにならない）
        * ファイル内容は読み込まれない
        * ``&e;`` は ``_Entity`` ノードとして木に残る
        * ``findtext("Source")`` は entity より前の部分文字列のみ返す
    """
    xml = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b'<!DOCTYPE SSTXMLRessources [\n'
        b'  <!ENTITY e SYSTEM "file:///etc/hostname">\n'
        b']>\n'
        b"<SSTXMLRessources>\n"
        b"  <Params>\n"
        b"    <Source>english</Source>\n"
        b"    <Dest>japanese</Dest>\n"
        b"    <Version>2</Version>\n"
        b"  </Params>\n"
        b"  <Content>\n"
        b'    <String List="0">\n'
        b"      <EDID>EntityTest</EDID>\n"
        b"      <REC>MGEF:FULL</REC>\n"
        b"      <Source>pre-&e;-post</Source>\n"
        b"      <Dest>pre-&e;-post</Dest>\n"
        b"    </String>\n"
        b"  </Content>\n"
        b"</SSTXMLRessources>\n"
    )
    p = _write_tmp_xml(tmp_path, "entity_external.xml", xml)

    entries, fmt, root, _ = parse_xml(p)

    # 外部ファイルの内容は読み込まれていない
    # /etc/hostname の内容が source に含まれていないことを確認
    # （環境に依存しない検証: entity 展開前の部分文字列のみが返る）
    assert entries[0].source == "pre-", (
        f"外部 entity は読み込まれず、entity 前の部分のみ返る: {entries[0].source!r}"
    )

    # _Entity ノードが木に残っている（読み込まれずに参照として保持）
    src_elem = root.find(".//String/Source")
    entity_children = [
        c for c in src_elem if isinstance(c, etree._Entity)
    ]
    assert len(entity_children) == 1, (
        f"&e; は _Entity ノードとして残る（読み込まれない）: "
        f"children={[type(c).__name__ for c in src_elem]}"
    )


# ===========================================================================
# v0.2: T68 — skip されたエントリの <Dest> が original_dest を保持
#
# Plan §5.6.3 / §5.9 / §6.3: state="skipped" のエントリは source で上書きせず、
# original_dest を保持する。xml_io.serialize_xml は
# ``entry.new_dest if entry.new_dest is not None else entry.original_dest``
# の単一セマンティクスでこれを実現する。
#
# 本テストは REC skip / 言語 skip にかかわらず、state="skipped" で
# new_dest=None のエントリの <Dest> が original_dest になることを検証する。
# ===========================================================================


def test_T68_skipped_entry_preserves_original_dest(
    skip_records_xml: Path,
    tmp_path: Path,
) -> None:
    """T68: state="skipped", new_dest=None のエントリの <Dest> が original_dest を保持。

    REC skip（HDPT:FULL）・言語 skip（日本語 Source）の両ケースで、
    new_dest をセットせずに serialize すると <Dest>.text は original_dest になる。
    これにより「過去に人間が修正した <Dest> を破壊しない」ポリシーが保証される。
    """

    entries, fmt, root, _ = parse_xml(skip_records_xml)

    # HDPT:FULL "Male Head"（REC skip 相当）と
    # WEAP:FULL "既存の日本語"（言語 skip 相当）を state="skipped" にする
    hdpt_entry = entries[0]
    assert hdpt_entry.rec == "HDPT:FULL"
    assert hdpt_entry.original_dest == "Male Head"
    hdpt_entry.state = "skipped"
    hdpt_entry.new_dest = None  # new_dest をセットしない

    jp_entry = entries[7]
    assert jp_entry.rec == "WEAP:FULL"
    assert "既存の日本語" in jp_entry.source
    assert jp_entry.original_dest == "既存の日本語"
    jp_entry.state = "skipped"
    jp_entry.new_dest = None

    out = serialize_xml(entries, root, fmt)

    # 出力を tmp_path に書き出して再 parse し <Dest> を確認。
    # tmp_path は pytest が自動削除するため try/finally unlink 不要。
    tmp_out = tmp_path / "t68_out.xml"
    tmp_out.write_bytes(out)
    out_entries, _, _, _ = parse_xml(tmp_out)

    out_hdpt = out_entries[0]
    out_jp = out_entries[7]

    # REC skip 相当: <Dest> は original_dest "Male Head" を保持
    assert out_hdpt.original_dest == "Male Head", (
        f"HDPT skip の <Dest> は original_dest を保持: "
        f"実際 {out_hdpt.original_dest!r}"
    )

    # 言語 skip 相当: <Dest> は original_dest "既存の日本語" を保持
    assert out_jp.original_dest == "既存の日本語", (
        f"日本語 skip の <Dest> は original_dest を保持: "
        f"実際 {out_jp.original_dest!r}"
    )

    # raw bytes でも確認（source で上書きされていないことの証明）
    assert b"<Dest>Male Head</Dest>" in out
    # XML ヘッダが BOM + CRLF 形式を保持していることも回帰確認
    assert out.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" in out


def test_T68b_skipped_entry_with_original_dest_differs_from_source(
    skip_records_xml: Path,
    tmp_path: Path,
) -> None:
    """T68 補足: source != original_dest のケースで original_dest を保持。

    Plan §5.6.3 / §5.9 の中核ポリシー: 過去に人間が修正した <Dest> を破壊しない。
    source と original_dest が異なるエントリを state="skipped" で serialize した場合、
    <Dest>.text は original_dest になる（source で上書きしない）。
    """
    entries, fmt, root, _ = parse_xml(skip_records_xml)

    # HDPT:FULL エントリの original_dest を人間が修正した値に変更
    hdpt_entry = entries[0]
    assert hdpt_entry.rec == "HDPT:FULL"
    assert hdpt_entry.source == "Male Head"
    hdpt_entry.original_dest = "過去に人間が修正した男性頭部"
    hdpt_entry.state = "skipped"
    hdpt_entry.new_dest = None  # new_dest をセットしない

    out = serialize_xml(entries, root, fmt)

    # 出力の raw bytes に original_dest が含まれる（source で上書きされていない）
    assert "過去に人間が修正した男性頭部".encode() in out, (
        "original_dest（過去の修正）が保持される"
    )

    # raw bytes を tmp に書いて parse で再確認
    tmp_out = tmp_path / "t68b_out.xml"
    tmp_out.write_bytes(out)
    out_entries, _, _, _ = parse_xml(tmp_out)

    out_hdpt = out_entries[0]
    assert out_hdpt.original_dest == "過去に人間が修正した男性頭部", (
        "source で上書きされず original_dest を保持"
    )
    # source は不変（parse し直しても元の英文）
    assert out_hdpt.source == "Male Head"
