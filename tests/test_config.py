"""test_config.py — ``load_config()`` のユニットテスト（T88-T102）。

v0.3 設定ファイル（iroiro.toml）対応の WP-1（テスト先行）。

対象モジュール: ``iroiro/config.py`` に追加される ``load_config``。

シグネチャ契約（Plan §4.5 / §7.2）::

    def load_config(explicit_path: Path | None) -> dict[str, object]:
        \"\"\"iroiro.toml を読んで [iroiro] セクションの dict を返す。

        Args:
            explicit_path: --config で明示指定されたパス。None なら cwd の iroiro.toml を探す。

        Returns:
            [iroiro] テーブルの dict（型検証・値域検証済み）。
            ファイル無し・[iroiro] セクション無しは {} を返す。

        Raises:
            IroiroError: ファイル無し（--config 明示時のみ）・パースエラー・
                型エラー・値域エラー・[iroiro] がテーブルでない。
        \"\"\"

検証ルール（§4.5.1）:

================  =======  ===========  =====================================
キー              型       値域          備考
================  =======  ===========  =====================================
``api_base``      ``str``  非空          ``""`` 拒否
``api_key``       ``str``  ``""`` 許可   llama.cpp は検証しないので空でも動く
``model``         ``str``  非空
``timeout``       ``float`` ``> 0``
``concurrency``   ``int``  ``>= 1``
``max_chars``     ``int``  ``>= 0``      0 は正当値（全件スキップ）
================  =======  ===========  =====================================

**``bool`` は拒否**（Python ``bool ⊂ int`` 事故防止）。
未知キー混在時は警告ログを出すが **例外送出しない**・既知キーは返り値に含める。

注意:
    WP-1（本ファイル）はテストのみを提供する。``iroiro/config.py`` に
    ``load_config`` が存在しない段階では、冒頭の import が ``ImportError`` に
    なりテスト全体が収集エラーになる。これは **想定通り**。WP-2 完了後に
    全テストが green になることを目指す。
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

import pytest

from iroiro.config import load_config
from iroiro.errors import IroiroError

# ===========================================================================
# 共通 fixture: tests/fixtures ディレクトリ
# ===========================================================================

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ===========================================================================
# T88: load_config(None) — cwd に iroiro.toml 無し → IroiroError（v0.5）
# ===========================================================================

def test_T88_no_config_file_returns_empty_dict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T88: cwd に iroiro.toml が無い場合、``load_config(None)`` は ``IroiroError``。

    v0.5（Plan 005 §2.2 / §2.9）での破壊的変更: ``iroiro.toml`` は ``--dry-run``
    含む全操作で必須。v0.4 までは ``{}`` 返却で後方互換だったが、v0.5 では
    ``IroiroError``（3 新項目が必須のため空 dict では要件を満たせない）。

    ※ 同契約は ``test_T142`` でも検証されている。T88 は歴史的経緯で v0.5 挙動に更新。
    """
    # tmp_path は空なので iroiro.toml は見つからない
    monkeypatch.chdir(tmp_path)
    with pytest.raises(IroiroError) as exc_info:
        load_config(None)
    msg = str(exc_info.value)
    # エラーメッセージに手がかり（``iroiro.toml`` 等）が含まれる
    assert "iroiro.toml" in msg or "config" in msg.lower(), (
        f"エラーメッセージに iroiro.toml への言及がある: 実際 {msg!r}"
    )


# ===========================================================================
# T89: 全項目記述の iroiro.toml → 全項目反映（v0.5 で 3 新項目追加）
# ===========================================================================

def test_T89_full_config_all_keys_reflected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T89: 全項目を記述した iroiro.toml を読み込み、全て反映されること。

    iroiro_full.toml の値（DEFAULT_* と明確に異なる）がそのまま返る。
    v0.5（Plan 005 §2.5）: ``system_prompt`` / ``reject_phrases`` / ``rec_hints``
    の 3 新項目も反映される。``reject_phrases`` は ``frozenset[str]`` に normalize
    される（T135 と整合）。
    """
    # fixture を cwd の iroiro.toml として配置
    shutil.copy(FIXTURES_DIR / "iroiro_full.toml", tmp_path / "iroiro.toml")
    monkeypatch.chdir(tmp_path)

    result = load_config(None)

    # 既存 6 項目（厳密比較）
    assert result["api_base"] == "http://from-toml:9999/v1"
    assert result["api_key"] == "toml-secret-key"
    assert result["model"] == "toml-model-name"
    assert result["timeout"] == 99.0
    assert result["concurrency"] == 7
    assert result["max_chars"] == 7777

    # v0.5 の 3 新項目（system_prompt は multiline のため型と非空のみ検証・
    # R2「byte 完全一致ではなく意味的同等」に準拠）
    assert isinstance(result["system_prompt"], str)
    assert result["system_prompt"].strip() != ""

    # reject_phrases は frozenset[str] に normalize（21 語・重複除去済み）
    assert isinstance(result["reject_phrases"], frozenset)
    assert "了解" in result["reject_phrases"]
    assert "翻訳します" in result["reject_phrases"]
    assert len(result["reject_phrases"]) == 21

    # rec_hints は dict[str, str]・18 種
    assert isinstance(result["rec_hints"], dict)
    assert "MGEF:FULL" in result["rec_hints"]
    assert "BOOK:DESC" in result["rec_hints"]
    assert len(result["rec_hints"]) == 18

    # v0.6 skip_records は frozenset[str]・14 件
    assert isinstance(result["skip_records"], frozenset)
    assert len(result["skip_records"]) == 14

    # 全体で 10 キー（既存 6 + v0.5 新規 3 + v0.6 新規 1）
    assert len(result) == 10, f"全項目が反映される: 実際 {result!r}"


# ===========================================================================
# T90: 一部項目のみ → その項目だけ（残りは含まれない）・v0.5 で 3 新項目追加
# ===========================================================================

def test_T90_partial_config_only_recorded_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T90: 一部項目のみ記述の場合、その項目だけが dict に含まれる。

    記述されていない項目は dict のキーに存在しない（呼出側で _resolve が
    内蔵デフォルトに落ちる）。これが §4.4 のマージ規則の前提。

    v0.5（Plan 005 §2.2）: ``system_prompt`` / ``reject_phrases`` / ``rec_hints``
    の 3 新項目は必須・``iroiro_partial.toml`` に含まれるため、result dict にも
    含まれる。``reject_phrases`` は ``frozenset[str]`` に normalize。
    """
    shutil.copy(FIXTURES_DIR / "iroiro_partial.toml", tmp_path / "iroiro.toml")
    monkeypatch.chdir(tmp_path)

    result = load_config(None)

    # 記述された既存項目のみ含まれる
    assert result["api_base"] == "http://partial:8080/v1"
    assert result["model"] == "partial-model"
    # 記述されていない項目はキーに無い（デフォルトに落ちる根拠）
    assert "api_key" not in result
    assert "timeout" not in result
    assert "concurrency" not in result
    assert "max_chars" not in result

    # v0.5 の 3 新項目（partial fixture に含まれるため反映）
    assert "system_prompt" in result
    assert isinstance(result["system_prompt"], str)
    # ``reject_phrases`` は ``frozenset[str]`` に normalize（2 語）
    assert isinstance(result["reject_phrases"], frozenset)
    assert result["reject_phrases"] == frozenset({"了解", "翻訳します"})
    # ``rec_hints`` は ``dict[str, str]``・2 種
    assert result["rec_hints"] == {
        "MGEF:FULL": "魔法の効果名。",
        "BOOK:DESC": "書籍の本文。",
    }


# ===========================================================================
# T91: load_config(Path("custom.toml")) — 明示パス読込
# ===========================================================================

def test_T91_explicit_path_loads_custom_file(
    tmp_path: Path,
) -> None:
    """T91: --config で明示指定されたパスを読み込む。

    iroiro.toml 以外のファイル名でも explicit_path 経由で読める。
    cwd の iroiro.toml は探索しない（明示パスが優先）。
    """
    custom_path = tmp_path / "custom.toml"
    shutil.copy(FIXTURES_DIR / "iroiro_full.toml", custom_path)

    result = load_config(custom_path)

    assert result["api_base"] == "http://from-toml:9999/v1"
    assert result["model"] == "toml-model-name"
    assert result["concurrency"] == 7


