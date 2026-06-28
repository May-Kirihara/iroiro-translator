"""実行設定（Plan §6.6）。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from iroiro.translator import ApiConfig


@dataclass(slots=True)
class RunConfig:
    """``translate`` コマンド1回の実行設定。

    Attributes:
        input_path: 入力XMLのパス。
        output_path: 出力XMLのパス。
        api: API 設定。
        resume: ``--resume`` フラグ。progress.json を読んで続きから。
        dry_run: ``--dry-run`` フラグ。LLM を呼ばず件数表示のみ。
        verbose: ``-v`` フラグ。詳細ログ。
        skip_records: スキップ対象 REC 型のセット（v0.2 追加）。
            ``--no-skip-default-records`` / ``--skip-records`` から構築される。
    """

    input_path: Path
    output_path: Path
    api: ApiConfig
    resume: bool
    dry_run: bool
    verbose: bool
    skip_records: frozenset[str]
