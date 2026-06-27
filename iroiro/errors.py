"""iroiro-translator 共通例外。

Plan §5.5.3 / §5.6.3 / §5.9 で参照される ``IroiroError`` を定義する。
アプリケーション層の回復不能エラー（CDATA/comment 検出、トークン不一致、
リトライ最終失敗等）はこの例外で包んで呼び出し側に伝える。
"""

from __future__ import annotations


class IroiroError(Exception):
    """iroiro-translator のアプリケーション例外。

    呼び出し側（CLI 等）は本例外を catch して ``state = "failed"``、
    ``new_dest = original_dest`` の回復動作を行う（Plan §5.6.3 / §5.9）。
    """
