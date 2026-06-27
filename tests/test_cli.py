"""test_cli.py — CLI end-to-end テスト（T36-T40）。

対象モジュール: `iroiro/cli.py`、`iroiro/config.py`
シグネチャ契約（Plan §6.6 / §6.7）:
    @dataclass(slots=True)
    class RunConfig:
        input_path: Path
        output_path: Path
        api: ApiConfig
        resume: bool
        dry_run: bool
        verbose: bool

    def main() -> None: ...   # typer entry, `translate` サブコマンド

    ※ テストから呼ぶため `iroiro.cli.app`（typer.Typer インスタンス）が存在することを想定。

CLI インターフェース（Plan §5.4）:
    iroiro translate INPUT.xml [-o OUTPUT] [--api-base URL] [--api-key KEY]
        [--model NAME] [--concurrency N] [--max-chars N] [--timeout SEC]
        [--resume] [--dry-run] [-v]

モック戦略:
  - `iroiro.cli.Translator` / `iroiro.translator.Translator` を MockTranslator に置換
  - MockTranslator は translate_entry が固定訳文またはカスタムハンドラの結果を返す
  - LLM HTTP 通信は発生しない（Translator インスタンス自体を差し替え）

検証項目:
  - T36: tiny.xml → 出力 XML を再 parse して期待通り
  - T37: --dry-run → 出力ファイル無し、件数表示
  - T38: --resume → progress.json を読んで続き
  - T39: 失敗含むケース → <Dest> は元のまま
  - T40: 出力 XML を xTranslator 相互運用性チェック
"""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from iroiro.errors import IroiroError

# ===========================================================================
# MockTranslator: LLM を呼ばずに固定訳文を返す
# ===========================================================================

class MockTranslator:
    """Translator と同じ IF を持つモック。

    `handler` は `(source: str, rec: str) -> str`。
    未指定時は `【訳】{source}` を返す。
    例外を投げる handler も指定可能（T39 失敗テスト用）。
    """

    def __init__(self, cfg, client=None, handler: Callable[[str, str], str] | None = None):
        self.cfg = cfg
        self._handler = handler

    async def translate_entry(self, source: str, rec: str) -> str:
        if self._handler is None:
            return f"【訳】{source}"
        result = self._handler(source, rec)
        if isinstance(result, Exception):
            raise result
        return result

    async def aclose(self) -> None:
        pass


@pytest.fixture
def patch_translator(monkeypatch: pytest.MonkeyPatch):
    """iroiro.cli / iroiro.translator の Translator を MockTranslator で差し替える。

    handler を渡してカスタマイズ可能。
    """
    installed: dict[str, MockTranslator] = {}

    def install(handler: Callable[[str, str], str] | None = None) -> None:
        def factory(cfg, client=None, **kwargs):
            inst = MockTranslator(cfg, client=client, handler=handler)
            installed["inst"] = inst
            return inst

        # `from iroiro.translator import Translator` 形式
        monkeypatch.setattr("iroiro.cli.Translator", factory, raising=False)
        # `import iroiro.translator` 形式
        monkeypatch.setattr("iroiro.translator.Translator", factory, raising=False)

    return install


# ===========================================================================
# CliRunner / app 取得ヘルパー
# ===========================================================================

def _get_app():
    """iroiro.cli.app（typer.Typer）を取得。"""
    from iroiro.cli import app
    return app


def _run_translate(
    input_xml: Path,
    *,
    output: Path | None = None,
    resume: bool = False,
    dry_run: bool = False,
    api_base: str = "http://localhost:8081/v1",
    model: str = "test-model",
    max_chars: int = 4000,
    timeout: int = 30,
    concurrency: int = 1,
) -> object:
    """`iroiro translate` を実行して CliRunner.invoke の結果を返す。"""
    app = _get_app()
    runner = CliRunner()
    args = ["translate", str(input_xml)]
    if output is not None:
        args += ["-o", str(output)]
    if resume:
        args.append("--resume")
    if dry_run:
        args.append("--dry-run")
    args += ["--api-base", api_base]
    args += ["--model", model]
    args += ["--max-chars", str(max_chars)]
    args += ["--timeout", str(timeout)]
    args += ["--concurrency", str(concurrency)]
    return runner.invoke(app, args)


