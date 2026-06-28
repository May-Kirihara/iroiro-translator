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
# T88: load_config(None) — cwd に iroiro.toml 無し → {}
# ===========================================================================

def test_T88_no_config_file_returns_empty_dict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T88: cwd に iroiro.toml が無い場合、load_config(None) は {} を返す。

    後方互換性の基礎: 設定ファイルが存在しない場合は空 dict を返し、
    呼出側は内蔵デフォルトを使う（v0.1 と同じ挙動）。
    """
    # tmp_path は空なので iroiro.toml は見つからない
    monkeypatch.chdir(tmp_path)
    result = load_config(None)
    assert result == {}, (
        f"iroiro.toml が無い場合は空 dict: 実際 {result!r}"
    )


# ===========================================================================
# T89: 全項目記述の iroiro.toml → 全項目反映
# ===========================================================================

def test_T89_full_config_all_keys_reflected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T89: 全項目を記述した iroiro.toml を読み込み、全て反映されること。

    iroiro_full.toml の値（DEFAULT_* と明確に異なる）がそのまま返る。
    """
    # fixture を cwd の iroiro.toml として配置
    shutil.copy(FIXTURES_DIR / "iroiro_full.toml", tmp_path / "iroiro.toml")
    monkeypatch.chdir(tmp_path)

    result = load_config(None)

    assert result == {
        "api_base": "http://from-toml:9999/v1",
        "api_key": "toml-secret-key",
        "model": "toml-model-name",
        "timeout": 99.0,
        "concurrency": 7,
        "max_chars": 7777,
    }, f"全項目が反映される: 実際 {result!r}"


# ===========================================================================
# T90: 一部項目のみ → その項目だけ（残りは含まれない）
# ===========================================================================

def test_T90_partial_config_only_recorded_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T90: 一部項目のみ記述の場合、その項目だけが dict に含まれる。

    記述されていない項目は dict のキーに存在しない（呼出側で _resolve が
    内蔵デフォルトに落ちる）。これが §4.4 のマージ規則の前提。
    """
    shutil.copy(FIXTURES_DIR / "iroiro_partial.toml", tmp_path / "iroiro.toml")
    monkeypatch.chdir(tmp_path)

    result = load_config(None)

    # api_base と model だけ含まれる
    assert result == {
        "api_base": "http://partial:8080/v1",
        "model": "partial-model",
    }, f"一部項目だけ反映: 実際 {result!r}"
    # 記述されていない項目はキーに無い（デフォルトに落ちる根拠）
    assert "api_key" not in result
    assert "timeout" not in result
    assert "concurrency" not in result
    assert "max_chars" not in result


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
# T94: [iroiro] テーブル無し（[other] だけ） → {}
# ===========================================================================

def test_T94_no_iroiro_section_returns_empty_dict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """T94: [iroiro] セクションが存在しない場合、{} を返す（警告なし）。

    §4.5.2: [other] セクションだけ等の場合は {} を返し、警告も出さない
    （空と同じ扱い）。ファイルが存在しても [iroiro] が無ければ設定無し。
    """
    shutil.copy(FIXTURES_DIR / "iroiro_other_only.toml", tmp_path / "iroiro.toml")
    monkeypatch.chdir(tmp_path)

    with caplog.at_level(logging.WARNING):
        result = load_config(None)

    assert result == {}, (
        f"[iroiro] セクションが無い場合は空 dict: 実際 {result!r}"
    )
    # 警告ログは出ない（[iroiro] 無しは正常系）
    assert len(caplog.records) == 0, (
        f"[iroiro] セクション無しは警告しない: 実際 {caplog.records!r}"
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
