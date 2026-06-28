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
