"""実行設定（Plan §6.6）と ``iroiro.toml`` ローダー（v0.3・Plan 003 §4）。"""

from __future__ import annotations

import logging
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from iroiro.errors import IroiroError
from iroiro.translator import ApiConfig, PromptConfig

_logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RunConfig:
    """``translate`` コマンド1回の実行設定。

    Attributes:
        input_path: 入力XMLのパス。
        output_path: 出力XMLのパス。
        api: API 設定。
        prompts: LLM 挙動中核設定（v0.5 追加）。``system_prompt`` /
            ``rec_hints`` / ``reject_phrases`` を含む ``PromptConfig``。
            ``iroiro.toml`` から構築される。
        resume: ``--resume`` フラグ。progress.json を読んで続きから。
        dry_run: ``--dry-run`` フラグ。LLM を呼ばず件数表示のみ。
        verbose: ``-v`` フラグ。詳細ログ。
        skip_records: スキップ対象 REC 型のセット（v0.2 追加・v0.6 で toml 必須化）。
            ``iroiro.toml`` の ``skip_records`` または CLI ``--skip-records`` から
            構築される。v0.6 で :data:`DEFAULT_SKIP_RECORDS` 定数は削除されコード内
            デフォルトは無い（Plan 006 §5・案 α 徹底版）。
        retry_failed: ``--retry-failed`` フラグ（v0.4 追加）。resume 時に
            ``failed`` エントリを ``state=pending`` に戻して再翻訳対象にする。
            デフォルト ``False``（後方互換・v0.3 までと同じ挙動）。優先順位は
            CLI ``--retry-failed`` / ``--no-retry-failed`` ＞ iroiro.toml ＞ False。
    """

    input_path: Path
    output_path: Path
    api: ApiConfig
    prompts: PromptConfig
    resume: bool
    dry_run: bool
    verbose: bool
    skip_records: frozenset[str]
    retry_failed: bool


# ===========================================================================
# iroiro.toml ローダー（v0.3・Plan 003 §4 / §7.2）
# ===========================================================================