# ===========================================================================
# T92: load_config(Path("missing.toml")) — 存在しない → IroiroError
# ===========================================================================

def test_T92_explicit_missing_path_raises(
    tmp_path: Path,
) -> None:
    """T92: --config で存在しないパスを明示指定した場合、IroiroError を投げる。

    ファイル無し（--config 明示時のみ）は §4.5.2 で exit code 2 を想定。
    エラーメッセージにパスが含まれること（ユーザーが原因を特定できるため）。
    """
    missing_path = tmp_path / "missing.toml"
    assert not missing_path.exists()

    with pytest.raises(IroiroError) as exc_info:
        load_config(missing_path)

    msg = str(exc_info.value)
    # メッセージにパス名が含まれる（ユーザーへの手がかり）
    assert "missing.toml" in msg, (
        f"エラーメッセージにファイル名が含まれる: 実際 {msg!r}"
    )


# ===========================================================================
# T93: 無効 TOML（シンタックスエラー） → IroiroError
# ===========================================================================

def test_T93_invalid_toml_syntax_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T93: 無効な TOML（シンタックスエラー）の場合、IroiroError を投げる。

    tomllib のパースエラーを IroiroError でラップして投げる。
    エラーメッセージにパースエラーの詳細が含まれること。
    """
    shutil.copy(FIXTURES_DIR / "iroiro_broken.toml", tmp_path / "iroiro.toml")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(IroiroError) as exc_info:
        load_config(None)

    # パースエラーであることがメッセージから分かる（詳細は tomllib 依存）
    msg = str(exc_info.value)
    assert len(msg) > 0, "エラーメッセージが空でない"


# ===========================================================================
# T94: [iroiro] テーブル無し（[other] だけ） → IroiroError（v0.5）
# ===========================================================================

def test_T94_no_iroiro_section_returns_empty_dict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T94: ``[iroiro]`` セクションが存在しない場合 ``IroiroError``（v0.5）。

    v0.5（Plan 005 §2.2 / §4.5 T149）での破壊的変更: ``[iroiro]`` セクション自体が
    存在しない toml は ``IroiroError``（v0.4 までは ``{}`` 返却だったが、3 新項目が
    必須のため空 ``{}`` では要件を満たせない）。警告ログも出ない（エラーで停止）。

    ※ 同契約は ``test_T149`` でも検証されている。T94 は歴史的経緯で v0.5 挙動に更新。
    """
    shutil.copy(FIXTURES_DIR / "iroiro_other_only.toml", tmp_path / "iroiro.toml")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(IroiroError) as exc_info:
        load_config(None)

    msg = str(exc_info.value)
    assert "iroiro" in msg.lower(), (
        f"エラーメッセージに [iroiro] セクションへの言及がある: 実際 {msg!r}"
    )


# ===========================================================================
# T95: [iroiro] がテーブルでない（iroiro = "x"） → IroiroError
# ===========================================================================

