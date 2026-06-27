"""``rich`` ベースの進捗表示ヘルパ（Plan §5.3 / §4.1）。

ログとコンソール出力を一箇所に集約し、CLI から簡単に使えるようにする。
verbose フラグで詳細度を切り替える。
"""

from __future__ import annotations

import logging

from rich.console import Console
from rich.logging import RichHandler

_console = Console()
_verbose = False


def get_console() -> Console:
    """共有 ``rich.Console`` を返す。"""
    return _console


def configure_logging(verbose: bool) -> None:
    """``rich.RichHandler`` で logging を設定する。

    Args:
        verbose: ``True`` の場合は ``DEBUG``、``False`` の場合は ``INFO``。
    """
    global _verbose
    _verbose = verbose
    level = logging.DEBUG if verbose else logging.INFO
    handler = RichHandler(
        console=_console,
        show_time=False,
        show_path=False,
        rich_tracebacks=True,
    )
    root = logging.getLogger()
    # 既存ハンドラをクリアしてから設定（重複防止）
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def info(msg: str, *args: object) -> None:
    """info レベルでログ出力。"""
    logging.info(msg, *args)


def warn(msg: str, *args: object) -> None:
    """warning レベルでログ出力。"""
    logging.warning(msg, *args)


def debug(msg: str, *args: object) -> None:
    """debug レベルでログ出力（verbose 時のみ表示）。"""
    logging.debug(msg, *args)


def print(msg: str = "", *args: object, **kwargs: object) -> None:
    """コンソールへ装飾なしで出力する（``rich.Console.print`` の thin wrapper）。"""
    _console.print(msg, *args, **kwargs)  # type: ignore[arg-type]


def is_verbose() -> bool:
    """verbose モードか。"""
    return _verbose
