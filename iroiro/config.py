"""実行設定（Plan §6.6）と ``iroiro.toml`` ローダー（v0.3・Plan 003 §4）。"""

from __future__ import annotations

import logging
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from iroiro.errors import IroiroError
from iroiro.translator import ApiConfig

_logger = logging.getLogger(__name__)


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
        retry_failed: ``--retry-failed`` フラグ（v0.4 追加）。resume 時に
            ``failed`` エントリを ``state=pending`` に戻して再翻訳対象にする。
            デフォルト ``False``（後方互換・v0.3 までと同じ挙動）。優先順位は
            CLI ``--retry-failed`` / ``--no-retry-failed`` ＞ iroiro.toml ＞ False。
    """

    input_path: Path
    output_path: Path
    api: ApiConfig
    resume: bool
    dry_run: bool
    verbose: bool
    skip_records: frozenset[str]
    retry_failed: bool


# ===========================================================================
# iroiro.toml ローダー（v0.3・Plan 003 §4 / §7.2）
# ===========================================================================


def load_config(explicit_path: Path | None) -> dict[str, object]:
    """``iroiro.toml`` を読んで ``[iroiro]`` セクションの dict を返す。

    Args:
        explicit_path: ``--config`` で明示指定されたパス。``None`` なら cwd の
            ``iroiro.toml`` を探す。

    Returns:
        ``[iroiro]`` テーブルの dict（**型検証・値域検証済み**）。
        ファイル無し（``--config`` 無指定時のみ）・``[iroiro]`` セクション無しは
        ``{}`` を返す。記述されていない項目はキーに含まれない（呼出側で
        内蔵デフォルトに落ちる）。

    Raises:
        IroiroError: ファイル無し（``--config`` 明示時のみ）・パースエラー・
            型エラー・値域エラー・``[iroiro]`` がテーブルでない。

    検証ルール（Plan 003 §4.5.1）:

        ============  =======  ===========  =====================================
        キー          型       値域          備考
        ============  =======  ===========  =====================================
        ``api_base``  ``str``  非空          ``""`` 拒否
        ``api_key``   ``str``  ``""`` 許可   llama.cpp は検証しないので空でも動く
        ``model``     ``str``  非空
        ``timeout``   ``float`` ``> 0``      ``int`` 許容・``bool`` 拒否
        ``concurrency`` ``int`` ``>= 1``     ``bool`` 拒否
        ``max_chars`` ``int``  ``>= 0``      0 は正当値（全件スキップ）
        ============  =======  ===========  =====================================

    ``bool`` は全ての数値フィールドで拒否（Python ``bool ⊂ int`` 事故防止）。
    未知キー混在時は ``WARNING`` ログを出すが **例外送出しない**・既知キーは
    返り値に含める（前方互換のため）。
    """
    # ---- 1. パス解決 ------------------------------------------------------
    if explicit_path is not None:
        path = explicit_path
        if not path.is_file():
            raise IroiroError(f"config file not found: {path}")
    else:
        path = Path.cwd() / "iroiro.toml"
        if not path.is_file():
            # cwd に iroiro.toml 無し → 後方互換（何もしない・警告も出さない）
            return {}

    # ---- 2. TOML パース --------------------------------------------------
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise IroiroError(f"invalid TOML in {path}: {e}") from e

    # ---- 3. [iroiro] テーブル取得 ----------------------------------------
    if "iroiro" not in data:
        # [iroiro] セクション無し → 空扱い（警告なし・Plan 003 §4.5.2/T94）
        return {}
    iroiro_table: object = data["iroiro"]
    if not isinstance(iroiro_table, dict):
        raise IroiroError(
            f"[iroiro] must be a table, got {type(iroiro_table).__name__} in {path}"
        )

    # ---- 4. 各キー検証 ---------------------------------------------------
    result: dict[str, object] = {}
    for key, raw in iroiro_table.items():
        validator = _VALIDATORS.get(key)
        if validator is None:
            # 未知キー: WARNING ログのみ・例外送出しない（前方互換・T98）
            _logger.warning(
                "unknown key %r in [iroiro] of %s — ignored", key, path
            )
            continue
        result[key] = validator(raw, key, path)

    # 設定が1件以上読み込まれた場合、INFO ログで出力（N3）。
    # ファイル無し・[iroiro] セクション無し・未知キーのみの場合は空 dict なので
    # このログは出ず、従来通りの静寂を保つ（後方互換）。
    # configure_logging は non-verbose 時にレベル INFO に設定するため、
    # デフォルト（-v 無し）でも本ログは表示される。
    if result:
        _logger.info("Loaded iroiro.toml from %s (%d keys)", path, len(result))
    return result


# ---------------------------------------------------------------------------
# 個別 validator（bool 拒否・値域チェック込み）
# ---------------------------------------------------------------------------


def _validate_str_nonempty(v: object, key: str, path: Path) -> str:
    """str かつ非空を検証（``api_base`` / ``model`` 用）。"""
    if not isinstance(v, str):
        raise IroiroError(
            f"{key} must be str, got {type(v).__name__} in {path}"
        )
    if v == "":
        raise IroiroError(f'{key} must be non-empty, got "" in {path}')
    return v


def _validate_str_allow_empty(v: object, key: str, path: Path) -> str:
    """str かつ空許可を検証（``api_key`` 用）。"""
    if not isinstance(v, str):
        raise IroiroError(
            f"{key} must be str, got {type(v).__name__} in {path}"
        )
    return v


def _validate_number_positive(v: object, key: str, path: Path) -> float:
    """数値（``int``/``float`` 許容・``bool`` 拒否）かつ ``> 0`` を検証。

    ``timeout`` 用。TOML では ``timeout = 120`` が ``int`` になるため ``int`` も
    受け入れる（``timeout = -1`` は値域エラーとして処理する必要があるため・T97）。
    """
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise IroiroError(
            f"{key} must be float, got {type(v).__name__} in {path}"
        )
    if not (v > 0):
        raise IroiroError(f"{key} must be > 0, got {v} in {path}")
    return float(v)


def _validate_int_min(v: object, key: str, path: Path, minimum: int) -> int:
    """``int``（``bool``/``float`` 拒否）かつ ``>= minimum`` を検証。"""
    if isinstance(v, bool) or not isinstance(v, int):
        raise IroiroError(
            f"{key} must be int, got {type(v).__name__} in {path}"
        )
    if not (v >= minimum):
        raise IroiroError(f"{key} must be >= {minimum}, got {v} in {path}")
    return v


def _validate_concurrency(v: object, key: str, path: Path) -> int:
    return _validate_int_min(v, key, path, 1)


def _validate_max_chars(v: object, key: str, path: Path) -> int:
    return _validate_int_min(v, key, path, 0)


def _validate_bool(v: object, key: str, path: Path) -> bool:
    """厳格 ``bool`` を検証（``retry_failed`` 用・v0.4 追加）。

    Python では ``bool ⊂ int``（``isinstance(True, int) == True``）だが、
    ``isinstance(1, bool) == False`` なので ``int`` 値（``1`` / ``0``）は拒否される。
    他の数値フィールド（timeout / concurrency / max_chars）が ``bool`` を拒否するのと
    対称的な「厳格 bool」思想。``retry_failed = 1`` のような書き間違いを暗黙に受け入れると、
    ``if retry_failed:`` で truthy 扱いされて **意図せず** 全 failed エントリが再試行対象に
    変わる事故に繋がるため、厳格 bool 以外は全て拒否する（Plan 004 §4.4 / T113）。
    """
    if not isinstance(v, bool):
        raise IroiroError(
            f"{key} must be bool, got {type(v).__name__} in {path}"
        )
    return v


# key -> validator（戻り値は検証済みの str/int/float/bool・dict[str, object] に代入可能）
_VALIDATORS: dict[str, Callable[[object, str, Path], object]] = {
    "api_base": _validate_str_nonempty,
    "api_key": _validate_str_allow_empty,
    "model": _validate_str_nonempty,
    "timeout": _validate_number_positive,
    "concurrency": _validate_concurrency,
    "max_chars": _validate_max_chars,
    "retry_failed": _validate_bool,  # v0.4 追加
}
