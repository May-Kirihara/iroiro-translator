"""iroiro-translator パッケージ。

Skyrim / Fallout4 / Starfield MOD の xTranslator 形式 XML (SSTXMLRessources v2) を入力とし、
``<Content>/<String>`` ごとに ``<Source>`` の英文を LLM で日本語訳し、
``<Dest>`` に書き戻した XML を出力するバッチ CLI を提供する。

詳細は ``docs/plans/001-initial.md`` を参照。
"""

from __future__ import annotations

__version__ = "0.6.0"
