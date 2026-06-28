"""``iroiro`` CLI エントリポイント。

Plan §5.4 / §6.7 で規定される ``translate`` サブコマンドを実装する。

``translate`` のフロー:
    1. ``parse_xml`` で entries/fmt/root/params を取得。
    2. ``--resume`` 時は ``ProgressWriter.load_existing`` で既存訳文を entries に反映。
    3. ``--dry-run`` 時は件数表示のみで終了。
    4. 各 entry を処理:
       * state != ``pending`` なら skip。
       * ``rec in skip_records`` → ``skipped``（REC 型スキップ・v0.2）。
       * ``is_translation_needed(source, rec, skip_records)`` が False → ``skipped``。
       * ``len(source) > max_chars`` → ``skipped``。
       * ``Translator.translate_entry`` で翻訳。``IroiroError`` は catch して ``failed``。
    5. ``serialize_xml`` で出力XMLを生成。

テスト容易性のため、``Translator`` はモジュール内で ``from iroiro.translator import Translator``
して参照する（``monkeypatch.setattr("iroiro.cli.Translator", ...)`` が効くように）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from iroiro import logging as iroiro_logging
from iroiro.config import RunConfig
from iroiro.errors import IroiroError
from iroiro.models import StringEntry
from iroiro.progress import (
    ProgressData,
    ProgressWriter,
    compute_input_hash,
    compute_skip_records_fingerprint,
)
from iroiro.translator import (
    DEFAULT_SKIP_RECORDS,
    ApiConfig,
    Translator,
    _parse_skip_records,
    is_translation_needed,
)
from iroiro.xml_io import parse_xml, serialize_xml

# モジュールレベルで ``app`` を定義（テストが ``from iroiro.cli import app`` するため）。
# callback を必ず定義することで「multi-command モード」にし、``translate`` サブコマンドを
# 明示的に呼び出すことを必須にする（``iroiro translate INPUT.xml``）。
# callback 無し & コマンド1つの場合、typer は single-command モードになり
# ``iroiro INPUT.xml`` と解釈されてしまう。
app = typer.Typer(
    name="iroiro",
    help=(
        "Skyrim MOD xTranslator 形式 XML を OpenAI 互換 LLM で英→日翻訳する。\n\n"
        "詳細は docs/plans/001-initial.md を参照。"
    ),
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def _main() -> None:
    """iroiro CLI。サブコマンド ``translate`` を持つ。"""
    # dummy callback: multi-command モードを強制するための空実装
    return None


# デフォルト値（Plan §5.4 / §13）
DEFAULT_API_BASE = "http://localhost:8081/v1"
DEFAULT_API_KEY = "iroiro"
DEFAULT_MODEL = "ggml-org/gemma-4-12B-it-GGUF:Q4_K_M"
DEFAULT_CONCURRENCY = 1
DEFAULT_MAX_CHARS = 4000
DEFAULT_TIMEOUT = 120.0


@app.command()
def translate(
    input: Path = typer.Argument(..., help="入力XMLファイルのパス"),
    output: Path | None = typer.Option(
        None,
        "-o",
        "--output",
        help="出力XMLファイルのパス。省略時は <input>.translated.xml",
    ),
    api_base: str = typer.Option(
        DEFAULT_API_BASE, "--api-base", help="OpenAI 互換 API のベース URL"
    ),
    api_key: str = typer.Option(
        DEFAULT_API_KEY, "--api-key", help="API キー（llama.cpp では検証されない）"
    ),
    model: str = typer.Option(DEFAULT_MODEL, "--model", help="モデル名"),
    concurrency: int = typer.Option(
        DEFAULT_CONCURRENCY, "--concurrency", help="同時リクエスト数"
    ),
    max_chars: int = typer.Option(
        DEFAULT_MAX_CHARS,
        "--max-chars",
        help="1エントリの最大文字数。超過時はスキップ（分割は v0.2機能）",
    ),
    timeout: float = typer.Option(
        DEFAULT_TIMEOUT, "--timeout", help="1リクエストの読み出しタイムアウト（秒）"
    ),
    resume: bool = typer.Option(
        False, "--resume", help="progress.json があれば再開"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="LLM を呼ばず処理件数のみ表示"
    ),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="詳細ログ"),
    no_skip_default_records: bool = typer.Option(
        False,
        "--no-skip-default-records",
        help="デフォルトの12件スキップを無効化（全 REC 型を翻訳対象にする）",
    ),
    skip_records_text: str = typer.Option(
        "",
        "--skip-records",
        help='追加スキップ REC 型（カンマ区切り・例: "LCTN:FULL,ACTI:FULL"）',
    ),
) -> None:
    """入力XMLの ``<Source>`` を翻訳し、``<Dest>`` に書き戻したXMLを出力する。"""
    iroiro_logging.configure_logging(verbose)

    if not input.exists():
        iroiro_logging.print(f"[red]Error:[/red] input file not found: {input}")
        raise typer.Exit(code=2)

    output_path = output if output is not None else _default_output_path(input)
    api_cfg = ApiConfig(
        base_url=api_base,
        api_key=api_key,
        model=model,
        timeout=timeout,
        concurrency=concurrency,
        max_chars=max_chars,
    )
    # skip_records 構築（Plan §5.2）:
    # - デフォルト: DEFAULT_SKIP_RECORDS（12件）+ --skip-records の追加要素
    # - --no-skip-default-records 単独: --skip-records のみ（空なら空 set = 全 REC 型翻訳）
    # - --no-skip-default-records + --skip-records: 後者のセットのみ適用
    if no_skip_default_records:
        skip_records = _parse_skip_records(skip_records_text)
    else:
        skip_records = DEFAULT_SKIP_RECORDS | _parse_skip_records(skip_records_text)

    cfg = RunConfig(
        input_path=input,
        output_path=output_path,
        api=api_cfg,
        resume=resume,
        dry_run=dry_run,
        verbose=verbose,
        skip_records=skip_records,
    )

    asyncio.run(_run(cfg))


def _default_output_path(input_path: Path) -> Path:
    """``<input>.translated.xml`` を返す。"""
    return input_path.with_name(input_path.stem + ".translated.xml")


def _progress_path(input_path: Path) -> Path:
    """``<input>.iroiro-progress.json`` を返す（Plan §5.8 / 申送り事項5）。"""
    return input_path.with_name(input_path.name + ".iroiro-progress.json")


async def _run(cfg: RunConfig) -> None:
    """``translate`` コマンドの本体（非同期）。"""
    console = iroiro_logging.get_console()

    # ---- 1. parse ----
    iroiro_logging.info("Parsing input: %s", cfg.input_path)
    entries, fmt, root, _params = parse_xml(cfg.input_path)
    iroiro_logging.info(
        "Parsed %d <String> entries (BOM=%s, newline=%r, encoding=%s)",
        len(entries),
        fmt.has_bom,
        fmt.newline,
        fmt.encoding,
    )

    # ---- 2. resume ----
    progress_path = _progress_path(cfg.input_path)
    input_hash = compute_input_hash(cfg.input_path)
    skip_records_fp = compute_skip_records_fingerprint(cfg.skip_records)
    writer = ProgressWriter(
        progress_path=progress_path,
        input_path=cfg.input_path,
        input_hash=input_hash,
        api_base=cfg.api.base_url,
        model=cfg.api.model,
        skip_records_fingerprint=skip_records_fp,
    )

    existing: ProgressData | None = None
    if cfg.resume:
        try:
            existing = writer.load_existing()
        except ValueError as e:
            iroiro_logging.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(code=2) from e
        if existing is not None:
            iroiro_logging.info(
                "Resuming: %d translated, %d failed",
                len(existing.entries),
                len(existing.failed),
            )
            _apply_existing(entries, existing)
        else:
            iroiro_logging.info("Resume requested but no existing progress.json found")

    # ---- 3. 件数集計（dry-run 表示用） ----
    # Plan §5.3 + T69: REC skip と言語 skip が重複カウントされないよう、
    # まず REC skip を抽出し、残り（non_rec_pending）で言語/長文判定を行う。
    total = len(entries)
    pending = [e for e in entries if e.state == "pending"]
    skipped_rec = [e for e in pending if e.rec in cfg.skip_records]
    non_rec_pending = [e for e in pending if e.rec not in cfg.skip_records]
    translatable = [
        e
        for e in non_rec_pending
        if is_translation_needed(e.source, e.rec, cfg.skip_records)
        and len(e.source) <= cfg.api.max_chars
    ]
    skipped_lang = [
        e
        for e in non_rec_pending
        if not is_translation_needed(e.source, e.rec, cfg.skip_records)
    ]
    skipped_long = [
        e
        for e in non_rec_pending
        if is_translation_needed(e.source, e.rec, cfg.skip_records)
        and len(e.source) > cfg.api.max_chars
    ]
    already_done = sum(1 for e in entries if e.state == "translated")

    console.print(f"[bold]総エントリ数:[/bold] {total}")
    console.print(f"[green]翻訳対象:[/green] {len(translatable)}")
    console.print(f"[yellow]スキップ（REC 型）:[/yellow] {len(skipped_rec)}")
    console.print(f"[yellow]スキップ（空/日本語混入）:[/yellow] {len(skipped_lang)}")
    console.print(f"[yellow]スキップ（長文超過）:[/yellow] {len(skipped_long)}")
    if already_done:
        console.print(f"[cyan]再開済（progress.json）:[/cyan] {already_done}")

    # ---- 4. dry-run ----
    if cfg.dry_run:
        console.print("[dim]--dry-run: LLM を呼ばず終了します[/dim]")
        return

    # ---- 5. 翻訳 ----
    translator = Translator(cfg.api)
    try:
        await _translate_all(translator, entries, writer, cfg)
    finally:
        await translator.aclose()

    # ---- 6. serialize & write ----
    iroiro_logging.info("Serializing output: %s", cfg.output_path)
    out_bytes = serialize_xml(entries, root, fmt)
    cfg.output_path.write_bytes(out_bytes)

    # 最終サマリ
    translated = sum(1 for e in entries if e.state == "translated")
    failed = sum(1 for e in entries if e.state == "failed")
    skipped = sum(1 for e in entries if e.state == "skipped")
    console.print(
        f"[bold green]完了:[/bold green] translated={translated}, "
        f"failed={failed}, skipped={skipped} / total={total}"
    )
    console.print(f"出力: {cfg.output_path}")
    console.print(f"進捗: {progress_path}")


def _apply_existing(entries: list[StringEntry], existing: ProgressData) -> None:
    """``load_existing`` の結果を entries に反映する。

    * ``existing.entries[index]`` → ``state=translated``, ``new_dest=loaded``
    * ``existing.failed`` に index がある → ``state=failed``, ``new_dest=original_dest``

    これにより、resume 時に出力XMLの ``<Dest>`` が progress.json の訳文になる。
    """
    for entry in entries:
        if entry.index in existing.entries:
            entry.new_dest = existing.entries[entry.index]
            entry.state = "translated"
        elif entry.index in existing.failed:
            entry.new_dest = entry.original_dest
            entry.state = "failed"


async def _translate_all(
    translator: Translator,
    entries: list[StringEntry],
    writer: ProgressWriter,
    cfg: RunConfig,
) -> None:
    """全エントリを並列翻訳する（``cfg.api.concurrency`` で同時実行制限）。"""
    sem = asyncio.Semaphore(max(1, cfg.api.concurrency))

    async def process(entry: StringEntry) -> None:
        if entry.state != "pending":
            return
        # REC 型スキップ（Plan §5.2 / §5.6.3）: skip_records に含まれる REC は
        # original_dest を保持して skipped にする（source で上書きしない）。
        if entry.rec in cfg.skip_records:
            entry.new_dest = entry.original_dest
            entry.state = "skipped"
            entry.skip_reason = "rec"
            return
        # 言語スキップ（空/空白/日本語混入）
        if not is_translation_needed(entry.source, entry.rec, cfg.skip_records):
            entry.new_dest = entry.original_dest
            entry.state = "skipped"
            entry.skip_reason = "language"
            return
        # 長文スキップ
        if len(entry.source) > cfg.api.max_chars:
            iroiro_logging.warn(
                "skipping long source (index=%d, len=%d > max_chars=%d)",
                entry.index,
                len(entry.source),
                cfg.api.max_chars,
            )
            entry.new_dest = entry.original_dest
            entry.state = "skipped"
            entry.skip_reason = "max_chars"
            return

        async with sem:
            try:
                translated = await translator.translate_entry(entry.source, entry.rec)
                entry.new_dest = translated
                entry.state = "translated"
                await writer.mark_done(entry.index, translated)
            except IroiroError as e:
                iroiro_logging.warn(
                    "translation failed (index=%d): %s", entry.index, e
                )
                entry.new_dest = entry.original_dest
                entry.state = "failed"
                await writer.mark_failed(entry.index)

    await asyncio.gather(*(process(e) for e in entries))


def main() -> None:
    """``iroiro`` エントリポイント。``pyproject.toml`` の ``[project.scripts]`` から呼ばれる。"""
    app()


if __name__ == "__main__":
    main()