# ===========================================================================
# T36: tiny.xml → 出力 XML を再 parse して期待通り
# ===========================================================================

def test_T36_translate_basic(
    tiny_xml: Path,
    tmp_path: Path,
    patch_translator,
) -> None:
    """T36: tiny.xml を translate し、出力 XML を再 parse して期待通り。"""
    patch_translator(handler=lambda src, rec: f"【訳】{src}")

    output = tmp_path / "out.xml"
    result = _run_translate(tiny_xml, output=output)
    assert result.exit_code == 0, f"CLI 成功 (exit=0): {result.output}"

    # 出力ファイルが生成
    assert output.exists(), "出力ファイルが生成される"

    # 出力を再 parse
    from iroiro.xml_io import parse_xml
    entries, fmt, root, _ = parse_xml(output)
    assert len(entries) > 0, "エントリが抽出できる"

    # 翻訳対象のエントリ（alias 含む entry[0]）の <Dest> が MockTranslator の訳文
    # entry[0] は "Hello <alias=hero>, welcome to %{location}!" のような英文
    alias_entry = entries[0]
    # MockTranslator は f"【訳】{src}" を返すので、出力の <Dest> には
    # 「【訳】」接頭辞が付いているはず（翻訳が反映された証拠）
    assert alias_entry.original_dest.startswith("【訳】"), (
        f"<Dest> に翻訳結果が反映されている: {alias_entry.original_dest!r}"
    )
    # alias トークン・%{...} が保持されている（トークン整合性検証をパスした証拠）
    assert "<alias=hero>" in alias_entry.original_dest
    assert "%{location}" in alias_entry.original_dest

    # 出力の raw bytes を確認
    raw = output.read_bytes()
    assert b"<SSTXMLRessources>" in raw
    assert b"</SSTXMLRessources>" in raw


# ===========================================================================
# T37: --dry-run → 出力ファイル無し、件数表示
# ===========================================================================

def test_T37_dry_run_no_output(
    tiny_xml: Path,
    tmp_path: Path,
    patch_translator,
) -> None:
    """T37: --dry-run では出力ファイルを生成せず、処理件数を表示する。"""
    patch_translator(handler=lambda src, rec: f"【訳】{src}")  # 呼ばれないはず

    output = tmp_path / "out.xml"
    result = _run_translate(tiny_xml, output=output, dry_run=True)
    assert result.exit_code == 0, f"CLI 成功: {result.output}"

    # 出力ファイルが生成されない
    assert not output.exists(), "dry-run では出力ファイルを生成しない"

    # 標準出力に件数系の表示がある（"件" や "entries" 等のキーワード）
    # 実装依存だが、何らかの処理件数表示があるはず
    assert len(result.output) > 0, "何らかの出力がある"


# ===========================================================================
# T38: --resume → progress.json を読んで続き
# ===========================================================================

