"""test_cli.py — CLI end-to-end テスト（T36-T40）。

v0.2 追加: T64-T67（``--no-skip-default-records`` / ``--skip-records``）,
T69-T70（dry-run 重複カウント防止・REC skip の original_dest 保持）,
T82（CLI レベルの --resume fingerprint mismatch・exit code 2）。

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
        skip_records: frozenset[str]  # v0.2 追加

    def main() -> None: ...   # typer entry, `translate` サブコマンド

    ※ テストから呼ぶため `iroiro.cli.app`（typer.Typer インスタンス）が存在することを想定。

CLI インターフェース（Plan §5.4 / §5.2）:
    iroiro translate INPUT.xml [-o OUTPUT] [--api-base URL] [--api-key KEY]
        [--model NAME] [--concurrency N] [--max-chars N] [--timeout SEC]
        [--resume] [--dry-run] [-v]
        [--no-skip-default-records] [--skip-records TEXT]

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
  - v0.2 T64-T67: --no-skip-default-records / --skip-records の動作
  - v0.2 T69: dry-run で REC skip と言語 skip が重複カウントされない
  - v0.2 T70: REC skip されたエントリの <Dest> が original_dest を保持
  - v0.2 T82: --resume 時の fingerprint mismatch で exit code 2
"""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from iroiro.errors import IroiroError
from iroiro.models import StringEntry
from iroiro.progress import ProgressData

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
    no_skip_default_records: bool = False,
    skip_records_text: str = "",
) -> object:
    """`iroiro translate` を実行して CliRunner.invoke の結果を返す。

    v0.2 フラグ:
      - ``no_skip_default_records``: ``--no-skip-default-records``
      - ``skip_records_text``: ``--skip-records TEXT``（カンマ区切り）
    """
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
    if no_skip_default_records:
        args.append("--no-skip-default-records")
    if skip_records_text:
        args += ["--skip-records", skip_records_text]
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

    from iroiro.progress import compute_input_hash, compute_skip_records_fingerprint
    from iroiro.translator import DEFAULT_SKIP_RECORDS
    from iroiro.xml_io import parse_xml

    # tiny.xml を tmp_path にコピー（fixtures を汚さないため）
    tmp_input = tmp_path / "tiny.xml"
    shutil.copy(tiny_xml, tmp_input)

    # 事前に progress.json を作成（<input>.iroiro-progress.json）
    # v0.2 形式: skip_records_fingerprint を含める（デフォルト動作と一致させる）
    input_hash = compute_input_hash(tmp_input)
    fp_default = compute_skip_records_fingerprint(DEFAULT_SKIP_RECORDS)
    progress_path = tmp_path / (tmp_input.name + ".iroiro-progress.json")
    preexisting_translation = "【既存訳文】entry0"
    progress_path.write_text(
        json.dumps(
            {
                "input_path": str(tmp_input),
                "input_hash": input_hash,
                "api_base": "http://localhost:8081/v1",
                "model": "test-model",
                "skip_records_fingerprint": fp_default,
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


# ===========================================================================
# v0.2: T64-T67, T69-T70, T82 — 翻訳スキップ REC 型 CLI テスト
#
# Plan §5.2 / §6.2: --no-skip-default-records / --skip-records の動作検証。
# skip_records.xml フィクスチャ構成（8エントリ）:
#   - HDPT:FULL "Male Head"     → デフォルト skip（REC skip）
#   - WEAP:FULL "Iron Sword"    → デフォルト外（翻訳対象）
#   - MGEF:FULL "Fire Damage"   → デフォルト skip（REC skip）
#   - RACE:FULL "Nord"          → デフォルト skip（REC skip）
#   - BPTD:BPTN "Head"          → デフォルト skip（REC skip・:FULL 以外）
#   - ACTI:FULL "Wooden Door"   → デフォルト外（翻訳対象）
#   - ACTI:FULL ""              → 空（言語 skip）
#   - WEAP:FULL "既存の日本語"  → 日本語（言語 skip）
#
# デフォルト動作の期待値:
#   翻訳対象: 2, 言語skip: 2, REC skip: 4, 長文skip: 0（合計 8）
# ===========================================================================


def test_T64_no_skip_default_records_translates_hdpt(
    skip_records_xml: Path,
    tmp_path: Path,
    patch_translator,
) -> None:
    """T64: --no-skip-default-records 指定で HDPT:FULL が翻訳対象になる。

    デフォルト動作では HDPT:FULL は REC skip されるが、
    --no-skip-default-records でデフォルトリストを無効化すると翻訳される。
    """
    translated_sources: list[str] = []
    translated_recs: list[str] = []

    def handler(src: str, rec: str) -> str:
        translated_sources.append(src)
        translated_recs.append(rec)
        return f"【訳】{src}"

    patch_translator(handler=handler)

    output = tmp_path / "out_t64.xml"
    result = _run_translate(
        skip_records_xml, output=output, no_skip_default_records=True
    )
    assert result.exit_code == 0, f"CLI 成功: {result.output}"

    # HDPT:FULL "Male Head" が翻訳対象になっている（MockTranslator に渡された）
    assert "Male Head" in translated_sources, (
        "HDPT:FULL が --no-skip-default-records で翻訳対象になった"
    )
    assert "HDPT:FULL" in translated_recs


def test_T65_skip_records_adds_acti_full(
    skip_records_xml: Path,
    tmp_path: Path,
    patch_translator,
) -> None:
    """T65: --skip-records "ACTI:FULL" 指定で ACTI:FULL が追加スキップされる。

    デフォルトでは ACTI:FULL "Wooden Door" は翻訳対象だが、--skip-records で
    追加スキップを指定すると翻訳されなくなる。
    """
    translated_sources: list[str] = []

    def handler(src: str, rec: str) -> str:
        translated_sources.append(src)
        return f"【訳】{src}"

    patch_translator(handler=handler)

    output = tmp_path / "out_t65.xml"
    result = _run_translate(
        skip_records_xml, output=output, skip_records_text="ACTI:FULL"
    )
    assert result.exit_code == 0, f"CLI 成功: {result.output}"

    # ACTI:FULL "Wooden Door" は --skip-records で追加スキップされた
    assert "Wooden Door" not in translated_sources, (
        "ACTI:FULL が --skip-records で追加スキップされた"
    )
    # WEAP:FULL "Iron Sword" はデフォルトリスト外 + --skip-records 対象外 → 翻訳される
    assert "Iron Sword" in translated_sources, (
        "WEAP:FULL は引き続き翻訳対象"
    )


def test_T66_no_skip_default_plus_skip_records_mgef(
    skip_records_xml: Path,
    tmp_path: Path,
    patch_translator,
) -> None:
    """T66: --no-skip-default-records + --skip-records "MGEF:FULL" の複合ケース。

    Plan §5.2: --no-skip-default-records が「デフォルトを無効化」した上で
    --skip-records を適用する。
    このケースでは MGEF:FULL だけがスキップされ、HDPT/WEAP 等は翻訳される。
    （ユースケース: 魔法名をスキップしたいが他は翻訳したい）
    """
    translated_recs: list[str] = []
    translated_sources: list[str] = []

    def handler(src: str, rec: str) -> str:
        translated_recs.append(rec)
        translated_sources.append(src)
        return f"【訳】{src}"

    patch_translator(handler=handler)

    output = tmp_path / "out_t66.xml"
    result = _run_translate(
        skip_records_xml,
        output=output,
        no_skip_default_records=True,
        skip_records_text="MGEF:FULL",
    )
    assert result.exit_code == 0, f"CLI 成功: {result.output}"

    # MGEF:FULL "Fire Damage" はスキップ（--skip-records で指定）
    assert "Fire Damage" not in translated_sources, (
        "MGEF:FULL は --skip-records でスキップされた"
    )
    assert "MGEF:FULL" not in translated_recs

    # HDPT:FULL "Male Head" は翻訳される（デフォルトリストが無効化されているため）
    assert "Male Head" in translated_sources, (
        "HDPT:FULL は --no-skip-default-records で翻訳対象になった"
    )
    assert "HDPT:FULL" in translated_recs

    # WEAP:FULL "Iron Sword" も翻訳される
    assert "Iron Sword" in translated_sources


def test_T67_dry_run_includes_rec_skip_line(
    skip_records_xml: Path,
    tmp_path: Path,
    patch_translator,
) -> None:
    """T67: dry-run 出力に「スキップ（REC 型）」行が含まれる。

    Plan §5.3: dry-run 出力に「スキップ（REC 型）」を追加。
    skip_records.xml の場合、REC skip は 4件（HDPT/MGEF/RACE/BPTD）。
    """
    patch_translator(handler=lambda src, rec: f"【訳】{src}")  # 呼ばれないはず

    output = tmp_path / "out_t67.xml"
    result = _run_translate(skip_records_xml, output=output, dry_run=True)
    assert result.exit_code == 0, f"dry-run 成功: {result.output}"

    # 出力に「スキップ（REC 型）」が含まれる
    assert "スキップ（REC 型）" in result.output, (
        f"dry-run 出力に REC 型 skip 行がある: {result.output!r}"
    )

    # 出力ファイルは生成されない
    assert not output.exists(), "dry-run では出力ファイルを生成しない"


def test_T69_dry_run_no_double_count_between_rec_and_lang(
    skip_records_xml: Path,
    tmp_path: Path,
    patch_translator,
) -> None:
    """T69: dry-run で REC skip と言語 skip が重複カウントされない。

    Plan §5.3 + §6.2 T69: REC skip のエントリは言語判定に回さない（排他的）。
    skip_records.xml の場合、合計 = 総エントリ数 になる:
      総8 = 翻訳対象2 + 言語skip2 + REC skip4 + 長文skip0
    """
    import re

    patch_translator(handler=lambda src, rec: f"【訳】{src}")

    result = _run_translate(skip_records_xml, dry_run=True)
    assert result.exit_code == 0, f"dry-run 成功: {result.output}"

    out = result.output

    # 各数値を抽出（ラベルに続く数字）。数値が見つからない場合は 0 ではなく
    # テスト失敗にするため、デフォルト None を経由して assert。
    def _extract(label_substr: str) -> int | None:
        # "総エントリ数: 8" / "翻訳対象: 2" / "スキップ（空/日本語混入）: 2" 等
        # リッチタグが除去された状態の result.output を想定
        pattern = re.compile(
            re.escape(label_substr) + r"\D*(\d+)", re.MULTILINE
        )
        m = pattern.search(out)
        return int(m.group(1)) if m else None

    total = _extract("総エントリ数")
    translatable = _extract("翻訳対象")
    skipped_lang = _extract("スキップ（空/日本語混入）")
    skipped_rec = _extract("スキップ（REC 型）")
    skipped_long = _extract("スキップ（長文超過）")

    assert total == 8, f"総エントリ数は8: 実際 {total!r}\n出力: {out!r}"
    assert translatable == 2, (
        f"翻訳対象は2 (WEAP Iron Sword, ACTI Wooden Door): 実際 {translatable!r}"
    )
    assert skipped_lang == 2, (
        f"言語skipは2 (ACTI 空, WEAP 日本語): 実際 {skipped_lang!r}"
    )
    assert skipped_rec == 4, (
        f"REC skipは4 (HDPT, MGEF, RACE, BPTD): 実際 {skipped_rec!r}"
    )
    assert skipped_long == 0, f"長文skipは0: 実際 {skipped_long!r}"

    # 重複カウント防止: 合計 == 総エントリ数
    assert translatable + skipped_lang + skipped_rec + skipped_long == total, (
        "REC skip と言語 skip が重複カウントされていない（合計 = 総エントリ数）"
    )


def test_T70_rec_skipped_entry_preserves_original_dest(
    skip_records_xml: Path,
    tmp_path: Path,
    patch_translator,
) -> None:
    """T70: REC skip されたエントリの <Dest> が original_dest を保持する。

    Plan §5.6.3 / §5.9 + §6.2 T70: REC skip のエントリは source で上書きせず、
    original_dest を保持する（言語 skip と同じ単一セマンティクス）。

    HDPT:FULL "Male Head" の <Dest> は "Male Head" のまま（MockTranslator は呼ばれない）。
    """
    from iroiro.xml_io import parse_xml

    translated_sources: list[str] = []

    def handler(src: str, rec: str) -> str:
        translated_sources.append(src)
        return f"【訳】{src}"

    patch_translator(handler=handler)

    output = tmp_path / "out_t70.xml"
    result = _run_translate(skip_records_xml, output=output)
    assert result.exit_code == 0, f"CLI 成功: {result.output}"

    # 入出力を parse して HDPT:FULL エントリの <Dest> を比較
    in_entries, _, _, _ = parse_xml(skip_records_xml)
    out_entries, _, _, _ = parse_xml(output)

    assert len(in_entries) == len(out_entries) == 8

    # HDPT:FULL エントリを特定（index 0）
    hdpt_in = in_entries[0]
    assert hdpt_in.rec == "HDPT:FULL", f"前提: entries[0] は HDPT:FULL: {hdpt_in.rec!r}"
    hdpt_out = out_entries[0]

    # HDPT:FULL "Male Head" は MockTranslator に渡されない
    assert "Male Head" not in translated_sources, (
        "HDPT:FULL は REC skip され MockTranslator に渡されない"
    )

    # <Dest> は original_dest を保持（source "Male Head" で上書きされていない）
    assert hdpt_out.original_dest == hdpt_in.original_dest, (
        f"HDPT:FULL の <Dest> は original_dest を保持: "
        f"in={hdpt_in.original_dest!r} out={hdpt_out.original_dest!r}"
    )
    # 念のため、明示的に元の値と一致することを確認
    assert hdpt_out.original_dest == "Male Head"

    # MGEF:FULL も同様に original_dest を保持
    mgef_in = in_entries[2]
    assert mgef_in.rec == "MGEF:FULL"
    mgef_out = out_entries[2]
    assert mgef_out.original_dest == mgef_in.original_dest == "Fire Damage"
    assert "Fire Damage" not in translated_sources


def test_T82_cli_resume_fingerprint_mismatch_exit_code_2(
    skip_records_xml: Path,
    tmp_path: Path,
    patch_translator,
) -> None:
    """T82: CLI レベルで skip_records を変更して --resume → exit code 2 で停止。

    Plan §6.2c T82: T77 は ProgressWriter 単体レベル・T82 は CLI 統合レベル。
    progress.json に保存された skip_records_fingerprint が現在の skip_records と
    異なる場合、CLI は _apply_existing 呼出前に ValueError を catch して exit code 2
    で停止する（input_hash mismatch と同じパターン・v0.1 T21 の CLI 版）。
    """
    import shutil

    from iroiro.progress import compute_input_hash, compute_skip_records_fingerprint
    from iroiro.translator import DEFAULT_SKIP_RECORDS

    # skip_records.xml を tmp_path にコピー（fixtures を汚さないため）
    tmp_input = tmp_path / "skip_records.xml"
    shutil.copy(skip_records_xml, tmp_input)

    # progress.json を作成: DEFAULT_SKIP_RECORDS の fingerprint を保存
    input_hash = compute_input_hash(tmp_input)
    progress_path = tmp_path / (tmp_input.name + ".iroiro-progress.json")
    fp_default = compute_skip_records_fingerprint(DEFAULT_SKIP_RECORDS)
    progress_path.write_text(
        json.dumps(
            {
                "input_path": str(tmp_input),
                "input_hash": input_hash,
                "api_base": "http://localhost:8081/v1",
                "model": "test-model",
                "skip_records_fingerprint": fp_default,
                "entries": {0: "既存訳"},
                "failed": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    patch_translator(handler=lambda src, rec: f"【訳】{src}")

    # --no-skip-default-records で異なる skip_records を指定して --resume
    # → fingerprint が一致しない → exit code 2
    output = tmp_path / "out_t82.xml"
    result = _run_translate(
        tmp_input,
        output=output,
        resume=True,
        no_skip_default_records=True,  # fingerprint が "" になり不一致
    )

    assert result.exit_code == 2, (
        f"fingerprint mismatch で exit code 2: 実際 {result.exit_code}\n"
        f"output: {result.output}"
    )
    # 出力ファイルは生成されない
    assert not output.exists(), "fingerprint mismatch 時は出力ファイルを生成しない"


# ===========================================================================
# v0.3: T103-T109 — iroiro.toml 設定ファイル対応の CLI 統合テスト
#
# Plan §6.2 / docs/plans/003-config-file.md: --config フラグと iroiro.toml の
# 読み込み・優先順位を検証する。
#
# 検証方針:
#   - dry-run では progress.json が作られず Translator も構築されないため、
#     cfg.api を直接 capture して検証する（MockTranslator factory 経由）。
#   - tiny.xml を tmp_path にコピーして使い、fixtures ディレクトリを汚さない
#     （progress.json が <input>.iroiro-progress.json に作られるため）。
#   - cwd は monkeypatch.chdir(tmp_path) で制御（iroiro.toml の有無を再現）。
#
# 優先順位（Plan §4.4）:
#     強 ← CLI フラグ（明示指定時）＞ iroiro.toml ＞ 内蔵デフォルト → 弱
#
#   ※ `is None` 判定で `0` や `""` を falsy 扱いしない（T108/T109 の肝）。
#      `or` 演算子は `0` や `""` を falsy 扱いしてしまうので絶対に使わない。
# ===========================================================================


@pytest.fixture
def capture_api_config(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """iroiro.cli.Translator を差し替え、構築された ApiConfig を capture する。

    dry-run でない場合、``translate()`` は ``Translator(cfg.api)`` を呼ぶので、
    その ``cfg.api``（ApiConfig インスタンス）を capture できる。
    返り値の ``list[0]`` が構築された ApiConfig。

    MockTranslator を差し込むので LLM は呼ばれない（tiny.xml で高速）。
    """
    captured: list[object] = []

    def factory(cfg, client=None, **kwargs):
        captured.append(cfg)
        return MockTranslator(cfg, client=client)

    monkeypatch.setattr("iroiro.cli.Translator", factory, raising=False)
    monkeypatch.setattr("iroiro.translator.Translator", factory, raising=False)
    return captured


def _run_translate_with_config(
    input_xml: Path,
    *,
    output: Path | None = None,
    extra_args: list[str] | None = None,
) -> object:
    """``iroiro translate`` を最小限の引数で実行（config file テスト用）。

    既存の :func:`_run_translate` と違い、``--api-base`` / ``--model`` 等を
    自動付与しない。``extra_args`` で明示的に渡されたフラグのみを付ける。
    これにより「フラグ無し」（toml またはデフォルトに落ちる）状況を再現できる。

    ※ WP-2 完了前は ``--config`` フラグ自体が未実装のため、T106/T107 は
       Typer の unknown option エラーになる。WP-2 完了後に green 化する。
    """
    app = _get_app()
    runner = CliRunner()
    args = ["translate", str(input_xml)]
    if output is not None:
        args += ["-o", str(output)]
    if extra_args:
        args += extra_args
    return runner.invoke(app, args)


# ---------------------------------------------------------------------------
# T103: iroiro.toml 無し cwd + フラグ無し → 内蔵デフォルト使用（v0.1 互換）
# ---------------------------------------------------------------------------

def test_T103_no_toml_no_flags_uses_builtin_defaults(
    tiny_xml: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capture_api_config: list[object],
) -> None:
    """T103: iroiro.toml 無し cwd + フラグ無し → 内蔵デフォルト使用（v0.1 互換）。

    後方互換性の回帰保証。toml が存在せず CLI フラグも省略した場合は、
    ``iroiro/cli.py`` の ``DEFAULT_*`` 定数がそのまま使われる。
    （Plan §4.4 の最弱優先順位・v0.1 と同じ挙動）
    """
    import shutil

    from iroiro.cli import (
        DEFAULT_API_BASE,
        DEFAULT_API_KEY,
        DEFAULT_CONCURRENCY,
        DEFAULT_MAX_CHARS,
        DEFAULT_MODEL,
        DEFAULT_TIMEOUT,
    )

    tmp_input = tmp_path / "tiny.xml"
    shutil.copy(tiny_xml, tmp_input)
    monkeypatch.chdir(tmp_path)  # cwd は空（iroiro.toml 無し）

    output = tmp_path / "out_t103.xml"
    result = _run_translate_with_config(tmp_input, output=output)

    assert result.exit_code == 0, f"CLI 成功: {result.output}"
    assert len(capture_api_config) == 1, "Translator が1回構築された"
    cfg = capture_api_config[0]
    assert cfg.base_url == DEFAULT_API_BASE, (
        f"api_base は内蔵デフォルト: 実際 {cfg.base_url!r}"
    )
    assert cfg.api_key == DEFAULT_API_KEY
    assert cfg.model == DEFAULT_MODEL
    assert cfg.timeout == DEFAULT_TIMEOUT
    assert cfg.concurrency == DEFAULT_CONCURRENCY
    assert cfg.max_chars == DEFAULT_MAX_CHARS


# ---------------------------------------------------------------------------
# T104: iroiro.toml 有り + フラグ無し → toml 値が反映される
# ---------------------------------------------------------------------------

def test_T104_toml_applied_when_no_flags(
    tiny_xml: Path,
    tmp_path: Path,
    fixtures_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capture_api_config: list[object],
) -> None:
    """T104: iroiro.toml 有り + フラグ無し → toml 値が RunConfig に反映される。

    cwd に ``iroiro.toml``（全項目・DEFAULT_* と明確に異なる値）を置き、
    フラグを1つも指定しない場合、toml の値が ApiConfig に反映される
    （DEFAULT_* ではなく toml の値が使われる）。
    """
    import shutil

    tmp_input = tmp_path / "tiny.xml"
    shutil.copy(tiny_xml, tmp_input)
    shutil.copy(fixtures_dir / "iroiro_full.toml", tmp_path / "iroiro.toml")
    monkeypatch.chdir(tmp_path)

    output = tmp_path / "out_t104.xml"
    result = _run_translate_with_config(tmp_input, output=output)

    assert result.exit_code == 0, f"CLI 成功: {result.output}"
    assert len(capture_api_config) == 1, "Translator が1回構築された"
    cfg = capture_api_config[0]
    assert cfg.base_url == "http://from-toml:9999/v1", (
        f"api_base は toml の値: 実際 {cfg.base_url!r}"
    )
    assert cfg.api_key == "toml-secret-key"
    assert cfg.model == "toml-model-name"
    assert cfg.timeout == 99.0
    assert cfg.concurrency == 7
    assert cfg.max_chars == 7777


# ---------------------------------------------------------------------------
# T105: iroiro.toml 有り + --api-base X 明示 → フラグが優先
# ---------------------------------------------------------------------------

def test_T105_cli_flag_overrides_toml(
    tiny_xml: Path,
    tmp_path: Path,
    fixtures_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capture_api_config: list[object],
) -> None:
    """T105: iroiro.toml 有り + ``--api-base X`` 明示 → フラグが優先する。

    toml の ``api_base`` は ``"http://from-toml:9999/v1"`` だが、
    CLI ``--api-base`` で明示指定した値が優先される（Plan §4.4 最強優先順位）。
    他の項目は toml のまま（フラグで上書きしていないため）。
    """
    import shutil

    tmp_input = tmp_path / "tiny.xml"
    shutil.copy(tiny_xml, tmp_input)
    shutil.copy(fixtures_dir / "iroiro_full.toml", tmp_path / "iroiro.toml")
    monkeypatch.chdir(tmp_path)

    output = tmp_path / "out_t105.xml"
    result = _run_translate_with_config(
        tmp_input,
        output=output,
        extra_args=["--api-base", "http://from-cli/v1"],
    )

    assert result.exit_code == 0, f"CLI 成功: {result.output}"
    cfg = capture_api_config[0]
    assert cfg.base_url == "http://from-cli/v1", (
        f"CLI フラグが toml より優先: 実際 {cfg.base_url!r}"
    )
    # フラグで上書きしていない項目は toml のまま
    assert cfg.model == "toml-model-name"
    assert cfg.max_chars == 7777
    assert cfg.api_key == "toml-secret-key"


# ---------------------------------------------------------------------------
# T106: --config custom.toml → 指定パスが読まれる
# ---------------------------------------------------------------------------

def test_T106_config_flag_reads_custom_path(
    tiny_xml: Path,
    tmp_path: Path,
    fixtures_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capture_api_config: list[object],
) -> None:
    """T106: ``--config custom.toml`` → 指定パスが読まれる。

    cwd に ``iroiro.toml``（partial・別内容）と ``custom.toml``（full）を配置し、
    ``--config custom.toml`` で full の値が反映されることを確認する。
    これにより「cwd の iroiro.toml は無視され、--config のパスが優先される」
    ことを検証する（Plan §4.3 検索順位1）。
    """
    import shutil

    tmp_input = tmp_path / "tiny.xml"
    shutil.copy(tiny_xml, tmp_input)
    # cwd の iroiro.toml は partial（api_base="http://partial:8080/v1"）
    shutil.copy(fixtures_dir / "iroiro_partial.toml", tmp_path / "iroiro.toml")
    # custom.toml は full（api_base="http://from-toml:9999/v1"）
    shutil.copy(fixtures_dir / "iroiro_full.toml", tmp_path / "custom.toml")
    monkeypatch.chdir(tmp_path)

    output = tmp_path / "out_t106.xml"
    result = _run_translate_with_config(
        tmp_input,
        output=output,
        extra_args=["--config", str(tmp_path / "custom.toml")],
    )

    assert result.exit_code == 0, f"CLI 成功: {result.output}"
    cfg = capture_api_config[0]
    # custom.toml（full）の値が反映される（cwd の iroiro.toml は無視）
    assert cfg.base_url == "http://from-toml:9999/v1", (
        f"--config で指定したファイルが読まれる: 実際 {cfg.base_url!r}"
    )
    assert cfg.model == "toml-model-name"
    assert cfg.concurrency == 7
    assert cfg.max_chars == 7777


# ---------------------------------------------------------------------------
# T107: --config missing.toml → exit code 2
# ---------------------------------------------------------------------------

def test_T107_config_missing_file_exit_code_2(
    tiny_xml: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T107: ``--config missing.toml`` → exit code 2。

    存在しないファイルを ``--config`` で明示指定した場合、``IroiroError`` を
    catch して exit code 2 で停止する（Plan §4.5.2）。

    ※ ``--config`` 無指定時の cwd の iroiro.toml が存在しない場合は
       何もしない（後方互換）が、``--config`` で明示した場合はエラーになる。
    """
    import shutil

    tmp_input = tmp_path / "tiny.xml"
    shutil.copy(tiny_xml, tmp_input)
    monkeypatch.chdir(tmp_path)

    missing = tmp_path / "missing.toml"
    assert not missing.exists()

    output = tmp_path / "out_t107.xml"
    result = _run_translate_with_config(
        tmp_input,
        output=output,
        extra_args=["--config", str(missing)],
    )

    assert result.exit_code == 2, (
        f"存在しない --config で exit code 2: 実際 {result.exit_code}\n"
        f"output: {result.output}"
    )
    # 出力ファイルは生成されない
    assert not output.exists(), "エラー時は出力ファイルを生成しない"


# ---------------------------------------------------------------------------
# T108: toml max_chars=4000 + CLI --max-chars 0 → CLI の 0 が勝つ
# ---------------------------------------------------------------------------

def test_T108_cli_max_chars_zero_overrides_toml(
    tiny_xml: Path,
    tmp_path: Path,
    fixtures_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capture_api_config: list[object],
) -> None:
    """T108: toml max_chars + CLI ``--max-chars 0`` → CLI の 0 が勝つ。

    Plan §4.4 の ``is None`` 判定の検証。CLI で明示的に 0 を渡した場合、
    falsy 扱いされずに 0 が採用される（toml の 7777 でなく 0）。
    ``or`` 演算子を使うと 0 は falsy なので toml の 7777 に埋もれてしまうが、
    ``is None`` 判定なら 0 が正しく採用される。

    ※ max_chars=0 は「全件スキップ」の正当値（§4.5.1）。本テストでは
       ApiConfig の max_chars フィールドの値だけを検証し、スキップ挙動は
       別テスト（test_config.py T102 等）で担保する。
    """
    import shutil

    tmp_input = tmp_path / "tiny.xml"
    shutil.copy(tiny_xml, tmp_input)
    shutil.copy(fixtures_dir / "iroiro_full.toml", tmp_path / "iroiro.toml")
    monkeypatch.chdir(tmp_path)

    output = tmp_path / "out_t108.xml"
    result = _run_translate_with_config(
        tmp_input,
        output=output,
        extra_args=["--max-chars", "0"],
    )

    assert result.exit_code == 0, f"CLI 成功: {result.output}"
    cfg = capture_api_config[0]
    assert cfg.max_chars == 0, (
        f"CLI の 0 が toml の 7777 を上書き（falsy で埋もれない）: "
        f"実際 {cfg.max_chars!r}"
    )
    # フラグで上書きしていない項目は toml のまま
    assert cfg.base_url == "http://from-toml:9999/v1"


# ---------------------------------------------------------------------------
# T109: toml api_key="secret" + CLI --api-key "" → CLI の空文字が勝つ
# ---------------------------------------------------------------------------

def test_T109_cli_empty_api_key_overrides_toml(
    tiny_xml: Path,
    tmp_path: Path,
    fixtures_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capture_api_config: list[object],
) -> None:
    """T109: toml api_key + CLI ``--api-key ""`` → CLI の空文字が勝つ。

    Plan §4.4 の ``is None`` 判定の検証。CLI で明示的に空文字を渡した場合、
    falsy 扱いされずに空文字が採用される（toml の "toml-secret-key" でなく ""）。
    ``or`` 演算子を使うと "" は falsy なので toml の値に埋もれてしまうが、
    ``is None`` 判定なら空文字が正しく採用される。

    ※ ``--api-key ""`` をシェルから渡す場合は ``""`` でクォート必須。
       CliRunner では argv に直接空文字を渡すのでクォート不要。
    """
    import shutil

    tmp_input = tmp_path / "tiny.xml"
    shutil.copy(tiny_xml, tmp_input)
    shutil.copy(fixtures_dir / "iroiro_full.toml", tmp_path / "iroiro.toml")
    monkeypatch.chdir(tmp_path)

    output = tmp_path / "out_t109.xml"
    result = _run_translate_with_config(
        tmp_input,
        output=output,
        extra_args=["--api-key", ""],
    )

    assert result.exit_code == 0, f"CLI 成功: {result.output}"
    cfg = capture_api_config[0]
    assert cfg.api_key == "", (
        f"CLI の空文字が toml の secret を上書き（falsy で埋もれない）: "
        f"実際 {cfg.api_key!r}"
    )
    # フラグで上書きしていない項目は toml のまま
    assert cfg.base_url == "http://from-toml:9999/v1"


# ===========================================================================
# v0.4: T114-T117 — ``_apply_existing()`` のユニットテスト（Plan 004 §4.5 / §6.2）
#
# Plan 004 §4.5 で ``_apply_existing()`` に ``retry_failed: bool = False`` 引数が追加
# された。本セクションは同関数を直接呼び出して retry_failed の有無による state 遷移と
# new_dest の扱いを検証するホワイトボックステスト。
#
# ※ T123-T129 は CLI 統合テスト（end-to-end）。本セクション T114-T117 は関数単体の
#    テストで、より細かい state / new_dest の検証を担う。両者は互补関係にある。
#
# 検証対象の契約（Plan 004 §4.5）:
#   - retry_failed=False（デフォルト）: failed index → state=failed, new_dest=original_dest
#   - retry_failed=True: failed index → state=pending, new_dest=None（触らない）
#   - translated index は retry_failed に関わらず state=translated, new_dest=loaded
#   - 未処理 index は retry_failed に関わらず state=pending, new_dest=None（触らない）
#
# ※ new_dest=None のままの場合、serialize_xml は original_dest を <Dest> に出力する
#    （xml_io.py L199-200 / Plan §5.9）。これが Plan 004 §4.7「翻訳が終わるまで
#    original_dest を保持」の実現手段。
# ===========================================================================


def _make_entry(
    index: int, *, source: str = "Hello", dest: str = "Hello"
) -> StringEntry:
    """T114-T117 用の StringEntry を構築する（state=pending・new_dest=None）。

    ``parse_xml`` 直後と同じ初期状態を作る（index 以外はダミー値）。
    """
    return StringEntry(
        index=index,
        edid="TEST",
        rec="WEAP:FULL",
        source=source,
        original_dest=dest,
        new_dest=None,
        state="pending",
    )


def _make_progress(
    *, entries: dict[int, str] | None = None, failed: list[int] | None = None
) -> ProgressData:
    """T114-T117 用の ProgressData を構築する（entries / failed のみ差し替え）。"""
    return ProgressData(
        entries=entries or {},
        failed=failed or [],
        input_hash="testhash",
        api_base="http://localhost:8081/v1",
        model="test-model",
        skip_records_fingerprint="",
    )


def test_T114_apply_existing_retry_failed_false_keeps_failed() -> None:
    """T114: retry_failed=False（デフォルト）→ failed index は state=failed・new_dest=original_dest。

    従来動作（v0.3 までと同じ）の回帰保証。``retry_failed`` 引数を省略しても
    ``False`` を明示しても同じ挙動になることを検証する（後方互換）。
    """
    from iroiro.cli import _apply_existing

    # 引数省略（既存呼出し側と同じ）→ 従来動作
    entry_default = _make_entry(index=5, source="Hello", dest="OriginalDest5")
    existing = _make_progress(failed=[5])
    _apply_existing([entry_default], existing)

    assert entry_default.state == "failed", (
        f"引数省略時は failed 確定: 実際 {entry_default.state!r}"
    )
    assert entry_default.new_dest == "OriginalDest5", (
        f"new_dest は original_dest を保持: 実際 {entry_default.new_dest!r}"
    )

    # 明示的に False を渡しても同じ
    entry_explicit = _make_entry(index=5, source="Hello", dest="OriginalDest5")
    _apply_existing([entry_explicit], existing, retry_failed=False)
    assert entry_explicit.state == "failed", (
        f"retry_failed=False は failed 確定: 実際 {entry_explicit.state!r}"
    )
    assert entry_explicit.new_dest == "OriginalDest5"


def test_T115_apply_existing_retry_failed_true_marks_pending() -> None:
    """T115: retry_failed=True → failed index は state=pending・new_dest=None（触らない）。

    Plan 004 §4.5: 再試行対象になった証拠。``state=pending`` に戻ることで
    ``_translate_all`` の処理対象になる。``new_dest`` は触らない（``None`` のまま）
    ことで、serialize 時に ``original_dest`` が ``<Dest>`` に使われる
    （Plan 004 §4.7「翻訳が終わるまで original_dest を保持」）。
    翻訳が成功すれば ``new_dest`` に訳文が入る（T125 で統合検証）。
    """
    from iroiro.cli import _apply_existing

    entry = _make_entry(index=5, source="Hello", dest="OriginalDest5")
    existing = _make_progress(failed=[5])

    _apply_existing([entry], existing, retry_failed=True)

    assert entry.state == "pending", (
        f"pending に戻り再試行対象: 実際 {entry.state!r}"
    )
    assert entry.new_dest is None, (
        f"new_dest は触らない（None のまま・serialize 時に original_dest 使用）: "
        f"実際 {entry.new_dest!r}"
    )


def test_T116_apply_existing_translated_stays_translated_with_retry() -> None:
    """T116: retry_failed=True でも translated index は state=translated で確定。

    translated は retry_failed に関わらず最優先で確定（``entries`` が ``failed``
    より優先・両方に同じ index が有ることは不変性 ``entries ∩ failed = ∅`` で
    本来無いが、仮に有った場合は entries が勝つ）。一度成功した翻訳を再試行
    しない不変性の保証。
    """
    from iroiro.cli import _apply_existing

    entry = _make_entry(index=7, source="Hello", dest="OriginalDest7")
    existing = _make_progress(entries={7: "既存訳文7"})

    _apply_existing([entry], existing, retry_failed=True)

    assert entry.state == "translated", (
        f"translated は retry_failed に関わらず確定: 実際 {entry.state!r}"
    )
    assert entry.new_dest == "既存訳文7", (
        f"new_dest は既存訳文: 実際 {entry.new_dest!r}"
    )


def test_T117_apply_existing_untouched_stays_pending() -> None:
    """T117: retry_failed=True でも未処理 index は state=pending・new_dest=None のまま。

    既存 ``entries`` にも ``failed`` にも無い index は何も触られない（変化なし）。
    retry_failed が未処理エントリに影響を与えないことの保証。
    """
    from iroiro.cli import _apply_existing

    entry = _make_entry(index=9, source="Hello", dest="OriginalDest9")
    # entries も failed も空 → index=9 は未処理
    existing = _make_progress()

    _apply_existing([entry], existing, retry_failed=True)

    assert entry.state == "pending", (
        f"未処理 index は pending のまま: 実際 {entry.state!r}"
    )
    assert entry.new_dest is None, (
        f"未処理 index の new_dest は None のまま（触らない）: "
        f"実際 {entry.new_dest!r}"
    )


# ===========================================================================
# v0.4: T123-T129 — --retry-failed / iroiro.toml retry_failed の CLI 統合テスト
#
# Plan 004 §6.4: progress.json の failed エントリを再翻訳対象に戻す機能を検証。
# 優先順位（Plan 004 §4.1）: CLI ``--retry-failed`` / ``--no-retry-failed``
#   ＞ iroiro.toml ``retry_failed`` ＞ 内蔵デフォルト False
#
# 検証戦略:
#   - tiny.xml の entry[1]（BOOK:FULL "Line one<br>Line two"）は DEFAULT_SKIP_RECORDS
#     外かつ英語・非空・max_chars 以下のため **翻訳対象**。この index を progress.json
#     の failed に事前登録し、retry_failed の有無で MockTranslator に渡るかを検証する。
#   - progress.json は <input>.iroiro-progress.json に作られるため、tiny.xml を
#     tmp_path にコピーして fixtures ディレクトリを汚さない（T38/T82 と同じパターン）。
#   - skip_records_fingerprint は DEFAULT_SKIP_RECORDS と一致させ、T77/T82 の
#     fingerprint mismatch 経路に入らないようにする。
# ===========================================================================


def _seed_progress_with_failed(
    tmp_path: Path,
    input_xml: Path,
    failed_indices: list[int],
) -> Path:
    """progress.json に failed リストを事前登録する（v0.4 T123-T127 用 helper）。

    指定 index が failed として記録された状態を模擬。``input_hash`` は実ファイル
    から計算し、``skip_records_fingerprint`` は ``DEFAULT_SKIP_RECORDS``（デフォルト
    動作）と一致させることで fingerprint mismatch を回避する（T77/T82 のエラー
    経路に入らないようにする）。

    Returns:
        作成した progress.json のパス（``<input>.iroiro-progress.json``）。
    """
    from iroiro.progress import compute_input_hash, compute_skip_records_fingerprint
    from iroiro.translator import DEFAULT_SKIP_RECORDS

    input_hash = compute_input_hash(input_xml)
    fp_default = compute_skip_records_fingerprint(DEFAULT_SKIP_RECORDS)
    progress_path = tmp_path / (input_xml.name + ".iroiro-progress.json")
    progress_path.write_text(
        json.dumps(
            {
                "input_path": str(input_xml),
                "input_hash": input_hash,
                "api_base": "http://localhost:8081/v1",
                "model": "test-model",
                "skip_records_fingerprint": fp_default,
                "entries": {},
                "failed": failed_indices,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return progress_path


# ---------------------------------------------------------------------------
# T123: progress.json に failed=[1]・CLI --resume のみ → entry 1 は再翻訳されない
# ---------------------------------------------------------------------------

def test_T123_resume_without_retry_keeps_failed(
    tiny_xml: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    patch_translator,
) -> None:
    """T123: ``--resume`` のみ（``--retry-failed`` 無指定）→ entry 1 は再翻訳されない。

    Plan 004 §6.4 T123: retry_failed 未指定時はデフォルト False（v0.3 互換）。
    failed に確定した entry 1 は ``state=failed`` のまま再翻訳対象にならない。
    後方互換性の回帰保証。
    """
    import shutil

    from iroiro.xml_io import parse_xml

    tmp_input = tmp_path / "tiny.xml"
    shutil.copy(tiny_xml, tmp_input)
    monkeypatch.chdir(tmp_path)  # cwd は空（iroiro.toml 無し = retry_failed False）
    progress_path = _seed_progress_with_failed(tmp_path, tmp_input, failed_indices=[1])

    called_sources: list[str] = []

    def handler(src: str, rec: str) -> str:
        called_sources.append(src)
        return f"【訳】{src}"

    patch_translator(handler=handler)

    output = tmp_path / "out_t123.xml"
    result = _run_translate_with_config(
        tmp_input,
        output=output,
        extra_args=["--resume"],  # --retry-failed 無し = デフォルト False
    )

    assert result.exit_code == 0, f"CLI 成功: {result.output}"

    # entry[1] の source は MockTranslator に渡されない（failed 確定・v0.3 互換）
    src_entries, _, _, _ = parse_xml(tmp_input)
    entry1_source = src_entries[1].source
    assert entry1_source not in called_sources, (
        f"entry[1] は failed 確定のため再翻訳されない（v0.3 互換）: "
        f"called_sources={called_sources!r}"
    )
    # progress.json の failed は保持されたまま（1 が残っている）
    raw = json.loads(progress_path.read_text(encoding="utf-8"))
    assert 1 in raw["failed"], (
        f"failed から 1 は消えない（再翻訳されていない）: 実際 {raw['failed']!r}"
    )


# ---------------------------------------------------------------------------
# T124: progress.json に failed=[1]・CLI --resume --retry-failed → entry 1 が再翻訳される
# ---------------------------------------------------------------------------

def test_T124_resume_retry_failed_retranslates(
    tiny_xml: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    patch_translator,
) -> None:
    """T124: ``--resume --retry-failed`` → entry 1 が再翻訳される。

    Plan 004 §4.5 / §6.4 T124: ``retry_failed=True`` の場合、``_apply_existing`` は
    failed の index を ``state=pending`` に戻す。結果として翻訳対象になり
    MockTranslator に source が渡る。
    """
    import shutil

    from iroiro.xml_io import parse_xml

    tmp_input = tmp_path / "tiny.xml"
    shutil.copy(tiny_xml, tmp_input)
    monkeypatch.chdir(tmp_path)  # cwd は空
    _seed_progress_with_failed(tmp_path, tmp_input, failed_indices=[1])

    called_sources: list[str] = []

    def handler(src: str, rec: str) -> str:
        called_sources.append(src)
        return f"【訳】{src}"

    patch_translator(handler=handler)

    output = tmp_path / "out_t124.xml"
    result = _run_translate_with_config(
        tmp_input,
        output=output,
        extra_args=["--resume", "--retry-failed"],
    )

    assert result.exit_code == 0, f"CLI 成功: {result.output}"

    # entry[1] の source が MockTranslator に渡された（pending に戻って再翻訳）
    src_entries, _, _, _ = parse_xml(tmp_input)
    entry1_source = src_entries[1].source
    assert entry1_source in called_sources, (
        f"entry[1] は --retry-failed で pending に戻り再翻訳された: "
        f"called_sources={called_sources!r}"
    )


# ---------------------------------------------------------------------------
# T125: --resume --retry-failed・mock 成功 → progress.json から 1 が削除・entries["1"] に訳文
# ---------------------------------------------------------------------------

def test_T125_retry_success_clears_failed_in_progress(
    tiny_xml: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    patch_translator,
) -> None:
    """T125: retry 成功時の **不変性** 検証（最重要テスト）。

    Plan 004 §4.6 / §6.4 T125: ``--resume --retry-failed`` で再試行して成功した場合、
    ``mark_done(1, ...)`` が ``entries["1"]`` に訳文を追加した **後**、``failed`` から
    ``1`` を削除する。結果として progress.json は:
      - ``1 not in data["failed"]`` （不変性: entries ∩ failed = ∅）
      - ``"1" in data["entries"]``  （訳文が保存された）
    これにより「Resuming: X translated, Y failed」メッセージと progress.json の
    最終状態が常に整合する。ProgressWriter 単体の T121 と対になる CLI 統合検証。
    """
    import shutil

    tmp_input = tmp_path / "tiny.xml"
    shutil.copy(tiny_xml, tmp_input)
    monkeypatch.chdir(tmp_path)  # cwd は空
    progress_path = _seed_progress_with_failed(tmp_path, tmp_input, failed_indices=[1])

    patch_translator(handler=lambda src, rec: f"【訳】{src}")

    output = tmp_path / "out_t125.xml"
    result = _run_translate_with_config(
        tmp_input,
        output=output,
        extra_args=["--resume", "--retry-failed"],
    )

    assert result.exit_code == 0, f"CLI 成功: {result.output}"

    # ★ 不変性検証: progress.json を実際に読んで failed / entries を確認
    raw = json.loads(progress_path.read_text(encoding="utf-8"))

    # entries["1"] に訳文が入った（retry 成功）
    assert "1" in raw["entries"], (
        f"entries['1'] に再翻訳の訳文が保存された: 実際 {raw['entries']!r}"
    )
    assert raw["entries"]["1"].startswith("【訳】"), (
        f"entries['1'] は MockTranslator の訳文: 実際 {raw['entries']['1']!r}"
    )

    # failed から 1 が削除された（不変性: entries ∩ failed = ∅）
    assert 1 not in raw["failed"], (
        f"failed から 1 が削除された（不変性検証）: 実際 {raw['failed']!r}"
    )


# ---------------------------------------------------------------------------
# T126: iroiro.toml に retry_failed=true・CLI --resume（フラグ無指定）→ entry 1 が再翻訳
# ---------------------------------------------------------------------------

def test_T126_toml_retry_failed_true_applies_on_resume(
    tiny_xml: Path,
    tmp_path: Path,
    fixtures_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    patch_translator,
) -> None:
    """T126: ``iroiro.toml`` の ``retry_failed=true`` が ``--resume`` 時に反映される。

    Plan 004 §4.1 優先順位: CLI フラグ無指定時は iroiro.toml の値を採用。
    ``retry_failed=true`` が書かれた toml がある cwd で ``--resume`` すると、
    entry 1 が再翻訳対象になる（``--retry-failed`` を毎回打たなくて済むユーザー要望）。
    """
    import shutil

    from iroiro.xml_io import parse_xml

    tmp_input = tmp_path / "tiny.xml"
    shutil.copy(tiny_xml, tmp_input)
    shutil.copy(fixtures_dir / "iroiro_retry_true.toml", tmp_path / "iroiro.toml")
    monkeypatch.chdir(tmp_path)
    _seed_progress_with_failed(tmp_path, tmp_input, failed_indices=[1])

    called_sources: list[str] = []

    def handler(src: str, rec: str) -> str:
        called_sources.append(src)
        return f"【訳】{src}"

    patch_translator(handler=handler)

    output = tmp_path / "out_t126.xml"
    result = _run_translate_with_config(
        tmp_input,
        output=output,
        extra_args=["--resume"],  # フラグ無指定 → toml の retry_failed=true を採用
    )

    assert result.exit_code == 0, f"CLI 成功: {result.output}"

    # entry[1] が toml の retry_failed=true により再翻訳対象になった
    src_entries, _, _, _ = parse_xml(tmp_input)
    entry1_source = src_entries[1].source
    assert entry1_source in called_sources, (
        f"entry[1] は toml の retry_failed=true で再翻訳された: "
        f"called_sources={called_sources!r}"
    )


# ---------------------------------------------------------------------------
# T127: iroiro.toml retry_failed=true・CLI --resume --no-retry-failed → entry 1 は再翻訳されない
# ---------------------------------------------------------------------------

def test_T127_cli_no_retry_failed_overrides_toml(
    tiny_xml: Path,
    tmp_path: Path,
    fixtures_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    patch_translator,
) -> None:
    """T127: ``--no-retry-failed`` が ``iroiro.toml`` の ``retry_failed=true`` より優先。

    Plan 004 §4.1 優先順位: CLI フラグ（非 None）＞ iroiro.toml ＞ 内蔵 False。
    ``--no-retry-failed``（CLI で False を明示）は toml の ``true`` を上書きする。
    結果として entry 1 は再翻訳されず failed 確定のまま（v0.3 互換挙動に戻る）。
    T108/T109（``is None`` 判定で falsy を埋もれさせない）と同じ思想。
    """
    import shutil

    from iroiro.xml_io import parse_xml

    tmp_input = tmp_path / "tiny.xml"
    shutil.copy(tiny_xml, tmp_input)
    shutil.copy(fixtures_dir / "iroiro_retry_true.toml", tmp_path / "iroiro.toml")
    monkeypatch.chdir(tmp_path)
    _seed_progress_with_failed(tmp_path, tmp_input, failed_indices=[1])

    called_sources: list[str] = []

    def handler(src: str, rec: str) -> str:
        called_sources.append(src)
        return f"【訳】{src}"

    patch_translator(handler=handler)

    output = tmp_path / "out_t127.xml"
    result = _run_translate_with_config(
        tmp_input,
        output=output,
        extra_args=["--resume", "--no-retry-failed"],  # CLI で False を明示
    )

    assert result.exit_code == 0, f"CLI 成功: {result.output}"

    # entry[1] は --no-retry-failed により再翻訳されない（toml の true を上書き）
    src_entries, _, _, _ = parse_xml(tmp_input)
    entry1_source = src_entries[1].source
    assert entry1_source not in called_sources, (
        f"entry[1] は --no-retry-failed で再翻訳されない（toml の true を上書き）: "
        f"called_sources={called_sources!r}"
    )


# ---------------------------------------------------------------------------
# T128: Typer bool|None=None の3状態区別をヘルプ出力で確認
# ---------------------------------------------------------------------------

def test_T128_help_shows_retry_failed_flags(
    tmp_path: Path,
) -> None:
    """T128: ``--help`` に ``--retry-failed`` と ``--no-retry-failed`` が両方表示される。

    Plan 004 §4.3: Typer の ``--flag/--no-flag`` 構文（``bool | None = None``）が
    正しく認識されているかをヘルプ出力で検証する。3状態（未指定=None / True / False）
    を区別できることが本機能の肝（T126/T127 の前提）。

    本テストは WP-2 で ``--retry-failed/--no-retry-failed`` オプションが
    ``translate()`` に追加された後に green になる。追加前はヘルプに表示されない
    ため fail する（想定通り）。
    """
    app = _get_app()
    runner = CliRunner()
    result = runner.invoke(app, ["translate", "--help"])

    assert result.exit_code == 0, f"--help が成功: {result.output}"

    out = result.output
    # --retry-failed と --no-retry-failed の両方がヘルプに表示される
    # （Typer の / 構文が正しく認識されている証拠・3状態区別が可能）
    assert "--retry-failed" in out, (
        f"--retry-failed がヘルプに表示される: {out!r}"
    )
    assert "--no-retry-failed" in out, (
        f"--no-retry-failed がヘルプに表示される（3状態区別の証拠）: {out!r}"
    )


# ---------------------------------------------------------------------------
# T129: --retry-failed 単独（--resume 無し）→ 警告ログ + exit 0
# ---------------------------------------------------------------------------

def test_T129_retry_failed_without_resume_warns_and_continues(
    tiny_xml: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    patch_translator,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """T129: ``--retry-failed`` 単独（``--resume`` 無し）→ 警告ログ + exit 0。

    Plan 004 §11.4: ``--resume`` 無しの ``retry_failed`` は無意味（progress.json が
    読み込まれないため pending 戻しも発生しない）だが、exit 2 にする程のエラーでは
    ない。WARNING ログを出して通常実行を継続する（ユーザーが ``--resume`` 忘れに
    気づけるよう）。設計判断: 緩い側（継続）に倒す。
    """
    import logging
    import shutil

    tmp_input = tmp_path / "tiny.xml"
    shutil.copy(tiny_xml, tmp_input)
    monkeypatch.chdir(tmp_path)  # cwd は空（iroiro.toml 無し）

    patch_translator(handler=lambda src, rec: f"【訳】{src}")

    output = tmp_path / "out_t129.xml"
    with caplog.at_level(logging.WARNING):
        result = _run_translate_with_config(
            tmp_input,
            output=output,
            extra_args=["--retry-failed"],  # --resume 無し
        )

    assert result.exit_code == 0, (
        f"--retry-failed 単独は警告しつつ exit 0 で継続: "
        f"実際 {result.exit_code}\noutput: {result.output}"
    )

    # 警告ログ または stdout に retry / resume への言及がある
    # （iroiro.logging は rich console 経由で stdout にも出すので両方チェック）
    warning_msgs = [
        r.getMessage() for r in caplog.records
        if r.levelno >= logging.WARNING
    ]
    all_text = " ".join(warning_msgs) + " " + result.output
    assert "retry" in all_text.lower() or "resume" in all_text.lower(), (
        f"警告に retry/resume への言及がある（--resume 忘れの通知）: "
        f"warnings={warning_msgs!r}\nstdout: {result.output!r}"
    )


# ---------------------------------------------------------------------------
# T131: --resume --retry-failed で再試行 → 再失敗 → failed=[1] 保持・重複 append なし
#
# v0.4 Codex review 対応（N2 補完）: T118（mark_failed 重複チェック）と T125
# （retry 成功時の failed クリア）の「再失敗」側を補完する CLI 統合テスト。
# retry_failed=True で再試行して **再失敗** した場合:
#   - progress.json failed は [1] のまま（重複 append なし・mark_failed 重複チェック）
#   - entries に 1 は入らない（失敗なので訳文は保存されない）
#   - 出力 XML の entry[1] <Dest> は original_dest を保持（Plan 004 §4.7）
# ---------------------------------------------------------------------------

def test_T131_resume_retry_failed_refail_keeps_original_dest(
    tiny_xml: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    patch_translator,
) -> None:
    """T131: progress.json failed=[1] + --resume --retry-failed + mock が失敗 →
    index 1 は再び failed・new_dest=original_dest で保持・重複 append なし。

    Plan 004 §4.5 / §4.6 / §4.7: retry_failed=True で entry 1 が pending に戻り
    再翻訳対象になるが、MockTranslator が IroiroError を投げて再失敗する。
    このとき:

      1. ``mark_failed(1)`` の重複チェック（``if 1 not in failed``）により、
         failed は [1] のまま（重複 append されない → failed リスト膨張防止）
      2. entries に 1 は入らない（失敗なので訳文未保存）
      3. serialize 時 ``new_dest=None`` のため ``original_dest`` が <Dest> に出力される
         （Plan 004 §4.7「翻訳が終わるまで original_dest を保持」）

    T118（ProgressWriter 単体・重複チェック）・T125（retry 成功）の対になる
    「retry 再失敗」経路の CLI 統合検証。
    """
    import shutil

    from iroiro.xml_io import parse_xml

    tmp_input = tmp_path / "tiny.xml"
    shutil.copy(tiny_xml, tmp_input)
    monkeypatch.chdir(tmp_path)  # cwd は空（iroiro.toml 無し）
    progress_path = _seed_progress_with_failed(tmp_path, tmp_input, failed_indices=[1])

    # entry[1] の source（lxml が &lt;br&gt; をアンエスケープした状態で渡る）
    src_entries, _, _, _ = parse_xml(tmp_input)
    entry1_source = src_entries[1].source
    entry1_original_dest = src_entries[1].original_dest
    assert entry1_source == "Line one<br>Line two", (
        f"前提: entry[1] source は 'Line one<br>Line two': 実際 {entry1_source!r}"
    )

    # entry[1] だけ失敗させる handler（他は成功）
    def handler(src: str, rec: str) -> str:
        if src == entry1_source:
            raise IroiroError("mock retry failure for entry 1")
        return f"【訳】{src}"

    patch_translator(handler=handler)

    output = tmp_path / "out_t131.xml"
    result = _run_translate_with_config(
        tmp_input,
        output=output,
        extra_args=["--resume", "--retry-failed"],
    )

    assert result.exit_code == 0, (
        f"CLI は部分的失敗でも exit=0 を維持（T39 と同じ）: "
        f"実際 {result.exit_code}\noutput: {result.output}"
    )

    # ★ 1. progress.json を読んで failed / entries を確認
    raw = json.loads(progress_path.read_text(encoding="utf-8"))

    # failed は [1] のまま（mark_failed の重複チェックが働き append されない）
    assert raw["failed"] == [1], (
        f"failed は [1] のまま（mark_failed 重複チェックで append 抑制・"
        f"failed リスト膨張防止）: 実際 {raw['failed']!r}"
    )
    assert raw["failed"].count(1) == 1, (
        f"重複 append なし（T118 の CLI 統合検証）: 実際 {raw['failed']!r}"
    )

    # entries に 1 は無い（失敗なので訳文は保存されない）
    assert "1" not in raw["entries"], (
        f"entries に 1 は入らない（再失敗のため）: 実際 {raw['entries']!r}"
    )

    # ★ 2. 出力 XML を parse して entry[1] の <Dest> を確認
    out_entries, _, _, _ = parse_xml(output)
    out_entry1 = out_entries[1]
    assert out_entry1.original_dest == entry1_original_dest, (
        f"entry[1] の <Dest> は original_dest を保持（Plan 004 §4.7）: "
        f"実際 {out_entry1.original_dest!r} vs 期待 {entry1_original_dest!r}"
    )
