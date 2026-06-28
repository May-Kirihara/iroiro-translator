"""データモデル。

Plan §5.2 / §5.5.1 / §6.1 で規定される dataclass を定義する。

* ``StringEntry`` — XML 内の ``<Content>/<String>`` 1件に対応する作業単位。
* ``FileFormat`` — 入力 XML のバイトレベルフォーマット情報（BOM/改行/encoding/CDATA/comment）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(slots=True)
class StringEntry:
    """``<String>`` 1件の作業単位（Plan §5.2）。

    Attributes:
        index: XML 内出現順（0始まり）。安定した ID。progress.json の key と対応。
        edid: ``<EDID>`` の値（レコード識別子）。空文字列もありうる。
        rec: ``<REC>`` の値（例: ``MGEF:FULL``）。プロンプトヒント用。
        source: ``<Source>`` の生文字列（lxml が parse 時に XMLエスケープ解除済）。
        original_dest: ``<Dest>`` の元の生文字列。失敗/スキップ時に保持される。
        new_dest: 新しい訳文。未処理またはスキップ時は ``None``。
        state: 処理状態。
        skip_reason: スキップ理由（v0.2 追加・``state="skipped"`` の場合のみ設定）。
            ``"rec"`` / ``"language"`` / ``"max_chars"`` のいずれか。それ以外は ``None``。
    """

    index: int
    edid: str
    rec: str
    source: str
    original_dest: str
    new_dest: str | None
    state: Literal["pending", "translated", "skipped", "failed"]
    skip_reason: str | None = None


@dataclass(slots=True)
class FileFormat:
    """入力 XML のバイトレベルフォーマット情報（Plan §5.5.1 / §6.1）。

    Attributes:
        has_bom: 先頭3バイトが UTF-8 BOM (``EF BB BF``) か。
        newline: 改行コード（最初の改行バイト列で判定）。
        encoding: XML 宣言の ``encoding=`` 属性。無ければ ``UTF-8``。
        has_cdata: 生バイト列に ``<![CDATA[`` を含むか（v0.6）。
        has_comment: ``root.iter()`` に ``_Comment`` ノードを含むか（v0.6）。
    """

    has_bom: bool
    newline: Literal["\r\n", "\n", "\r"]
    encoding: str
    has_cdata: bool
    has_comment: bool