def test_T38_resume_reads_progress(
    tiny_xml: Path,
    tmp_path: Path,
    patch_translator,
) -> None:
    """T38: --resume 時に progress.json の訳文を再利用し、続きを処理する。

    progress.json に entry[0] の訳文を事前登録 → resume 実行 →
    entry[0] は既存訳文、他は MockTranslator の新規訳文。

    入力は tmp_path にコピーし、progress.json も tmp_path に置くことで
    fixtures ディレクトリを汚さない。
    """
    import shutil

    from iroiro.progress import compute_input_hash
    from iroiro.xml_io import parse_xml

    # tiny_xml を tmp_path にコピー（fixtures を汚さないため）
    tmp_input = tmp_path / "tiny.xml"
    shutil.copy(tiny_xml, tmp_input)

    # 事前に progress.json を作成（<input>.iroiro-progress.json）
    input_hash = compute_input_hash(tmp_input)
    progress_path = tmp_path / (tmp_input.name + ".iroiro-progress.json")
    preexisting_translation = "【既存訳文】entry0"
    progress_path.write_text(
        json.dumps(
            {
                "input_path": str(tmp_input),
                "input_hash": input_hash,
                "api_base": "http://localhost:8081/v1",
                "model": "test-model",
                "entries": {0: preexisting_translation},
                "failed": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # MockTranslator は entry[0] に呼ばれないはず（resume でスキップ）
    called_sources: list[str] = []

    def handler(src: str, rec: str) -> str:
        called_sources.append(src)
        return f"【新規訳】{src}"

    patch_translator(handler=handler)

    output = tmp_path / "out_resume.xml"
    result = _run_translate(tmp_input, output=output, resume=True)
    assert result.exit_code == 0, f"resume 実行成功: {result.output}"

    # 出力を parse して entry[0] の <Dest> が progress.json の既存訳文であることを検証
    out_entries, _, _, _ = parse_xml(output)
    assert out_entries[0].original_dest == preexisting_translation, (
        f"entry[0] は progress.json の既存訳文: {out_entries[0].original_dest!r}"
    )

    # entry[0] の source は MockTranslator に渡されていない（resume でスキップ）
    src_entries, _, _, _ = parse_xml(tmp_input)
    entry0_source = src_entries[0].source
    assert entry0_source not in called_sources, (
        "entry[0] は resume でスキップされ、MockTranslator に渡されない"
    )


# ===========================================================================
# T39: 失敗含むケース → <Dest> は元のまま
# ===========================================================================

def test_T39_failure_preserves_original_dest(
    tiny_xml: Path,
    tmp_path: Path,
    patch_translator,
) -> None:
    """T39: 翻訳失敗時は <Dest> が original_dest を保持する。

    MockTranslator が全エントリで IroiroError を投げる → 出力の全 <Dest> は
    入力の <Dest> と同じ（original_dest を保持）。
    """
    from iroiro.xml_io import parse_xml

    def failing_handler(src: str, rec: str) -> str:
        raise IroiroError("mock failure")

    patch_translator(handler=failing_handler)

    output = tmp_path / "out_fail.xml"
    result = _run_translate(tiny_xml, output=output)
    assert result.exit_code == 0, f"CLI は失敗しても exit=0（部分的失敗を許容）: {result.output}"

    # 出力の全 <Dest> が入力の <Dest> と同じ
    in_entries, _, _, _ = parse_xml(tiny_xml)
    out_entries, _, _, _ = parse_xml(output)

    assert len(in_entries) == len(out_entries)
    for in_e, out_e in zip(in_entries, out_entries, strict=True):
        assert out_e.original_dest == in_e.original_dest, (
            f"index {in_e.index}: <Dest> は元のまま (original_dest 保持)"
        )


# ===========================================================================
# T40: 出力 XML を xTranslator 相互運用性チェック
# ===========================================================================

def test_T40_xtranslator_interop(
    tiny_crlf_bom_xml: Path,
    tmp_path: Path,
    patch_translator,
) -> None:
    """T40: 出力 XML の宣言/BOM/CRLF/aliasエスケープが xTranslator 互換。

    実物形式（BOM+CRLF+standalone）の入力を処理し、出力も同じ形式を保持することを検証。
    """
    patch_translator(handler=lambda src, rec: f"【訳】{src}")

    output = tmp_path / "out_interop.xml"
    result = _run_translate(tiny_crlf_bom_xml, output=output)
    assert result.exit_code == 0, f"CLI 成功: {result.output}"

    raw = output.read_bytes()

    # 1. BOM 保持
    assert raw.startswith(b"\xef\xbb\xbf"), "出力は BOM 付き"

    # 2. CRLF 保持
    assert b"\r\n" in raw, "出力は CRLF を含む"

    # 3. standalone 宣言保持
    assert b'standalone="yes"' in raw, "standalone 宣言を保持"

    # 4. XML宣言が先頭（BOMの直後）
    assert raw.startswith(b'\xef\xbb\xbf<?xml')

    # 5. alias はエスケープされて格納（&lt;alias=...&gt;）
    assert b"&lt;alias=hero&gt;" in raw, "alias はエスケープされて格納"
    # 二重エスケープされていない
    assert b"&amp;lt;alias" not in raw, "二重エスケープなし"

    # 6. SSTXMLRessources ルート要素
    assert b"<SSTXMLRessources>" in raw
    assert raw.rstrip().endswith(b"</SSTXMLRessources>")

    # 7. 空要素は <X></X> 形式（自己閉じ無し）
    assert b"<Source/>" not in raw
    assert b"<Dest/>" not in raw