def load_config(explicit_path: Path | None) -> dict[str, object]:
    """``iroiro.toml`` を読んで ``[iroiro]`` セクションの dict を返す（v0.5）。

    Args:
        explicit_path: ``--config`` で明示指定されたパス。``None`` なら cwd の
            ``iroiro.toml`` を探す。

    Returns:
        ``[iroiro]`` テーブルの dict（**型検証・値域検証済み**）。
        v0.5 では ``system_prompt`` / ``reject_phrases`` / ``rec_hints`` の
        3 新項目が必須（``reject_phrases`` は ``frozenset[str]`` に normalize 済み・
        ``rec_hints`` は ``dict[str, str]`` のまま）。v0.6 では ``skip_records``
        も必須（``frozenset[str]`` に normalize 済み・Plan 006 §5）。

    Raises:
        IroiroError: ファイル無し・``[iroiro]`` セクション無し・4 必須項目のいずれか欠損・
            パースエラー・型エラー・値域エラー・``[iroiro]`` がテーブルでない・
            ``[iroiro.rec_hints]`` がテーブルでない。

    v0.5 の破壊的変更（Plan 005 §2.2 / §2.9）:

    - ファイル無し（``--config`` 無指定時）は ``{}`` 返却ではなく ``IroiroError``
    - ``[iroiro]`` セクション無しも ``{}`` 返却ではなく ``IroiroError``
    - ``system_prompt`` / ``reject_phrases`` / ``[iroiro.rec_hints]`` は必須

    v0.6 の破壊的変更（Plan 006 §5.3）:

    - ``skip_records`` が必須（``[iroiro] skip_records`` 配列・欠損時 ``IroiroError``）
    - :data:`DEFAULT_SKIP_RECORDS` 定数はコードから完全削除（案 α 徹底版）

    検証ルール（Plan 003 §4.5.1 + Plan 005 §2.5 + Plan 006 §5.2）:

        ============  =======  ===========  =====================================
        キー          型       値域          備考
        ============  =======  ===========  =====================================
        ``api_base``  ``str``  非空          ``""`` 拒否
        ``api_key``   ``str``  ``""`` 許可   llama.cpp は検証しないので空でも動く
        ``model``     ``str``  非空
        ``timeout``   ``float`` ``> 0``      ``int`` 許容・``bool`` 拒否
        ``concurrency`` ``int`` ``>= 1``     ``bool`` 拒否
        ``max_chars`` ``int``  ``>= 0``      0 は正当値（全件スキップ）
        ``retry_failed`` ``bool`` 厳格 bool  ``int`` 拒否
        ``system_prompt`` ``str`` 非空       strip 後も非空・``""`` / ``"   "`` 拒否
        ``reject_phrases`` ``list[str]`` 各要素非空  ``[]`` 許可・重複は ``frozenset`` 化
        ``rec_hints`` ``dict[str, str]`` 各キー/値非空  ``{}`` 許可・``bool`` 拒否
        ``skip_records`` ``list[str]`` 各要素非空  ``[]`` 許可・重複は ``frozenset`` 化・
                                                   ``strip().upper()`` で正規化（v0.6）
        ============  =======  ===========  =====================================

    ``bool`` は全ての数値フィールドで拒否（Python ``bool ⊂ int`` 事故防止）。
    未知キー混在時は ``WARNING`` ログを出すが **例外送出しない**・既知キーは
    返り値に含める（前方互換のため）。未知 REC キーは ``WARNING`` 無しで許可。
    """
    # ---- 1. パス解決 ------------------------------------------------------
    if explicit_path is not None:
        path = explicit_path
        if not path.is_file():
            raise IroiroError(f"config file not found: {path}")
    else:
        path = Path.cwd() / "iroiro.toml"
        if not path.is_file():
            # v0.5（Plan 005 §2.2）: cwd に iroiro.toml 無し → IroiroError
            # （v0.4 までは ``{}`` 返却で後方互換だったが破壊的変更）
            raise IroiroError(
                f"iroiro.toml not found in {Path.cwd()}."
                "  -> Run: cp iroiro.toml.example iroiro.toml"
                "  -> Or specify: --config /path/to/iroiro.toml"
            )

    # ---- 2. TOML パース --------------------------------------------------
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise IroiroError(f"invalid TOML in {path}: {e}") from e

    # ---- 3. [iroiro] テーブル取得 ----------------------------------------
    # v0.5（Plan 005 §2.2 / §4.5 T149）: ``[iroiro]`` セクション自体が存在しない
    # 場合も ``IroiroError``（v0.4 までは ``{}`` 返却だったが破壊的変更）。
    if "iroiro" not in data:
        raise IroiroError(f"[iroiro] section is required in {path}")
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
            # 未知キー: WARNING ログのみ・例外送出しない（前方互換・T98 / T150）
            _logger.warning(
                "unknown key %r in [iroiro] of %s — ignored", key, path
            )
            continue
        result[key] = validator(raw, key, path)

    # ---- 5. v0.5 必須チェック（3 新項目） --------------------------------
    # Plan 005 §2.2: ``system_prompt`` / ``reject_phrases`` / ``[iroiro.rec_hints]``
    # は必須。未知キー扱いで無視された場合も result に含まれないため、ここで改めて
    # 必須チェックする（T133 / T137 / T138）。
    if "system_prompt" not in result:
        raise IroiroError(f"[iroiro] system_prompt is required in {path}")
    if "reject_phrases" not in result:
        raise IroiroError(f"[iroiro] reject_phrases is required in {path}")
    # ``rec_hints`` は ``[iroiro.rec_hints]`` サブテーブルとして別途格納される。
    # ``data["iroiro"]`` に ``"rec_hints"`` キーが存在するかで判定する（Codex review
    # 5回目 notes 3）: ``rec_hints = {}`` も ``[iroiro.rec_hints]`` も ``tomllib``
    # 後は ``data["iroiro"]["rec_hints"]`` の nested dict になるため、``None`` か
    # どうかでテーブル存在判定する。
    if iroiro_table.get("rec_hints") is None:
        raise IroiroError(f"[iroiro.rec_hints] table is required in {path}")

    # v0.6（Plan 006 §5.3）: ``skip_records`` も必須。``DEFAULT_SKIP_RECORDS`` 定数は
    # 完全削除されコード内デフォルトが無いため、toml 必須チェックで担保する。
    if "skip_records" not in result:
        raise IroiroError(f"[iroiro] skip_records is required in {path}")

    # 設定が1件以上読み込まれた場合、INFO ログで出力（N3）。
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


# ---------------------------------------------------------------------------
# v0.5 新規 validator（system_prompt / reject_phrases / rec_hints・Plan 005 §2.5）
# ---------------------------------------------------------------------------


def _validate_system_prompt(v: object, key: str, path: Path) -> str:
    """``system_prompt`` の厳格 ``str`` 検証（v0.5・Plan 005 §2.5）。

    制約:
      - ``str`` 型のみ許可（``int`` / ``bool`` 拒否）
      - 非空（``""`` 拒否）
      - strip 後も非空（``"   "`` 拒否）

    戻り値は ``str`` のまま（normalize 無し）。``PromptConfig.system_prompt`` に代入可能。
    """
    if isinstance(v, bool) or not isinstance(v, str):
        raise IroiroError(
            f"{key} must be str, got {type(v).__name__} in {path}"
        )
    if v.strip() == "":
        raise IroiroError(
            f"{key} must be non-empty str in {path}"
        )
    return v


