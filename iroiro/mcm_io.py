"""Skyrim MCM 翻訳 TXT 形式の I/O（Plan 007 §3.2 / §3.6 / §3.7）。

MCM TXT は SkyUI MCM 翻訳ファイル形式で、1行1エントリ・タブ区切りの
``$KEY\\tEnglish text`` 構造を持つ。Skyrim が UTF-16 を要求するため、
正規形式は UTF-16 LE + BOM。

本モジュールは XML パイプライン（``xml_io.py``）とは I/O のみが異なり、
エントリモデル（``StringEntry``）と翻訳エンジン（``Translator``）は共有する。

保証契約（Plan 007 §3.2「フォーマット保存 + 改行正規化」）:
    * エンコーディング・BOM: 入力と同一を保存（UTF-16 LE → UTF-16 LE 出力）。
    * 改行: 入力の **支配的改行**（CRLF 件数 >= LF-only 件数 なら CRLF）へ正規化。
      行ごとの改行保存は行わない（``xml_io.py`` と対称・実用価値無し）。
    * 末尾改行: 入力の有無を保存。
    * ``$KEY`` はそのまま・値側を訳文で置換。
    * 空行・タブ無し非空行（コメント等）は passthrough（未翻訳・そのまま保持）。

行モデル（``_McmLine``）は ``parse_mcm`` → ``serialize_mcm`` 間で物理順序を復元するための
内部構造。テストからは opaque（Plan 007 §3.6）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from iroiro.models import StringEntry


@dataclass(slots=True)
class McmFormat:
    """MCM TXT のバイトレベルフォーマット情報（Plan 007 §3.2 / §3.7）。

    Attributes:
        has_bom: 先頭バイトが BOM（UTF-16 LE ``ff fe`` / UTF-16 BE ``fe ff`` /
            UTF-8 ``ef bb bf``）か。
        newline: 支配的改行。CRLF 件数 >= LF-only 件数 なら ``\\r\\n``、else ``\\n``。
            CR-only は支配的改行判定の tie（crlf=0, lf=0）で CRLF 扱いとなり
            CRLF へ正規化される（実データでは観測されない・明示的非サポート・§3.9）。
        encoding: エンコーディング。``utf-16-le`` / ``utf-16-be`` / ``utf-8``。
        has_trailing_newline: デコード後テキストが（支配的改行で）終わるか。
    """

    has_bom: bool
    newline: Literal["\r\n", "\n"]
    encoding: Literal["utf-16-le", "utf-16-be", "utf-8"]
    has_trailing_newline: bool


# 行モデルの1要素。passthrough 行（``raw``）かエントリ参照（``entry``）。
# ``entry`` の値は ``StringEntry.index``（翻訳可能エントリ通し番号・物理行番号ではない）。
_McmLine = tuple[Literal["raw", "entry"], str | int]


def parse_mcm(
    path: Path,
) -> tuple[list[StringEntry], McmFormat, list[_McmLine]]:
    """MCM TXT を parse して entries / fmt / lines を返す（Plan 007 §3.6 / §3.7）。

    Args:
        path: 入力 MCM TXT のパス。

    Returns:
        ``(entries, fmt, lines)``。
        * ``entries``: 翻訳可能エントリ（タブを含む行）の ``StringEntry`` リスト。
          ``index`` は翻訳可能エントリの通し番号（0,1,2,...）。``rec=""``。
          ``original_dest = source``（skip/fail 時の英文保持・§3.2.1）。
        * ``fmt``: ``McmFormat``。
        * ``lines``: 行モデル（物理順序）。passthrough 行とエントリ参照のリスト。
          ``serialize_mcm`` が物理順序を復元するために使う。テストからは opaque。

    エンコーディング判定（§3.7）:
        先頭バイト ``ff fe`` → UTF-16 LE（BOM あり）・``fe ff`` → UTF-16 BE・
        ``ef bb bf`` → UTF-8 BOM・それ以外 → UTF-8（BOM 無し）。

    行分類（§3.6）:
        * タブ ``\\t`` を含む行 → translatable entry: ``split("\\t", 1)`` で
          ``edid=key`` / ``source=value``。``$`` prefix は要求しない。
        * 空行（``strip() == ""``）・非空タブ無し行 → passthrough。
    """
    data = path.read_bytes()

    # ---- 1. エンコーディング・BOM 判定（§3.7） ----
    if data[:2] == b"\xff\xfe":
        encoding: Literal["utf-16-le", "utf-16-be", "utf-8"] = "utf-16-le"
        has_bom = True
        # UTF-16 として decode すると BOM は除去される
        text = data.decode("utf-16")
    elif data[:2] == b"\xfe\xff":
        encoding = "utf-16-be"
        has_bom = True
        text = data.decode("utf-16")
    elif data[:3] == b"\xef\xbb\xbf":
        encoding = "utf-8"
        has_bom = True
        text = data[3:].decode("utf-8")
    else:
        encoding = "utf-8"
        has_bom = False
        text = data.decode("utf-8")

    # ---- 2. 支配的改行判定（元テキストで集計） ----
    # CRLF 件数 >= LF-only 件数 なら CRLF（§3.2）。CR-only は tie（crlf=0, lf=0）で CRLF 扱いとなり CRLF へ正規化される（§3.9）。
    crlf_count = text.count("\r\n")
    lf_only_count = text.count("\n") - crlf_count
    newline: Literal["\r\n", "\n"] = (
        "\r\n" if crlf_count >= lf_only_count else "\n"
    )

    # ---- 3. 支配的改行への正規化（§3.2「フォーマット保存 + 改行正規化」） ----
    # \r\n → \n を先に行い（CRLF の二重変換防止）、続いて \r → \n（CR-only → LF・§3.9）、
    # 最後に支配的改行が CRLF なら \n → \r\n。
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if newline == "\r\n":
        normalized = normalized.replace("\n", "\r\n")

    # ---- 4. 末尾改行判定（正規化後テキストで） ----
    has_trailing_newline = normalized.endswith(newline) if normalized else False

    # ---- 5. 行モデル構築 ----
    # 支配的改行で split。末尾改行ありなら末尾の空要素は改行のアーティファクト
    # （実行ではない）のため除外する。
    if normalized == "":
        parts: list[str] = []
    else:
        parts = normalized.split(newline)
        if has_trailing_newline:
            # split は末尾に空文字を生む（trailing newline の名残）→ 実行ではないので除去
            parts = parts[:-1]

    lines: list[_McmLine] = []
    entries: list[StringEntry] = []
    idx = 0
    for part in parts:
        if "\t" in part:
            # タブ含む行 → translatable entry。最初のタブのみで分割し、
            # 値内の追加タブは保持する（§3.6）。
            key, value = part.split("\t", 1)
            entries.append(
                StringEntry(
                    index=idx,
                    edid=key,
                    rec="",
                    source=value,
                    # §3.2.1: skip/fail 時の英文保持。original_dest = source（英文値）。
                    original_dest=value,
                    new_dest=None,
                    state="pending",
                )
            )
            lines.append(("entry", idx))
            idx += 1
        else:
            # 空行・タブ無し非空行 → passthrough
            lines.append(("raw", part))

    fmt = McmFormat(
        has_bom=has_bom,
        newline=newline,
        encoding=encoding,
        has_trailing_newline=has_trailing_newline,
    )
    return entries, fmt, lines


def serialize_mcm(
    entries: list[StringEntry],
    lines: list[_McmLine],
    fmt: McmFormat,
) -> bytes:
    """entries と行モデルから MCM TXT バイト列を構築する（Plan 007 §3.2 / §3.6）。

    Args:
        entries: ``parse_mcm`` が返した entries（``_translate_all`` 等で ``new_dest``
            が更新されている可能性がある）。
        lines: ``parse_mcm`` が返した行モデル（物理順序）。
        fmt: ``parse_mcm`` が返した ``McmFormat``。

    Returns:
        出力バイト列。``fmt.encoding`` で encode され、``fmt.has_bom`` に応じて
        BOM が付与される。``fmt.newline`` で行が結合され、``fmt.has_trailing_newline``
        に応じて末尾改行が付与される。

    ``new_dest`` の fallback（§3.6・QA M1）:
        ``entry.new_dest is not None`` なら ``new_dest`` を、``None`` なら
        ``original_dest``（= source = 英文）を値に書く。これは ``_apply_existing`` の
        ``retry_failed=True`` ブランチ（``new_dest`` を触らない）経由で ``None`` が
        serialize に達するのを防御する。
    """
    entry_by_idx = {e.index: e for e in entries}
    text_lines: list[str] = []
    for kind, val in lines:
        if kind == "raw":
            # passthrough 行（空行・タブ無し非空行）はそのまま
            text_lines.append(str(val))
        else:  # "entry"
            entry = entry_by_idx[int(val)]
            dest = (
                entry.new_dest
                if entry.new_dest is not None
                else entry.original_dest
            )
            text_lines.append(f"{entry.edid}\t{dest}")

    text = fmt.newline.join(text_lines)
    if fmt.has_trailing_newline:
        text += fmt.newline

    # ---- encode（入力エンコーディングを保存・§3.7） ----
    if fmt.encoding == "utf-16-le":
        body = text.encode("utf-16-le")
        return (b"\xff\xfe" if fmt.has_bom else b"") + body
    if fmt.encoding == "utf-16-be":
        body = text.encode("utf-16-be")
        return (b"\xfe\xff" if fmt.has_bom else b"") + body
    # utf-8
    body = text.encode("utf-8")
    return (b"\xef\xbb\xbf" if fmt.has_bom else b"") + body