def test_T95_iroiro_not_table_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T95: [iroiro] がテーブルでなくスカラー値の場合、IroiroError を投げる。

    `iroiro = "x"` のような書き方は [iroiro] テーブルではない。
    §4.5.2: [iroiro] がテーブルでない場合は IroiroError → exit code 2。
    """
    shutil.copy(FIXTURES_DIR / "iroiro_not_table.toml", tmp_path / "iroiro.toml")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(IroiroError):
        load_config(None)


# ===========================================================================
# T96: 型エラー（timeout = "abc"） → IroiroError
# ===========================================================================

def test_T96_type_error_string_for_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T96: timeout に文字列を指定した場合、型エラーで IroiroError。

    timeout は float を要求。文字列 "abc" は型不一致。
    §4.5.2: `<key> must be <expected>, got <actual>` エラー。
    """
    (tmp_path / "iroiro.toml").write_text(
        '[iroiro]\ntimeout = "abc"\n', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(IroiroError):
        load_config(None)


# ===========================================================================
# T97: 値域エラー（timeout = -1） → IroiroError
# ===========================================================================

def test_T97_range_error_negative_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T97: timeout に負数を指定した場合、値域エラーで IroiroError。

    timeout は > 0 を要求。0 以下（負数・ゼロ）は値域外。
    §4.5.2: `<key> must be <range>, got <value>` エラー。
    """
    (tmp_path / "iroiro.toml").write_text(
        '[iroiro]\ntimeout = -1\n', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(IroiroError):
        load_config(None)


# ===========================================================================
# T98: 未知キー + 既知キー混在 → 警告ログ・既知キーだけ反映
# ===========================================================================

def test_T98_unknown_key_warns_and_keeps_known(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """T98: 未知キー混在時は警告ログを出しつつ既知キーだけ反映する。

    §4.5.2 / §7.2: 未知キーは例外送出せず、警告ログ（WARNING）を出して
    無視する。既知キーは返り値 dict に含める。前方互換のため。
    """
    shutil.copy(FIXTURES_DIR / "iroiro_unknown_key.toml", tmp_path / "iroiro.toml")
    monkeypatch.chdir(tmp_path)

    with caplog.at_level(logging.WARNING):
        result = load_config(None)

    # 既知キーは反映される
    assert result.get("api_base") == "http://known:8080/v1", (
        f"既知キーは反映される: 実際 {result!r}"
    )
    # 未知キーは返り値に含まれない（無視される）
    assert "unknown_key" not in result, (
        f"未知キーは返り値に含まれない: 実際 {result!r}"
    )
    assert "another_unknown" not in result

    # 警告ログが少なくとも1件出る（未知キー名が含まれる）
    warning_msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warning_msgs) > 0, (
        "未知キーに対する警告ログが出る"
    )
    # 警告メッセージに未知キー名が言及されている
    all_log_text = " ".join(warning_msgs)
    assert "unknown_key" in all_log_text or "another_unknown" in all_log_text, (
        f"警告ログに未知キー名が含まれる: 実際 {warning_msgs!r}"
    )


# ===========================================================================
# T99: bool を数値フィールドに（timeout = true） → IroiroError
# ===========================================================================

def test_T99_bool_for_numeric_field_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T99: bool を数値フィールドに割り当てた場合、型エラーで IroiroError。

    §4.5.1: Python では ``bool ⊂ int``（``isinstance(True, int) == True``）。
    ``timeout = true`` のような書き間違いを数値として受け入れてしまう事故を
    防ぐため、``isinstance(v, bool)`` なら型エラーとして拒否する。
    """
    (tmp_path / "iroiro.toml").write_text(
        '[iroiro]\ntimeout = true\n', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(IroiroError) as exc_info:
        load_config(None)

    # bool 拒否であることがメッセージから分かる（実装依存の詳細は問わない）
    msg = str(exc_info.value).lower()
    assert "timeout" in msg or "bool" in msg, (
        f"エラーメッセージにキー名または bool が言及される: 実際 {msg!r}"
    )


# ===========================================================================
# T100: 文字列フィールドに int（api_base = 123） → IroiroError
# ===========================================================================

def test_T100_int_for_string_field_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T100: 文字列フィールドに int を指定した場合、型エラーで IroiroError。

    api_base は str を要求。int 123 は型不一致。
    §4.5.2: `<key> must be <expected>, got <actual>` エラー。
    """
    (tmp_path / "iroiro.toml").write_text(
        '[iroiro]\napi_base = 123\n', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(IroiroError):
        load_config(None)


# ===========================================================================
# T101: api_base = "" → IroiroError（値域エラー）
# ===========================================================================

def test_T101_empty_api_base_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T101: api_base に空文字を指定した場合、値域エラーで IroiroError。

    §4.5.1: api_base は非空を要求。``""`` は値域エラー。
    ※ api_key の空文字は許可されるが、api_base の空文字は拒否される点に注意。
    """
    shutil.copy(FIXTURES_DIR / "iroiro_empty_base.toml", tmp_path / "iroiro.toml")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(IroiroError):
        load_config(None)


# ===========================================================================
# T102: max_chars = 0 → 正当値として受理
# ===========================================================================

def test_T102_max_chars_zero_accepted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T102: max_chars = 0 は正当値として受理される（境界値検証）。

    §4.5.1: max_chars の値域は ``>= 0``。0 は「全件スキップ」の正当値
    （``len(source) > 0`` が常に真のため、max_chars=0 だと全件スキップされる）。
    ``>= 1`` でなく ``>= 0`` であることが重要。
    """
    shutil.copy(FIXTURES_DIR / "iroiro_max_chars_zero.toml", tmp_path / "iroiro.toml")
    monkeypatch.chdir(tmp_path)

    result = load_config(None)

    assert "max_chars" in result, "max_chars は記述されているので dict に含まれる"
    assert result["max_chars"] == 0, (
        f"max_chars = 0 は正当値として受理: 実際 {result.get('max_chars')!r}"
    )


# ===========================================================================
# v0.4: T110-T113 — retry_failed 設定の検証（Plan 004 §4.4 / §6.1）
#
# retry_failed は厳格 bool（``isinstance(v, bool)``）のみ許可:
#   - ``true``  / ``false`` → そのまま bool として返す
#   - ``1`` / ``0``（int）  → 拒否（Python ``bool ⊂ int`` 事故防止）
#   - ``"true"`` / ``"false"``（文字列） → 拒否
#
# デフォルト False（後方互換・v0.3 までと同じ挙動）。優先順位は Plan 003 と同じ:
#   CLI ``--retry-failed`` / ``--no-retry-failed`` ＞ iroiro.toml ＞ 内蔵 False
#
# ※ 他の数値フィールド（timeout / concurrency / max_chars）は bool を拒否するが、
#    retry_failed は bool を **要求** する点が逆（同じ「厳格 bool」思想の両面）。
# ===========================================================================


def test_T110_retry_failed_true(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T110: ``retry_failed = true`` → ``{"retry_failed": True}``（v0.5 で 3 新項目追加）。

    Plan 004 §4.4: 厳格 bool のみ許可。``true`` は ``True`` として反映される。
    resume 時に failed エントリを state=pending に戻す（再翻訳対象）。

    v0.5（Plan 005 §2.2）: ``iroiro_retry_true.toml`` に 3 新項目（``system_prompt``
    / ``reject_phrases`` / ``[iroiro.rec_hints]``）が追記されたため、result dict にも
    含まれる。``reject_phrases`` は ``frozenset[str]`` に normalize。
    """
    shutil.copy(FIXTURES_DIR / "iroiro_retry_true.toml", tmp_path / "iroiro.toml")
    monkeypatch.chdir(tmp_path)

    result = load_config(None)

    assert result["retry_failed"] is True, (
        f"retry_failed = true が bool True として返る: 実際 {result.get('retry_failed')!r}"
    )
    # v0.5 の 3 新項目（fixture に含まれるため反映）
    assert "system_prompt" in result
    assert isinstance(result["system_prompt"], str)
    assert isinstance(result["reject_phrases"], frozenset)
    assert result["reject_phrases"] == frozenset({"了解", "翻訳します"})
    assert result["rec_hints"] == {"MGEF:FULL": "魔法の効果名。"}


def test_T111_retry_failed_false(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T111: ``retry_failed = false`` → ``{"retry_failed": False}``（v0.5 で 3 新項目追加）。

    Plan 004 §4.4: ``false`` は ``False`` として反映される。デフォルト（未記述）と
    同じ値だが、明示的に記述された場合は dict のキーに含まれる点が異なる
    （呼出側の ``_resolve`` で False が明示採用される）。

    v0.5（Plan 005 §2.2）: ``iroiro_retry_false.toml`` に 3 新項目が追記されたため、
    result dict にも含まれる。``reject_phrases`` は ``frozenset[str]`` に normalize。
    """
    shutil.copy(FIXTURES_DIR / "iroiro_retry_false.toml", tmp_path / "iroiro.toml")
    monkeypatch.chdir(tmp_path)

    result = load_config(None)

    assert result["retry_failed"] is False, (
        f"retry_failed = false が bool False として返る: 実際 {result.get('retry_failed')!r}"
    )
    # v0.5 の 3 新項目（fixture に含まれるため反映）
    assert "system_prompt" in result
    assert isinstance(result["system_prompt"], str)
    assert isinstance(result["reject_phrases"], frozenset)
    assert result["reject_phrases"] == frozenset({"了解", "翻訳します"})
    assert result["rec_hints"] == {"MGEF:FULL": "魔法の効果名。"}


def test_T112_retry_failed_string_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T112: ``retry_failed = "true"``（文字列） → ``IroiroError``。

    Plan 004 §4.4: 厳格 bool のみ許可。TOML の文字列 ``"true"`` は bool でないため
    型エラーで拒否される（``"false"`` / ``"yes"`` / ``"on"`` 等も同様）。
    ユーザーが YAML 等と勘違いして文字列で書く事故を防ぐ。
    """
    (tmp_path / "iroiro.toml").write_text(
        '[iroiro]\nretry_failed = "true"\n', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(IroiroError) as exc_info:
        load_config(None)

    # エラーメッセージにキー名または想定型が言及される（実装依存の詳細は問わない）
    msg = str(exc_info.value).lower()
    assert "retry_failed" in msg or "bool" in msg, (
        f"エラーメッセージにキー名または bool が言及される: 実際 {msg!r}"
    )


def test_T113_retry_failed_int_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T113: ``retry_failed = 1``（int） → ``IroiroError``（``bool ⊂ int`` 事故防止）。

    Plan 004 §4.4: Python では ``isinstance(True, int) == True`` だが
    ``isinstance(1, bool) == False``。``retry_failed = 1`` のような書き間違いを
    暗黙に受け入れると、``if retry_failed:`` で truthy 扱いされて **意図せず**
    全 failed エントリが再試行対象に変わる事故に繋がるため、厳格 bool 以外は拒否する。
    他の数値フィールド（timeout 等）が bool を拒否するのと対称的な検証。
    """
    (tmp_path / "iroiro.toml").write_text(
        '[iroiro]\nretry_failed = 1\n', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(IroiroError) as exc_info:
        load_config(None)

    msg = str(exc_info.value).lower()
    assert "retry_failed" in msg or "bool" in msg, (
        f"エラーメッセージにキー名または bool が言及される: 実際 {msg!r}"
    )


# ===========================================================================
# v0.5: T132-T142 — LLM 挙動中核（system_prompt / reject_phrases / rec_hints）
# の toml 化（Plan 005 §4.1 / §2.4-2.8）
#
# Plan 005 §2.1-2.2: コードから _SYSTEM_PROMPT / REJECT_PHRASES / _REC_HINTS
# 定数を完全削除し、iroiro.toml で必須指定する（案 α）。本セクションは
# load_config がこれら 3 新項目を正しく検証・normalize することを検証する。
#
# 検証ルール（Plan 005 §2.5）:
#
# ===================  =============================  ==================================
# キー                制約                            備考
# ===================  =============================  ==================================
# ``system_prompt``   非空 str・strip 後も非空       ``""`` / ``"   "`` 拒否
# ``reject_phrases``  ``list[str]``・各要素非空 str   ``bool`` 拒否・空リスト ``[]`` は許可・
#                                                       重複は ``frozenset`` 化で除去
# ``[iroiro.rec_hints]`` ``dict[str, str]``・各キー非空 テーブル自体は必須・空 ``{}`` は許可・
#                                                       各値非空 str・``bool`` 拒否
# ===================  =============================  ==================================
#
# ※ WP-1 段階では load_config に 3 新項目の検証が未実装のため、本セクションの
#    テストは全て red（WP-2 完了後に green 化）。既存テスト（T88-T113）は現状維持。
#
# ※ TOML 構文の鉄則（B5 指摘）: [iroiro.rec_hints] 配下のキーは ``:`` を含むため
#    必ず quoted key（``"MGEF:FULL"``）で書く。本セクションの fixtures は全て
#    quoted で統一している。
# ===========================================================================


# ---------------------------------------------------------------------------
# T132: system_prompt は非空 str のみ受入
# ---------------------------------------------------------------------------

def test_T132_system_prompt_type_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T132: ``system_prompt`` は非空 ``str``（strip 後も非空）のみ受入。

    拒否ケース:
      - ``""``（空文字列）
      - ``"   "``（空白のみ）
      - ``123``（int）
      - ``True``（bool・``bool ⊂ str`` ではないが Python では厳格に拒否）
      - キー自体が存在しない（→ T133 で検証）

    受入ケース:
      - ``"Skyrim MOD の英文を日本語に翻訳する。"``（非空 str・正常系）

    Plan 005 §2.5: ``""`` / ``"   "`` 拒否・``int`` / ``bool`` 拒否。
    """
    # 受入ケース（正常系・v0.5 フル設定の fixture を使用）
    shutil.copy(FIXTURES_DIR / "iroiro_v05_full.toml", tmp_path / "iroiro.toml")
    monkeypatch.chdir(tmp_path)
    result = load_config(None)
    assert isinstance(result.get("system_prompt"), str), (
        f"system_prompt は str として返る: 実際 {type(result.get('system_prompt'))!r}"
    )
    assert result["system_prompt"].strip() != "", (
        "system_prompt は strip 後も非空"
    )

    # 拒否ケース: 空文字列
    (tmp_path / "iroiro.toml").write_text(
        '[iroiro]\nsystem_prompt = ""\n'
        'reject_phrases = ["了解"]\n'
        '[iroiro.rec_hints]\n"MGEF:FULL" = "x"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    with pytest.raises(IroiroError):
        load_config(None)

    # 拒否ケース: 空白のみ
    (tmp_path / "iroiro.toml").write_text(
        '[iroiro]\nsystem_prompt = "   "\n'
        'reject_phrases = ["了解"]\n'
        '[iroiro.rec_hints]\n"MGEF:FULL" = "x"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    with pytest.raises(IroiroError):
        load_config(None)

    # 拒否ケース: int
    (tmp_path / "iroiro.toml").write_text(
        '[iroiro]\nsystem_prompt = 123\n'
        'reject_phrases = ["了解"]\n'
        '[iroiro.rec_hints]\n"MGEF:FULL" = "x"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    with pytest.raises(IroiroError):
        load_config(None)

    # 拒否ケース: bool
    (tmp_path / "iroiro.toml").write_text(
        '[iroiro]\nsystem_prompt = true\n'
        'reject_phrases = ["了解"]\n'
        '[iroiro.rec_hints]\n"MGEF:FULL" = "x"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    with pytest.raises(IroiroError):
        load_config(None)


# ---------------------------------------------------------------------------
# T133: system_prompt 必須（toml に無いと IroiroError）
# ---------------------------------------------------------------------------

def test_T133_system_prompt_required(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T133: ``system_prompt`` が toml に存在しない場合 ``IroiroError``。

    Plan 005 §2.2 / §2.8: ``system_prompt`` は必須。欠損時のエラーメッセージは
    ``"[iroiro] system_prompt is required in <path>"``。
    """
    shutil.copy(
        FIXTURES_DIR / "iroiro_v05_missing_prompt.toml", tmp_path / "iroiro.toml"
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(IroiroError) as exc_info:
        load_config(None)

    msg = str(exc_info.value)
    assert "system_prompt" in msg, (
        f"エラーメッセージに system_prompt が言及される: 実際 {msg!r}"
    )


# ---------------------------------------------------------------------------
# T134: reject_phrases は list[str] 受入・各要素非空・bool 拒否
# ---------------------------------------------------------------------------

def test_T134_reject_phrases_type_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T134: ``reject_phrases`` は ``list[str]``・各要素非空 ``str``・``bool`` 拒否。

    Plan 005 §2.5: ``bool ⊂ int`` 事故防止のため ``[True]`` のような要素は
    厳格に拒否する（``isinstance(True, bool)`` なら即座に ``IroiroError``）。
    ``reject_phrases = "了解"``（文字列スカラー）も ``list`` でないため拒否。
    """
    # 受入ケース（正常系）
    shutil.copy(FIXTURES_DIR / "iroiro_v05_full.toml", tmp_path / "iroiro.toml")
    monkeypatch.chdir(tmp_path)
    result = load_config(None)
    rp = result.get("reject_phrases")
    # list[str] または frozenset[str]（normalize 済み）のいずれか
    assert rp is not None, "reject_phrases は必須・dict に含まれる"
    assert hasattr(rp, "__iter__"), f"reject_phrases は iterable: 実際 {type(rp)!r}"

    # 拒否ケース: 文字列スカラー（list でない）
    (tmp_path / "iroiro.toml").write_text(
        '[iroiro]\nsystem_prompt = "x"\n'
        'reject_phrases = "了解"\n'
        '[iroiro.rec_hints]\n"MGEF:FULL" = "x"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    with pytest.raises(IroiroError):
        load_config(None)

    # 拒否ケース: bool を含むリスト
    (tmp_path / "iroiro.toml").write_text(
        '[iroiro]\nsystem_prompt = "x"\n'
        'reject_phrases = [true]\n'
        '[iroiro.rec_hints]\n"MGEF:FULL" = "x"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    with pytest.raises(IroiroError):
        load_config(None)

    # 拒否ケース: 空要素を含むリスト
    (tmp_path / "iroiro.toml").write_text(
        '[iroiro]\nsystem_prompt = "x"\n'
        'reject_phrases = ["了解", ""]\n'
        '[iroiro.rec_hints]\n"MGEF:FULL" = "x"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    with pytest.raises(IroiroError):
        load_config(None)

    # 拒否ケース: int を含むリスト
    (tmp_path / "iroiro.toml").write_text(
        '[iroiro]\nsystem_prompt = "x"\n'
        'reject_phrases = [123]\n'
        '[iroiro.rec_hints]\n"MGEF:FULL" = "x"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    with pytest.raises(IroiroError):
        load_config(None)


# ---------------------------------------------------------------------------
# T135: reject_phrases 重複要素は frozenset 化で除去
# ---------------------------------------------------------------------------

def test_T135_reject_phrases_dedup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T135: ``reject_phrases`` の重複要素は normalize で除去される。

    Plan 005 §2.5 / WP-2 §2: ``reject_phrases`` は ``frozenset[str]`` に
    normalize される（重複除去）。``["了解", "了解"]`` は 1 件になる。
    """
    (tmp_path / "iroiro.toml").write_text(
        '[iroiro]\n'
        'system_prompt = "x"\n'
        'reject_phrases = ["了解", "了解", "翻訳します", "翻訳します"]\n'
        'skip_records = []\n'
        '[iroiro.rec_hints]\n"MGEF:FULL" = "x"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    result = load_config(None)
    rp = result["reject_phrases"]
    # frozenset または list・いずれにせよ重複は除去されている
    rp_set = set(rp) if not isinstance(rp, (frozenset, set)) else rp
    assert rp_set == {"了解", "翻訳します"}, (
        f"重複が除去されて 2 件になる: 実際 {rp!r}"
    )


# ---------------------------------------------------------------------------
# T136: reject_phrases 空リスト [] は許可（メタ返答チェック無効化）
# ---------------------------------------------------------------------------

def test_T136_reject_phrases_empty_list_allowed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T136: ``reject_phrases = []``（空リスト）は正当値として許可される。

    Plan 005 §2.2 / §2.5: ユーザーが意図的にメタ返答チェックを無効化するケース。
    ``[iroiro.rec_hints]`` とは異なり、空リスト ``[]`` も許容される。
    """
    shutil.copy(
        FIXTURES_DIR / "iroiro_v05_empty_reject.toml", tmp_path / "iroiro.toml"
    )
    monkeypatch.chdir(tmp_path)

    result = load_config(None)
    # 空リスト（または空 frozenset）として返る・エラーにならない
    rp = result["reject_phrases"]
    assert len(rp) == 0, f"reject_phrases = [] は空として返る: 実際 {rp!r}"


# ---------------------------------------------------------------------------
# T137: reject_phrases 必須（toml に無いと IroiroError）
# ---------------------------------------------------------------------------

def test_T137_reject_phrases_required(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T137: ``reject_phrases`` が toml に存在しない場合 ``IroiroError``。

    Plan 005 §2.2 / §2.8: ``reject_phrases`` は必須。欠損時のエラーメッセージは
    ``"[iroiro] reject_phrases is required in <path>"``。
    """
    shutil.copy(
        FIXTURES_DIR / "iroiro_v05_missing_reject.toml", tmp_path / "iroiro.toml"
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(IroiroError) as exc_info:
        load_config(None)

    msg = str(exc_info.value)
    assert "reject_phrases" in msg, (
        f"エラーメッセージに reject_phrases が言及される: 実際 {msg!r}"
    )


# ---------------------------------------------------------------------------
# T138: [iroiro.rec_hints] テーブル必須（行自体が無いと IroiroError）
# ---------------------------------------------------------------------------

def test_T138_rec_hints_table_required(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T138: ``[iroiro.rec_hints]`` テーブル自体が存在しない場合 ``IroiroError``。

    Plan 005 §2.2 / §2.8: テーブル自体は必須（``[iroiro.rec_hints]`` ヘッダが
    toml 上に存在するか、``data["iroiro"]["rec_hints"]`` が ``None`` でないか）。
    空テーブル ``{}`` は許可されるが（T139）、テーブル自体の欠損はエラー。
    """
    shutil.copy(
        FIXTURES_DIR / "iroiro_v05_missing_rec_hints.toml",
        tmp_path / "iroiro.toml",
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(IroiroError) as exc_info:
        load_config(None)

    msg = str(exc_info.value)
    assert "rec_hints" in msg, (
        f"エラーメッセージに rec_hints が言及される: 実際 {msg!r}"
    )


# ---------------------------------------------------------------------------
# T139: [iroiro.rec_hints] 空テーブル {} は許可（REC ヒント無効化）
# ---------------------------------------------------------------------------

def test_T139_rec_hints_empty_table_allowed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T139: ``[iroiro.rec_hints]`` 空テーブル ``{}`` は正当値として許可される。

    Plan 005 §2.2 / §2.5: ユーザーが意図的に REC ヒントを無効化するケース。
    ``[iroiro.rec_hints]`` ヘッダのみで中身が無い場合は空 dict として返る。
    """
    (tmp_path / "iroiro.toml").write_text(
        '[iroiro]\n'
        'system_prompt = "x"\n'
        'reject_phrases = ["了解"]\n'
        'skip_records = []\n'
        '[iroiro.rec_hints]\n',  # ヘッダのみ・中身無し
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    result = load_config(None)
    rh = result["rec_hints"]
    assert rh == {}, f"空テーブルは空 dict として返る: 実際 {rh!r}"


# ---------------------------------------------------------------------------
# T140: [iroiro.rec_hints] 各キー非空・各値非空 str・bool 拒否
# ---------------------------------------------------------------------------

def test_T140_rec_hints_value_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T140: ``[iroiro.rec_hints]`` の各値は非空 ``str``・``bool`` 拒否。

    Plan 005 §2.5: 厳格型検証（``isinstance(v, bool)`` なら即座に ``IroiroError``）。
    各値 ``""``（空文字列）・``123``（int）・``true``（bool）は拒否される。
    """
    # 拒否ケース: 値が空文字列
    (tmp_path / "iroiro.toml").write_text(
        '[iroiro]\n'
        'system_prompt = "x"\n'
        'reject_phrases = ["了解"]\n'
        '[iroiro.rec_hints]\n"MGEF:FULL" = ""\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    with pytest.raises(IroiroError):
        load_config(None)

    # 拒否ケース: 値が int
    (tmp_path / "iroiro.toml").write_text(
        '[iroiro]\n'
        'system_prompt = "x"\n'
        'reject_phrases = ["了解"]\n'
        '[iroiro.rec_hints]\n"MGEF:FULL" = 123\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    with pytest.raises(IroiroError):
        load_config(None)

    # 拒否ケース: 値が bool
    (tmp_path / "iroiro.toml").write_text(
        '[iroiro]\n'
        'system_prompt = "x"\n'
        'reject_phrases = ["了解"]\n'
        '[iroiro.rec_hints]\n"MGEF:FULL" = true\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    with pytest.raises(IroiroError):
        load_config(None)


# ---------------------------------------------------------------------------
# T141: [iroiro.rec_hints] 未知 REC キー許可（quoted key 必須）
# ---------------------------------------------------------------------------

def test_T141_rec_hints_unknown_rec_allowed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """T141: ``[iroiro.rec_hints]`` に未知の REC キー（``"FOO:BAR"``）は許可される。

    Plan 005 §2.5: 将来の Skyrim REC 型拡張のため、未知の REC キーは ``WARNING``
    ログ無しで許可される（``"FOO:BAR" = "..."``・quoted key 必須）。
    """
    (tmp_path / "iroiro.toml").write_text(
        '[iroiro]\n'
        'system_prompt = "x"\n'
        'reject_phrases = ["了解"]\n'
        'skip_records = []\n'
        '[iroiro.rec_hints]\n'
        '"MGEF:FULL" = "魔法の効果名。"\n'
        '"FOO:BAR" = "未知の REC 型のヒント。"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    with caplog.at_level(logging.WARNING):
        result = load_config(None)

    rh = result["rec_hints"]
    assert "FOO:BAR" in rh, (
        f"未知 REC キー FOO:BAR は許可される: 実際 {rh!r}"
    )
    assert rh["FOO:BAR"] == "未知の REC 型のヒント。"


# ---------------------------------------------------------------------------
# T142: iroiro.toml ファイル無し時の load_config（v0.5 では IroiroError）
# ---------------------------------------------------------------------------

def test_T142_no_config_file_raises_in_v05(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T142: ``iroiro.toml`` ファイル無し（cwd に存在しない）場合 ``IroiroError``。

    Plan 005 §2.2 / §2.9: ``iroiro.toml`` は ``--dry-run`` 含む全操作で必須。
    v0.4 までは ``{}`` 返却（後方互換）だったが、v0.5 では ``IroiroError`` に変更
    （案 α の一貫性・LLM 挙動中核 3 項目が必須のため空 ``{}`` では要件を満たせない）。

    既存 T88 は v0.4 挙動（``{}`` 返却）を検証しているが、WP-2 で T88 も更新される。
    本 T142 は v0.5 の新しい契約を検証する。
    """
    monkeypatch.chdir(tmp_path)  # tmp_path は空なので iroiro.toml は見つからない

    with pytest.raises(IroiroError) as exc_info:
        load_config(None)

    # エラーメッセージに手がかり（cp iroiro.toml.example 等）が含まれることを推奨
    # するが、必須ではない。少なくとも "iroiro.toml" への言及はあるはず。
    msg = str(exc_info.value)
    assert "iroiro.toml" in msg or "config" in msg.lower(), (
        f"エラーメッセージに iroiro.toml への言及がある: 実際 {msg!r}"
    )


# ===========================================================================
# v0.5: T149-T153, T155-T157 — Codex review 指摘の追加テスト（Plan 005 §4.5）
#
# Plan 005 §4.5 Codex review 1-3回目指摘の追加テスト群。§4.1 T132-T142 の
# 不足ケースを補完する。
# ===========================================================================


# ---------------------------------------------------------------------------
# T149: [iroiro] セクション自体が無い toml → IroiroError（B3・案 α の一貫性）
# ---------------------------------------------------------------------------

def test_T149_no_iroiro_section_raises_in_v05(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T149: ``[iroiro]`` セクション自体が存在しない toml → ``IroiroError``。

    Plan 005 §2.2 / §2.8 / §4.5 T149: v0.4 までは ``{}`` 返却（T94）だったが、
    v0.5 では ``IroiroError``（案 α の一貫性・3 新項目が必須のため空 ``{}`` では
    要件を満たせない・B3）。既存 T94 は v0.4 挙養を検証しているが、WP-2 で
    T94 も更新される。本 T149 は v0.5 の新しい契約を検証する。
    """
    shutil.copy(FIXTURES_DIR / "iroiro_other_only.toml", tmp_path / "iroiro.toml")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(IroiroError) as exc_info:
        load_config(None)

    msg = str(exc_info.value)
    assert "iroiro" in msg.lower(), (
        f"エラーメッセージに [iroiro] セクションへの言及がある: 実際 {msg!r}"
    )


# ---------------------------------------------------------------------------
# T150: 未知の [iroiro] セクション内キー → WARNING のみ・例外送出しない
# ---------------------------------------------------------------------------

def test_T150_unknown_iroiro_key_warns_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """T150: ``[iroiro]`` セクション内の未知キー（``unknown_key`` 等）は WARNING のみ。

    Plan 005 §2.5: v0.3/v0.4 と同じ（``WARNING`` ログのみ・例外送出しない）。
    ※ top-level の ``[other]`` テーブルは別物・v0.5 では ``[iroiro]`` 必須なので
       ``[other]`` 単独だと ``[iroiro]`` 欠損エラーになる（T149 で検証）。
    """
    (tmp_path / "iroiro.toml").write_text(
        '[iroiro]\n'
        'system_prompt = "x"\n'
        'reject_phrases = ["了解"]\n'
        'skip_records = []\n'
        'unknown_key = "this should be ignored with a warning"\n'
        '[iroiro.rec_hints]\n"MGEF:FULL" = "x"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    with caplog.at_level(logging.WARNING):
        result = load_config(None)

    # 正常系の 3 項目は反映される
    assert "system_prompt" in result
    assert "reject_phrases" in result
    assert "rec_hints" in result
    # 未知キーは返り値に含まれない
    assert "unknown_key" not in result

    # 警告ログが少なくとも1件出る
    warning_msgs = [
        r.getMessage() for r in caplog.records
        if r.levelno >= logging.WARNING
    ]
    assert len(warning_msgs) > 0, "未知キーに対する警告ログが出る"
    all_log_text = " ".join(warning_msgs)
    assert "unknown_key" in all_log_text, (
        f"警告ログに未知キー名が含まれる: 実際 {warning_msgs!r}"
    )


# ---------------------------------------------------------------------------
# T151: [iroiro.rec_hints] に未知の REC キー（quoted）→ WARNING 無しで許可
# ---------------------------------------------------------------------------

def test_T151_rec_hints_unknown_rec_no_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """T151: ``[iroiro.rec_hints]`` の未知 REC キーは WARNING 無しで許可（T141 から分離）。

    Plan 005 §4.5 T151: T141 は「許可されること」を検証するが、本 T151 は
    「``WARNING`` ログが出ないこと」を独立して検証する。将来の Skyrim REC 型拡張のため。
    """
    (tmp_path / "iroiro.toml").write_text(
        '[iroiro]\n'
        'system_prompt = "x"\n'
        'reject_phrases = ["了解"]\n'
        'skip_records = []\n'
        '[iroiro.rec_hints]\n'
        '"MGEF:FULL" = "魔法の効果名。"\n'
        '"FOO:BAR" = "未知の REC 型のヒント。"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    with caplog.at_level(logging.WARNING):
        result = load_config(None)

    rh = result["rec_hints"]
    assert "FOO:BAR" in rh

    # ``FOO:BAR`` に対する WARNING は出ない（未知 REC キーは黙って許可）
    warning_msgs = [
        r.getMessage() for r in caplog.records
        if r.levelno >= logging.WARNING
    ]
    for w in warning_msgs:
        assert "FOO:BAR" not in w, (
            f"未知 REC キー FOO:BAR への WARNING は出ない: 実際 {warning_msgs!r}"
        )


# ---------------------------------------------------------------------------
# T152: rec_hints の形エラー（テーブルでなく文字列）→ IroiroError
# ---------------------------------------------------------------------------

def test_T152_rec_hints_wrong_shape_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T152: ``rec_hints`` がテーブルでなくスカラー値（``rec_hints = "x"``）→ ``IroiroError``。

    Plan 005 §2.8: ``"[iroiro.rec_hints] must be a table, got <type> in <path>"``。
    ``rec_hints = "x"`` のようにテーブルでなく文字列を割り当てた場合の検証。
    """
    (tmp_path / "iroiro.toml").write_text(
        '[iroiro]\n'
        'system_prompt = "x"\n'
        'reject_phrases = ["了解"]\n'
        'rec_hints = "not-a-table"\n',  # テーブルでなく文字列
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(IroiroError) as exc_info:
        load_config(None)

    msg = str(exc_info.value).lower()
    assert "rec_hints" in msg or "table" in msg, (
        f"エラーメッセージに rec_hints または table が言及される: 実際 {msg!r}"
    )


# ---------------------------------------------------------------------------
# T153: [iroiro.rec_hints] の値が bool（"MGEF:FULL" = true）→ IroiroError
# ---------------------------------------------------------------------------

def test_T153_rec_hints_bool_value_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T153: ``[iroiro.rec_hints]`` の値が ``bool``（``"MGEF:FULL" = true``）→ ``IroiroError``。

    Plan 005 §2.5: 厳格 ``str`` 検証。``bool ⊂ int`` 事故防止のため
    ``isinstance(v, bool)`` なら即座に ``IroiroError``。
    ※ T140 でも bool 拒否を検証しているが、T153 は Codex review 指摘で独立テスト化。
    """
    (tmp_path / "iroiro.toml").write_text(
        '[iroiro]\n'
        'system_prompt = "x"\n'
        'reject_phrases = ["了解"]\n'
        '[iroiro.rec_hints]\n"MGEF:FULL" = true\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(IroiroError):
        load_config(None)


# ---------------------------------------------------------------------------
# T155: iroiro.toml.example が tomllib で parse でき、load_config で通る
# ---------------------------------------------------------------------------

def test_T155_example_file_parses_and_loads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """T155: ``iroiro.toml.example`` が ``tomllib`` で parse でき ``load_config`` で通る。

    Plan 005 §4.5 T155 / R2: ``:`` bare key 問題の回帰防止（Codex review 2回目指摘）。
    ``iroiro.toml.example`` は ``cp`` で ``iroiro.toml`` にコピーして使われるため、
    ``tomllib`` で parse error にならないこと・3 新項目が含まれていること・
    ``load_config`` が通ることが必須。

    ※ WP-1 段階では ``iroiro.toml.example`` が v0.3/v0.4 形式（3 新項目無し）のため
       本テストは red。WP-2 で ``iroiro.toml.example`` に 3 新項目が追加された後、
       green 化する。
    """
    import tomllib

    # リポジトリルートの iroiro.toml.example を特定
    example_path = Path(__file__).resolve().parents[1] / "iroiro.toml.example"
    assert example_path.is_file(), f"iroiro.toml.example が存在する: {example_path}"

    # 1. tomllib で parse できる（``:`` bare key 問題の回帰防止）
    with example_path.open("rb") as f:
        data = tomllib.load(f)  # parse error を起こさないこと

    # 2. v0.5 の 3 新項目が example に含まれる（cp してそのまま使える状態）
    iroiro_section = data.get("iroiro", {})
    assert "system_prompt" in iroiro_section, (
        "iroiro.toml.example に system_prompt が含まれる（v0.5 必須項目）"
    )
    assert "reject_phrases" in iroiro_section, (
        "iroiro.toml.example に reject_phrases が含まれる（v0.5 必須項目）"
    )
    assert "rec_hints" in iroiro_section, (
        "iroiro.toml.example に [iroiro.rec_hints] が含まれる（v0.5 必須項目）"
    )

    # 3. load_config が例外を投げない（``--config`` 経由で読む）
    # tmp_path にコピーして読み込む（cwd を汚さないため）
    tmp_config = tmp_path / "from_example.toml"
    shutil.copy(example_path, tmp_config)
    result = load_config(tmp_config)  # 例外が投げられなければ OK
    assert "system_prompt" in result
    assert "reject_phrases" in result
    assert "rec_hints" in result


# ---------------------------------------------------------------------------
# T156: [iroiro.rec_hints] の quoted REC key が dict["MGEF:FULL"] になる
# ---------------------------------------------------------------------------

def test_T156_rec_hints_quoted_key_dict_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T156: ``[iroiro.rec_hints]`` の quoted REC key（``"MGEF:FULL"``）が
    ``dict["MGEF:FULL"]`` としてアクセス可能になることの検証。

    Plan 005 §4.5 T156 / B5: ``:`` を含むキーは quoted key で書く必要があるが、
    ``tomllib`` は ``"MGEF:FULL"``
    の quoted を外して ``"MGEF:FULL"`` という文字列キーとして parse する。
    これが ``dict["MGEF:FULL"]`` でアクセスできることの回帰防止。
    """
    shutil.copy(FIXTURES_DIR / "iroiro_v05_full.toml", tmp_path / "iroiro.toml")
    monkeypatch.chdir(tmp_path)

    result = load_config(None)
    rh = result["rec_hints"]
    # quoted key "MGEF:FULL" がそのまま dict のキーになる（``:`` を含む）
    assert "MGEF:FULL" in rh, (
        f"'MGEF:FULL' キーが dict に存在する: 実際 {list(rh.keys())!r}"
    )
    assert isinstance(rh["MGEF:FULL"], str)
    assert rh["MGEF:FULL"].strip() != ""
    # ``:`` を含む他の REC キーもアクセス可能
    assert "INFO:RNAM" in rh
    assert "BOOK:DESC" in rh


# ---------------------------------------------------------------------------
# T157: rec_hints = {}（空テーブル）時の _build_user_message が source のみを返す
# ---------------------------------------------------------------------------

def test_T157_build_user_message_empty_rec_hints_returns_source_only() -> None:
    """T157: ``rec_hints = {}``（空テーブル）の時、
    ``_build_user_message(source, rec, rec_hints={})`` が source のみを返すことの検証。

    Plan 005 §4.5 T157 / §2.6: v0.5 で ``_build_user_message`` は
    ``_build_user_message(source, rec, rec_hints)`` に signature 変更される。
    空テーブル許可の仕様閉包として、ヒントが無い場合は source そのものを返す。
    本テストは新 signature に依存するため、WP-2 完了後に green 化する。
    """
    # local import（WP-1 段階では _build_user_message は 2引数のまま → TypeError で red）
    from iroiro.translator import _build_user_message

    source = "Fireball"
    # 空 rec_hints を渡した場合・ヒントが付与されず source そのものを返す
    result = _build_user_message(source, "MGEF:FULL", {})
    assert result == source, (
        f"空 rec_hints の時は source のみ返す: 実際 {result!r}"
    )


# ===========================================================================
# v0.6: T158-T164 — skip_records の toml 化（Plan 006 §5 / §9.2）
#
# Plan 006 §5 で [iroiro] skip_records が必須化（案 α 徹底版・DEFAULT_SKIP_RECORDS
# 完全削除）。本セクションは load_config が skip_records を正しく検証・normalize
# することを検証する。
#
# 検証ルール（Plan 006 §5.2）:
#
# ===================  =========================================  ===============================
# キー                 制約                                        備考
# ===================  =========================================  ===============================
# ``skip_records``    ``list[str]``・各要素非空 str              ``bool`` 拒否・空リスト ``[]`` は許可・
#                                                                 重複は ``frozenset`` 化で除去・
#                                                                 各要素を ``strip().upper()`` で正規化
# ===================  =========================================  ===============================
#
# 必須チェック（Plan 006 §5.3）: 欠損時 ``IroiroError``
#   ``"[iroiro] skip_records is required in <path>"``
#
# ※ WP-1 段階では load_config に skip_records の検証が未実装のため、本セクションの
#    テストは全て red（WP-2 完了後に green 化）。既存テスト（T88-T157）は現状維持。
#
# ※ 本セクションのテストは ``load_config`` 経由で検証するため、``_validate_skip_records``
#    関数を直接 import しない（local import 不要・collection error 回避）。
# ===========================================================================


# ---------------------------------------------------------------------------
# T158: load_config が skip_records を frozenset[str] で返す
# ---------------------------------------------------------------------------

def test_T158_skip_records_returned_as_frozenset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T158: ``load_config`` が ``skip_records`` を ``frozenset[str]`` で返す。

    Plan 006 §5.1 / §5.2: ``skip_records`` は ``list[str]``（TOML 配列）を受取り、
    ``frozenset[str]`` に normalize される（重複除去・大文字化）。
    ``iroiro_v05_full.toml`` に v0.6 の 14 件を追記した状態で、全 14 件が
    ``frozenset[str]`` として返ることを検証する。

    ※ WP-1 段階では ``skip_records`` は未知キー扱い（WARNING + 無視）のため
       ``result["skip_records"]`` が ``KeyError`` になり red。WP-2 完了後に green。
    """
    shutil.copy(FIXTURES_DIR / "iroiro_v05_full.toml", tmp_path / "iroiro.toml")
    monkeypatch.chdir(tmp_path)

    result = load_config(None)

    # skip_records は frozenset[str] として返る
    assert "skip_records" in result, (
        f"skip_records は必須・dict に含まれる: 実際 {result.keys()!r}"
    )
    sr = result["skip_records"]
    assert isinstance(sr, frozenset), (
        f"skip_records は frozenset に normalize される: 実際 {type(sr)!r}"
    )
    # v0.6 デフォルト 14 件が全て含まれる
    expected = frozenset({
        "HDPT:FULL", "FURN:FULL", "CLAS:FULL", "DOOR:FULL",
        "FACT:FULL", "CLFM:FULL", "TREE:FULL", "MGEF:FULL",
        "RACE:FULL", "EXPL:FULL", "HAZD:FULL", "BPTD:BPTN",
        "FLST:FULL", "KYWD:FULL",
    })
    assert sr == expected, (
        f"skip_records は v0.6 デフォルト 14 件: 実際 {sr!r}"
    )
    assert len(sr) == 14


# ---------------------------------------------------------------------------
# T159: skip_records 欠損で IroiroError
# ---------------------------------------------------------------------------

def test_T159_skip_records_required(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T159: ``skip_records`` が toml に存在しない場合 ``IroiroError``。

    Plan 006 §5.3: ``skip_records`` は必須。欠損時のエラーメッセージは
    ``"[iroiro] skip_records is required in <path>"``（system_prompt /
    reject_phrases / rec_hints と同パターン）。

    ※ WP-1 段階では ``skip_records`` 必須チェックが未実装のため、``load_config``
       が例外を投げずに ``IroiroError`` が raise されない → red。WP-2 完了後に green。
    """
    shutil.copy(
        FIXTURES_DIR / "iroiro_v06_missing_skip_records.toml",
        tmp_path / "iroiro.toml",
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(IroiroError) as exc_info:
        load_config(None)

    msg = str(exc_info.value)
    assert "skip_records" in msg, (
        f"エラーメッセージに skip_records が言及される: 実際 {msg!r}"
    )


# ---------------------------------------------------------------------------
# T160: skip_records が list でない（文字列スカラー）→ IroiroError
# ---------------------------------------------------------------------------

def test_T160_skip_records_string_scalar_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T160: ``skip_records = "HDPT:FULL"``（文字列スカラー） → ``IroiroError``。

    Plan 006 §5.2: ``list`` 型のみ許可。文字列スカラーは ``list`` でないため
    型エラーで拒否される（``_validate_reject_phrases`` と同パターン）。
    YAML 等と勘違いして文字列で書く事故を防ぐ。

    ※ WP-1 段階では ``skip_records`` は未知キー扱いで検証されないため
       ``IroiroError`` が raise されない → red。WP-2 完了後に green。
    """
    (tmp_path / "iroiro.toml").write_text(
        '[iroiro]\n'
        'system_prompt = "x"\n'
        'reject_phrases = ["了解"]\n'
        'skip_records = "HDPT:FULL"\n'  # 文字列スカラー（list でない）
        '[iroiro.rec_hints]\n"MGEF:FULL" = "x"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(IroiroError) as exc_info:
        load_config(None)

    msg = str(exc_info.value).lower()
    assert "skip_records" in msg or "list" in msg, (
        f"エラーメッセージに skip_records または list が言及される: 実際 {msg!r}"
    )


# ---------------------------------------------------------------------------
# T161: skip_records 要素が空文字 → IroiroError
# ---------------------------------------------------------------------------

def test_T161_skip_records_empty_element_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T161: ``skip_records`` 要素が空文字（``""``） → ``IroiroError``。

    Plan 006 §5.2: 各要素は非空 ``str``。``""`` は値域エラーで拒否される
    （``_validate_reject_phrases`` と同パターン）。

    ※ WP-1 段階では ``skip_records`` は未知キー扱いで検証されないため
       ``IroiroError`` が raise されない → red。WP-2 完了後に green。
    """
    (tmp_path / "iroiro.toml").write_text(
        '[iroiro]\n'
        'system_prompt = "x"\n'
        'reject_phrases = ["了解"]\n'
        'skip_records = ["HDPT:FULL", ""]\n'  # 空文字要素
        '[iroiro.rec_hints]\n"MGEF:FULL" = "x"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(IroiroError):
        load_config(None)


# ---------------------------------------------------------------------------
# T161b: skip_records 要素が strip 後空文字 → IroiroError
# ---------------------------------------------------------------------------

def test_T161b_skip_records_whitespace_element_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T161b: ``skip_records`` 要素が strip 後空文字（``"   "``） → ``IroiroError``。

    Plan 006 §5.2 / §9.2 T161b（Codex review 指摘）: ``strip().upper()`` 後も
    非空を要求する（``_validate_reject_phrases`` と同パターン）。

    ※ WP-1 段階では ``skip_records`` は未知キー扱いで検証されないため
       ``IroiroError`` が raise されない → red。WP-2 完了後に green。
    """
    (tmp_path / "iroiro.toml").write_text(
        '[iroiro]\n'
        'system_prompt = "x"\n'
        'reject_phrases = ["了解"]\n'
        'skip_records = ["HDPT:FULL", "   "]\n'  # strip 後空文字
        '[iroiro.rec_hints]\n"MGEF:FULL" = "x"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(IroiroError):
        load_config(None)


# ---------------------------------------------------------------------------
# T161c: skip_records 要素が int / bool → IroiroError
# ---------------------------------------------------------------------------

def test_T161c_skip_records_int_bool_element_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T161c: ``skip_records`` 要素が ``int`` / ``bool`` → ``IroiroError``。

    Plan 006 §5.2 / §9.2 T161c（Codex review 指摘）: ``bool ⊂ int`` 事故防止のため
    要素は厳格に ``str`` のみ許可（``_validate_reject_phrases`` と対称）。
    ``[123]`` / ``[true]`` 等の要素は型エラーで拒否される。

    ※ WP-1 段階では ``skip_records`` は未知キー扱いで検証されないため
       ``IroiroError`` が raise されない → red。WP-2 完了後に green。
    """
    # 拒否ケース: int 要素
    (tmp_path / "iroiro.toml").write_text(
        '[iroiro]\n'
        'system_prompt = "x"\n'
        'reject_phrases = ["了解"]\n'
        'skip_records = [123]\n'  # int 要素
        '[iroiro.rec_hints]\n"MGEF:FULL" = "x"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    with pytest.raises(IroiroError):
        load_config(None)

    # 拒否ケース: bool 要素
    (tmp_path / "iroiro.toml").write_text(
        '[iroiro]\n'
        'system_prompt = "x"\n'
        'reject_phrases = ["了解"]\n'
        'skip_records = [true]\n'  # bool 要素
        '[iroiro.rec_hints]\n"MGEF:FULL" = "x"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    with pytest.raises(IroiroError):
        load_config(None)


# ---------------------------------------------------------------------------
# T162: skip_records = [] は空 frozenset として許可（全件翻訳）
# ---------------------------------------------------------------------------

def test_T162_skip_records_empty_list_allowed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T162: ``skip_records = []``（空リスト）は正当値として許可される。

    Plan 006 §5.1 / §5.2 / §4.5: 空リスト ``[]`` は正当値（空 ``frozenset`` に
    normalize）。「全件翻訳」のユースケース。``compute_skip_records_fingerprint``
    の空集合特例（``""`` 返却・Plan 006 §4.5）と整合。

    ※ WP-1 段階では ``skip_records`` は未知キー扱いで ``result["skip_records"]``
       が ``KeyError`` になり red。WP-2 完了後に green。
    """
    (tmp_path / "iroiro.toml").write_text(
        '[iroiro]\n'
        'system_prompt = "x"\n'
        'reject_phrases = ["了解"]\n'
        'skip_records = []\n'  # 空リスト
        '[iroiro.rec_hints]\n"MGEF:FULL" = "x"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    result = load_config(None)

    # 空リスト（または空 frozenset）として返る・エラーにならない
    assert "skip_records" in result, (
        f"skip_records = [] は正当値・dict に含まれる: 実際 {result.keys()!r}"
    )
    sr = result["skip_records"]
    assert isinstance(sr, frozenset), (
        f"skip_records は frozenset: 実際 {type(sr)!r}"
    )
    assert len(sr) == 0, f"skip_records = [] は空 frozenset として返る: 実際 {sr!r}"


# ---------------------------------------------------------------------------
# T163: skip_records の大文字正規化（hdpt:full → HDPT:FULL）
# ---------------------------------------------------------------------------

def test_T163_skip_records_uppercase_normalization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T163: ``skip_records`` の各要素は ``strip().upper()`` で正規化される。

    Plan 006 §5.2: 各要素を ``strip().upper()`` で正規化（``_parse_skip_records``
    と同様）。``"hdpt:full"`` は ``"HDPT:FULL"`` に変換されて返る。

    ※ WP-1 段階では ``skip_records`` は未知キー扱いで ``result["skip_records"]``
       が ``KeyError`` になり red。WP-2 完了後に green。
    """
    (tmp_path / "iroiro.toml").write_text(
        '[iroiro]\n'
        'system_prompt = "x"\n'
        'reject_phrases = ["了解"]\n'
        'skip_records = ["hdpt:full"]\n'  # 小文字
        '[iroiro.rec_hints]\n"MGEF:FULL" = "x"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    result = load_config(None)

    sr = result["skip_records"]
    assert "HDPT:FULL" in sr, (
        f"小文字 'hdpt:full' は 'HDPT:FULL' に正規化される: 実際 {sr!r}"
    )
    assert "hdpt:full" not in sr, (
        f"小文字のままの要素は残らない: 実際 {sr!r}"
    )


# ---------------------------------------------------------------------------
# T164: skip_records 重複除去（["HDPT:FULL", "HDPT:FULL"] → 1 件）
# ---------------------------------------------------------------------------

def test_T164_skip_records_dedup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T164: ``skip_records`` の重複要素は ``frozenset`` 化で除去される。

    Plan 006 §5.1 / §5.2: ``frozenset[str]`` への normalize で重複除去（T135 の
    ``reject_phrases`` と同パターン）。``["HDPT:FULL", "HDPT:FULL"]`` は 1 件になる。

    ※ WP-1 段階では ``skip_records`` は未知キー扱いで ``result["skip_records"]``
       が ``KeyError`` になり red。WP-2 完了後に green。
    """
    (tmp_path / "iroiro.toml").write_text(
        '[iroiro]\n'
        'system_prompt = "x"\n'
        'reject_phrases = ["了解"]\n'
        'skip_records = ["HDPT:FULL", "HDPT:FULL", "MGEF:FULL", "MGEF:FULL"]\n'
        '[iroiro.rec_hints]\n"MGEF:FULL" = "x"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    result = load_config(None)

    sr = result["skip_records"]
    assert isinstance(sr, frozenset), (
        f"skip_records は frozenset: 実際 {type(sr)!r}"
    )
    assert sr == frozenset({"HDPT:FULL", "MGEF:FULL"}), (
        f"重複が除去されて 2 件になる: 実際 {sr!r}"
    )
    assert len(sr) == 2