def _validate_reject_phrases(
    v: object, key: str, path: Path
) -> frozenset[str]:
    """``reject_phrases`` の ``list[str]`` 検証と ``frozenset[str]`` normalize（v0.5）。

    制約:
      - ``list`` 型のみ許可（文字列スカラー拒否）
      - 各要素は ``str`` のみ（``int`` / ``bool`` 拒否・``bool ⊂ int`` 事故防止）
      - 各要素は非空（``""`` 拒否）
      - 空リスト ``[]`` は許可（メタ返答チェック無効化・T136）

    戻り値は ``frozenset[str]``（重複は自動で除去される・T135）。
    ``PromptConfig.reject_phrases`` に直接代入可能。
    """
    if not isinstance(v, list):
        raise IroiroError(
            f"{key} must be a list in {path}"
        )
    normalized: set[str] = set()
    for i, elem in enumerate(v):
        # ``bool ⊂ int`` 事故防止: ``isinstance(True, str)`` は False なので
        # ``bool`` は ``str`` 検査で弾かれるが、明示的に拒否する（N2・厳格型検証思想）
        if isinstance(elem, bool) or not isinstance(elem, str):
            raise IroiroError(
                f"{key}[{i}] must be non-empty str in {path}"
            )
        if elem == "":
            raise IroiroError(
                f"{key}[{i}] must be non-empty str in {path}"
            )
        normalized.add(elem)
    return frozenset(normalized)


def _validate_rec_hints(
    v: object, key: str, path: Path
) -> dict[str, str]:
    """``[iroiro.rec_hints]`` の ``dict[str, str]`` 検証（v0.5・Plan 005 §2.5）。

    制約:
      - ``dict`` 型のみ許可（文字列等のスカラー拒否・T152）
      - 各キーは非空 ``str``（T140）
      - 各値は ``str`` のみ（``int`` / ``bool`` 拒否・T153）
      - 各値は非空（``""`` 拒否・T140）
      - 空テーブル ``{}`` は許可（REC ヒント無効化・T139）
      - 未知 REC キー（``"FOO:BAR"`` 等・quoted key 必須）は WARNING 無しで許可（T141 / T151）

    戻り値は ``dict[str, str]`` のまま（``PromptConfig.rec_hints`` に代入可能）。
    """
    if not isinstance(v, dict):
        raise IroiroError(
            f"[iroiro.rec_hints] must be a table, got {type(v).__name__} in {path}"
        )
    normalized: dict[str, str] = {}
    for k, val in v.items():
        if not isinstance(k, str) or k == "":
            raise IroiroError(
                f"rec_hints key must be non-empty in {path}"
            )
        # ``bool ⊂ int`` 事故防止: ``isinstance(True, str)`` は False だが、
        # 明示的に ``bool`` を拒否（N2・厳格型検証思想）
        if isinstance(val, bool) or not isinstance(val, str):
            raise IroiroError(
                f"rec_hints[{k!r}] must be non-empty str in {path}"
            )
        if val == "":
            raise IroiroError(
                f"rec_hints[{k!r}] must be non-empty str in {path}"
            )
        normalized[k] = val
    return normalized


def _validate_skip_records(
    v: object, key: str, path: Path
) -> frozenset[str]:
    """``skip_records`` の ``list[str]`` 検証と ``frozenset[str]`` normalize（v0.6・Plan 006 §5.2）。

    :func:`_validate_reject_phrases` と **対称的な厳格性** で実装（Codex review 指摘）。

    制約:
      - ``list`` 型のみ許可（文字列スカラー拒否）
      - 各要素は ``str`` のみ（``int`` / ``bool`` 拒否・``bool ⊂ int`` 事故防止）
      - 各要素は strip 後非空（``""`` / ``"   "`` 拒否）
      - 大文字正規化（``.strip().upper()``・``_parse_skip_records`` と同様）
      - 空リスト ``[]`` は許可（全件翻訳・``compute_skip_records_fingerprint`` の
        空集合特例と整合・Plan 006 §4.5）
      - 重複は ``frozenset`` 化で自動除去

    戻り値は ``frozenset[str]``。``RunConfig.skip_records`` に直接代入可能。
    """
    if not isinstance(v, list):
        raise IroiroError(
            f"{key} must be a list in {path}"
        )
    normalized: set[str] = set()
    for i, elem in enumerate(v):
        # ``bool ⊂ int`` 事故防止: ``isinstance(True, str)`` は False なので
        # ``bool`` は ``str`` 検査で弾かれるが、明示的に拒否する（N2・厳格型検証思想）
        if isinstance(elem, bool) or not isinstance(elem, str):
            raise IroiroError(
                f"{key}[{i}] must be non-empty str in {path}"
            )
        stripped = elem.strip()
        if stripped == "":
            raise IroiroError(
                f"{key}[{i}] must be non-empty str in {path}"
            )
        normalized.add(stripped.upper())
    return frozenset(normalized)


# key -> validator（戻り値は検証済みの str/int/float/bool/frozenset/dict・dict[str, object] に代入可能）
_VALIDATORS: dict[str, Callable[[object, str, Path], object]] = {
    "api_base": _validate_str_nonempty,
    "api_key": _validate_str_allow_empty,
    "model": _validate_str_nonempty,
    "timeout": _validate_number_positive,
    "concurrency": _validate_concurrency,
    "max_chars": _validate_max_chars,
    "retry_failed": _validate_bool,  # v0.4 追加
    "system_prompt": _validate_system_prompt,  # v0.5 追加
    "reject_phrases": _validate_reject_phrases,  # v0.5 追加
    "rec_hints": _validate_rec_hints,  # v0.5 追加
    "skip_records": _validate_skip_records,  # v0.6 追加（Plan 006 §5.2）
}
