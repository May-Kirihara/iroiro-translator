"""test_progress.py — ProgressWriter / 進捗ファイルのテスト（T19-T25, T46, T50）。

v0.2 追加: T77-T80（``skip_records_fingerprint`` 検証）, T83（新規書き込みに
``skip_records_fingerprint`` フィールドが含まれる）。

対象モジュール: `iroiro/progress.py`
シグネチャ契約（Plan §6.5）:
    @dataclass(slots=True)
    class ProgressData:
        entries: dict[int, str]
        failed: list[int]
        input_hash: str
        api_base: str
        model: str
        skip_records_fingerprint: str  # v0.2 追加

    class ProgressWriter:
        def __init__(self, progress_path: Path, input_path: Path,
                     input_hash: str, api_base: str, model: str,
                     skip_records_fingerprint: str) -> None: ...
        async def mark_done(self, index: int, dest: str) -> None: ...
        async def mark_failed(self, index: int) -> None: ...
        def load_existing(self) -> ProgressData | None: ...

    def compute_input_hash(path: Path) -> str: ...
    def compute_skip_records_fingerprint(skip_records: frozenset[str]) -> str: ...

検証項目:
  - 原子書き込み（tmp + os.replace）で tmp 残存無し
  - asyncio.Lock で並行安全（concurrency 4 で 100 エントリ同時）
  - input_hash 不一致 / JSON decode error は ValueError で停止
  - input_path メタ情報が入力XMLのパスを指す
  - resume 時の failed index 保持
  - v0.2: skip_records_fingerprint 不一致で ValueError（input_hash と同じパターン）
  - v0.2: v0.1 形式 progress.json（fingerprint フィールド無し = ""）との互換性
  - v0.2: 新規書き込みした progress.json に skip_records_fingerprint フィールドが含まれる
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from iroiro.progress import (
    ProgressWriter,
    compute_input_hash,
    compute_skip_records_fingerprint,
)

# ===========================================================================
# 共通ヘルパー
# ===========================================================================

def _make_writer(
    tmp_path: Path,
    input_hash: str = "testhash",
    skip_records_fingerprint: str = "",
) -> ProgressWriter:
    """テスト用 ProgressWriter を作成。

    ``skip_records_fingerprint`` は v0.2 で追加された必須引数。default は ""
    （= v0.1 互換・空 set 扱い）。T77-T80 で明示的に異なる値を渡す。
    """
    input_xml = tmp_path / "input.xml"
    input_xml.write_text("<x/>")
    progress_path = tmp_path / "input.iroiro-progress.json"
    return ProgressWriter(
        progress_path=progress_path,
        input_path=input_xml,
        input_hash=input_hash,
        api_base="http://localhost:8081/v1",
        model="test-model",
        skip_records_fingerprint=skip_records_fingerprint,
    )


# ===========================================================================
# T19: mark_done → ファイル更新 → 再読込で同一
# ===========================================================================

@pytest.mark.asyncio
async def test_T19_mark_done_and_reload(tmp_path: Path) -> None:
    """T19: mark_done 後にファイルが更新され、load_existing で同一内容が読める。"""
    writer = _make_writer(tmp_path, input_hash="hash19")
    await writer.mark_done(0, "訳文0")
    await writer.mark_done(1, "訳文1")

    # ファイルが存在する
    assert writer._path.exists(), "progress.json が作成されている"

    data = writer.load_existing()
    assert data is not None
    assert data.entries == {0: "訳文0", 1: "訳文1"}
    assert data.input_hash == "hash19"
    assert data.api_base == "http://localhost:8081/v1"
    assert data.model == "test-model"
    assert data.failed == []


# ===========================================================================
# T20: 原子的書き込み: tmp が残らない（成功時）
# ===========================================================================

@pytest.mark.asyncio
async def test_T20_atomic_write_no_tmp_residue(tmp_path: Path) -> None:
    """T20: mark_done 成功時に .tmp ファイルが残らないこと。

    Plan §5.8: tmp -> os.replace の原子的書き込み。
    """
    writer = _make_writer(tmp_path)
    await writer.mark_done(0, "訳文0")
    await writer.mark_done(1, "訳文1")

    # .tmp ファイルが残存しない
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert not tmp_files, f".tmp ファイルが残存: {tmp_files}"

    # progress.json 自体は存在
    assert writer._path.exists()


# ===========================================================================
# T21: input_hash 不一致で ValueError
# ===========================================================================

def test_T21_hash_mismatch_raises(tmp_path: Path) -> None:
    """T21: 既存 progress.json の input_hash が異なる場合、load_existing が ValueError。

    Plan §5.8: hash 不一致は ValueError を上げて停止（自動修復しない）。
    """
    progress_path = tmp_path / "input.iroiro-progress.json"
    progress_path.write_text(
        json.dumps(
            {
                "input_path": str(tmp_path / "input.xml"),
                "input_hash": "OLD_HASH",
                "api_base": "http://localhost:8081/v1",
                "model": "test-model",
                "entries": {0: "訳文0"},
                "failed": [],
            },
            ensure_ascii=False,
        )
    )

    # 新しい writer は異なる hash を持つ
    writer = ProgressWriter(
        progress_path=progress_path,
        input_path=tmp_path / "input.xml",
        input_hash="NEW_HASH",
        api_base="http://localhost:8081/v1",
        model="test-model",
        skip_records_fingerprint="",  # v0.2 追加・既存 progress.json は "" 扱い
    )

    with pytest.raises(ValueError):
        writer.load_existing()


# ===========================================================================
# T22: concurrency 4 で100エントリを同時 mark_done → 件数完全、データ破損なし
# ===========================================================================

@pytest.mark.asyncio
async def test_T22_concurrent_mark_done_100_entries(tmp_path: Path) -> None:
    """T22: asyncio.Lock で並行安全。100エントリを concurrency=4 相当で同時書き込み。

    Plan §5.8 + NB#6/指摘#4: 並行 mark_done で件数漏れ・データ破損が無いこと。
    """
    writer = _make_writer(tmp_path)

    async def mark(i: int) -> None:
        await writer.mark_done(i, f"訳文{i:03d}")

    # 100タスクを4つずつ同時実行（Semaphore で制限）
    sem = asyncio.Semaphore(4)

    async def bounded_mark(i: int) -> None:
        async with sem:
            await mark(i)

    await asyncio.gather(*(bounded_mark(i) for i in range(100)))

    data = writer.load_existing()
    assert data is not None
    assert len(data.entries) == 100, f"全100件記録される: 実際 {len(data.entries)}"
    for i in range(100):
        assert data.entries[i] == f"訳文{i:03d}", f"index {i} の訳文が正しい"


# ===========================================================================
# T23: failed リストの追記
# ===========================================================================

@pytest.mark.asyncio
async def test_T23_mark_failed_appends(tmp_path: Path) -> None:
    """T23: mark_failed を呼ぶと failed リストに index が追加される。

    v0.4（Plan 004 §4.6）で ``mark_failed`` に重複チェックが入り、同じ index の
    2回目以降の呼出は無視される（従来は append 式で重複が発生し得た）。
    本テストの assert は「5 と 7 が共に含まれる」ことのみを検証するため、
    重複排除の前後を通じて green を保つ（単発呼出の挙動は変わらない）。
    重複排除自体の検証は T118（同 index 2回呼出 → 1個だけ）で担保する。
    """
    writer = _make_writer(tmp_path)
    await writer.mark_failed(5)
    await writer.mark_failed(7)
    await writer.mark_failed(5)  # v0.4: 重複チェックにより無視される（T118 で検証）

    data = writer.load_existing()
    assert data is not None
    # 5, 7 が共に含まれる（重複排除後も両方存在・単発呼出の挙動は不変）
    assert 5 in data.failed
    assert 7 in data.failed


# ===========================================================================
# T24: progress.json 破損時の挙動（JSON decode error → 停止＋ユーザー通知）
# ===========================================================================

def test_T24_corrupted_progress_raises(tmp_path: Path) -> None:
    """T24: JSON decode error の progress.json → load_existing が ValueError で停止。

    Plan §5.8: JSON decode error → 停止（新規作成しない）。ユーザーに削除を促す。
    """
    progress_path = tmp_path / "input.iroiro-progress.json"
    # 不正 JSON
    progress_path.write_text("{ this is not valid json,,, }")

    writer = ProgressWriter(
        progress_path=progress_path,
        input_path=tmp_path / "input.xml",
        input_hash="anyhash",
        api_base="http://localhost:8081/v1",
        model="test-model",
        skip_records_fingerprint="",  # v0.2 追加・JSON decode error 前に検査されない
    )

    with pytest.raises(ValueError):
        writer.load_existing()


# ===========================================================================
# T25: temp ファイル残存時のクリーンアップ
# ===========================================================================

@pytest.mark.asyncio
async def test_T25_stale_tmp_overwritten(tmp_path: Path) -> None:
    """T25: 前回クラッシュで残った .tmp があっても、次回 _flush で上書きされる。

    Plan §5.8: tmp -> os.replace は同じパスを使うため、古い .tmp は上書きされる。
    """
    writer = _make_writer(tmp_path)
    progress_path = writer._path
    tmp_path_for_writer = progress_path.with_suffix(progress_path.suffix + ".tmp")

    # 前回クラッシュで残った .tmp を模擬
    tmp_path_for_writer.write_text("stale content")

    # 新しい mark_done で _flush が走り、.tmp を上書き → os.replace で本ファイル化
    await writer.mark_done(0, "訳文0")

    # .tmp は本ファイル化され、残存しない
    assert not tmp_path_for_writer.exists(), "古い .tmp は本ファイル化され残存しない"
    assert progress_path.exists()

    data = writer.load_existing()
    assert data is not None
    assert data.entries == {0: "訳文0"}


# ===========================================================================
# T46: ProgressWriter の input_path メタ情報が入力XMLのパスを指すこと
# ===========================================================================

@pytest.mark.asyncio
async def test_T46_input_path_metadata(tmp_path: Path) -> None:
    """T46: progress.json の input_path が progress_path でなく入力XMLのパスを指す。

    Plan §5.8 (v0.3): progress_path / input_path を明示的に分離。
    """
    input_xml = tmp_path / "my_input.xml"
    input_xml.write_text("<x/>")
    progress_path = tmp_path / "my_input.iroiro-progress.json"

    writer = ProgressWriter(
        progress_path=progress_path,
        input_path=input_xml,
        input_hash="hash46",
        api_base="http://localhost:8081/v1",
        model="test-model",
        skip_records_fingerprint="",  # v0.2 追加
    )
    await writer.mark_done(0, "訳文0")

    # 生 JSON を読んで input_path を検証
    raw = json.loads(progress_path.read_text(encoding="utf-8"))
    assert raw["input_path"] == str(input_xml), (
        "input_path は入力XMLのパスを指す（progress_path でない）"
    )
    assert raw["input_path"] != str(progress_path)


# ===========================================================================
# T50: failed index を含む progress.json を --resume で読み込み、<Dest> が original_dest を保持
# ===========================================================================

def test_T50_resume_with_failed_indices(tmp_path: Path) -> None:
    """T50: failed index を含む progress.json を load_existing で読み込めること。

    Plan §7.3 T50: resume 時、failed index は再試行されずに ProgressData.failed に入る。
    CLI 側は failed index の <Dest> を original_dest として保持する（本テストは
    ProgressWriter 単体レベルの検証。CLI 統合は test_cli.py の T39 で担保）。
    """
    progress_path = tmp_path / "input.iroiro-progress.json"
    progress_path.write_text(
        json.dumps(
            {
                "input_path": str(tmp_path / "input.xml"),
                "input_hash": "hash50",
                "api_base": "http://localhost:8081/v1",
                "model": "test-model",
                "entries": {0: "訳文0", 1: "訳文1"},
                "failed": [2, 3],
            },
            ensure_ascii=False,
        )
    )

    writer = ProgressWriter(
        progress_path=progress_path,
        input_path=tmp_path / "input.xml",
        input_hash="hash50",
        api_base="http://localhost:8081/v1",
        model="test-model",
        skip_records_fingerprint="",  # v0.2 追加・v0.1 形式 progress.json は "" 扱いで一致
    )

    data = writer.load_existing()
    assert data is not None
    assert data.failed == [2, 3], "failed index が読み込まれる"
    assert data.entries == {0: "訳文0", 1: "訳文1"}


# ===========================================================================
# 補助テスト: compute_input_hash
# ===========================================================================

def test_compute_input_hash_stable(tmp_path: Path) -> None:
    """compute_input_hash は SHA256 を返し、同一ファイルで安定。"""
    p = tmp_path / "x.xml"
    p.write_bytes(b"<x/>")
    h1 = compute_input_hash(p)
    h2 = compute_input_hash(p)
    assert h1 == h2, "同一ファイルで hash は安定"
    assert len(h1) == 64, "SHA256 は64文字（hex）"


def test_compute_input_hash_differs(tmp_path: Path) -> None:
    """異なる内容で hash が異なる。"""
    p1 = tmp_path / "a.xml"
    p1.write_bytes(b"<a/>")
    p2 = tmp_path / "b.xml"
    p2.write_bytes(b"<b/>")
    assert compute_input_hash(p1) != compute_input_hash(p2)


def test_load_existing_returns_none_when_no_file(tmp_path: Path) -> None:
    """progress.json が存在しない場合は None。"""
    writer = _make_writer(tmp_path)
    assert writer.load_existing() is None


# ===========================================================================
# v0.2: T77-T80 — skip_records_fingerprint 検証（ProgressWriter 単体）
#
# Plan §5.4: progress.json の skip_records_fingerprint が現在の skip_records と
# 一致しない場合は ValueError で停止。input_hash と同じパターン。
# v0.1 形式 progress.json（fingerprint フィールド無し = ""）との互換性:
#   - 現在の fingerprint が "" （空 set）→ resume 成功（T79）
#   - 現在の fingerprint が非 "" （DEFAULT_SKIP_RECORDS 等）→ ValueError（T80）
# ===========================================================================


def test_T77_skip_records_fingerprint_mismatch_raises(tmp_path: Path) -> None:
    """T77: skip_records 変更後に ``--resume`` すると ValueError で停止。

    既存 progress.json の skip_records_fingerprint が現在の fingerprint と異なる
    場合、load_existing は ValueError を上げる（input_hash と同じパターン）。
    """
    fp_old = compute_skip_records_fingerprint(frozenset({"HDPT:FULL", "MGEF:FULL"}))
    fp_new = compute_skip_records_fingerprint(frozenset({"HDPT:FULL"}))

    progress_path = tmp_path / "input.iroiro-progress.json"
    progress_path.write_text(
        json.dumps(
            {
                "input_path": str(tmp_path / "input.xml"),
                "input_hash": "same_hash",
                "api_base": "http://localhost:8081/v1",
                "model": "test-model",
                "skip_records_fingerprint": fp_old,
                "entries": {0: "訳文0"},
                "failed": [],
            },
            ensure_ascii=False,
        )
    )

    # 新しい writer は異なる fingerprint を持つ（input_hash は同じ）
    writer = ProgressWriter(
        progress_path=progress_path,
        input_path=tmp_path / "input.xml",
        input_hash="same_hash",
        api_base="http://localhost:8081/v1",
        model="test-model",
        skip_records_fingerprint=fp_new,
    )

    with pytest.raises(ValueError):
        writer.load_existing()


def test_T78_skip_records_fingerprint_match_succeeds(tmp_path: Path) -> None:
    """T78: skip_records が同一なら ``--resume`` 成功。

    fingerprint が一致する場合は load_existing が ProgressData を返す。
    """
    fp = compute_skip_records_fingerprint(frozenset({"HDPT:FULL", "MGEF:FULL"}))

    progress_path = tmp_path / "input.iroiro-progress.json"
    progress_path.write_text(
        json.dumps(
            {
                "input_path": str(tmp_path / "input.xml"),
                "input_hash": "same_hash",
                "api_base": "http://localhost:8081/v1",
                "model": "test-model",
                "skip_records_fingerprint": fp,
                "entries": {0: "訳文0", 1: "訳文1"},
                "failed": [],
            },
            ensure_ascii=False,
        )
    )

    writer = ProgressWriter(
        progress_path=progress_path,
        input_path=tmp_path / "input.xml",
        input_hash="same_hash",
        api_base="http://localhost:8081/v1",
        model="test-model",
        skip_records_fingerprint=fp,  # 同じ fingerprint
    )

    data = writer.load_existing()
    assert data is not None, "fingerprint 一致で resume 成功"
    assert data.entries == {0: "訳文0", 1: "訳文1"}


def test_T79_v01_progress_with_empty_fingerprint_resumes_with_empty_set(
    tmp_path: Path,
) -> None:
    """T79: v0.1 形式 progress.json（fingerprint 無し = ""）+ 空 set（""）→ resume 成功。

    v0.1 で作成された progress.json には skip_records_fingerprint フィールドが無い。
    これは "" と解釈される。現在の設定が ``--no-skip-default-records``（空 set = ""）
    の場合、fingerprint が一致するので resume 成功する（後方互換性）。
    """
    progress_path = tmp_path / "input.iroiro-progress.json"
    # v0.1 形式: skip_records_fingerprint フィールド無し
    progress_path.write_text(
        json.dumps(
            {
                "input_path": str(tmp_path / "input.xml"),
                "input_hash": "same_hash",
                "api_base": "http://localhost:8081/v1",
                "model": "test-model",
                # skip_records_fingerprint 無し → "" と解釈される
                "entries": {0: "訳文0"},
                "failed": [],
            },
            ensure_ascii=False,
        )
    )

    # 現在は --no-skip-default-records（空 set = fingerprint ""）
    writer = ProgressWriter(
        progress_path=progress_path,
        input_path=tmp_path / "input.xml",
        input_hash="same_hash",
        api_base="http://localhost:8081/v1",
        model="test-model",
        skip_records_fingerprint="",  # 空 set
    )

    data = writer.load_existing()
    assert data is not None, (
        "v0.1 形式 progress.json + 空 set で resume 成功（後方互換性）"
    )
    assert data.entries == {0: "訳文0"}


def test_T80_v01_progress_with_default_skip_records_raises(tmp_path: Path) -> None:
    """T80: v0.1 形式 progress.json（fingerprint=""）+ DEFAULT_SKIP_RECORDS → ValueError.

    v0.1 で作成された progress.json（fingerprint=""）に対して v0.2 のデフォルト動作
    （DEFAULT_SKIP_RECORDS = 非空 fingerprint）で resume しようとすると、
    fingerprint 不一致で ValueError になる（安全側に倒す）。
    ユーザーは progress.json を削除する必要がある。
    """
    from iroiro.translator import DEFAULT_SKIP_RECORDS

    progress_path = tmp_path / "input.iroiro-progress.json"
    # v0.1 形式: skip_records_fingerprint フィールド無し（= "" 扱い）
    progress_path.write_text(
        json.dumps(
            {
                "input_path": str(tmp_path / "input.xml"),
                "input_hash": "same_hash",
                "api_base": "http://localhost:8081/v1",
                "model": "test-model",
                # skip_records_fingerprint 無し → "" と解釈される
                "entries": {0: "訳文0"},
                "failed": [],
            },
            ensure_ascii=False,
        )
    )

    # 現在はデフォルト動作（DEFAULT_SKIP_RECORDS）
    fp_default = compute_skip_records_fingerprint(DEFAULT_SKIP_RECORDS)
    assert fp_default != "", "前提: DEFAULT_SKIP_RECORDS の fingerprint は非空"

    writer = ProgressWriter(
        progress_path=progress_path,
        input_path=tmp_path / "input.xml",
        input_hash="same_hash",
        api_base="http://localhost:8081/v1",
        model="test-model",
        skip_records_fingerprint=fp_default,  # v0.1 の "" と不一致
    )

    with pytest.raises(ValueError):
        writer.load_existing()


# ===========================================================================
# v0.2: T83 — 新規書き込みした progress.json に skip_records_fingerprint が含まれる
#
# Codex レビュー#3 の test gap 対応。WP-2 の実装が正しく fingerprint を保存しているか。
# ===========================================================================


@pytest.mark.asyncio
async def test_T83_new_progress_includes_skip_records_fingerprint(tmp_path: Path) -> None:
    """T83: v0.2 で新規書き込みした progress.json に skip_records_fingerprint が含まれる。

    ProgressWriter.__init__ に渡した fingerprint が progress.json に保存される。
    これにより resume 時の検証が機能する（T77-T80 の前提）。
    """
    fp = compute_skip_records_fingerprint(frozenset({"HDPT:FULL", "MGEF:FULL"}))
    assert fp != "", "前提: 非空 set の fingerprint は非空"

    writer = ProgressWriter(
        progress_path=tmp_path / "input.iroiro-progress.json",
        input_path=tmp_path / "input.xml",
        input_hash="hash83",
        api_base="http://localhost:8081/v1",
        model="test-model",
        skip_records_fingerprint=fp,
    )
    await writer.mark_done(0, "訳文0")

    # 生 JSON を読んで skip_records_fingerprint フィールドを検証
    raw = json.loads(
        (tmp_path / "input.iroiro-progress.json").read_text(encoding="utf-8")
    )
    assert "skip_records_fingerprint" in raw, (
        "progress.json に skip_records_fingerprint フィールドが含まれる"
    )
    assert raw["skip_records_fingerprint"] == fp, (
        f"fingerprint 値が一致: {raw['skip_records_fingerprint']!r} vs {fp!r}"
    )


@pytest.mark.asyncio
async def test_T83b_empty_fingerprint_also_persisted(tmp_path: Path) -> None:
    """T83 補足: 空 fingerprint（""）も progress.json に保存される。

    ``--no-skip-default-records`` 指定時（空 set）も fingerprint フィールドは
    空文字列として保存される。これにより v0.1 形式との相互運用性が担保される。
    """
    writer = ProgressWriter(
        progress_path=tmp_path / "input.iroiro-progress.json",
        input_path=tmp_path / "input.xml",
        input_hash="hash83b",
        api_base="http://localhost:8081/v1",
        model="test-model",
        skip_records_fingerprint="",  # 空 set
    )
    await writer.mark_done(0, "訳文0")

    raw = json.loads(
        (tmp_path / "input.iroiro-progress.json").read_text(encoding="utf-8")
    )
    assert "skip_records_fingerprint" in raw
    assert raw["skip_records_fingerprint"] == "", (
        "空 set の fingerprint は空文字列として保存される"
    )


# ===========================================================================
# T84 (critical regression): resume 後の mark_done が既存 entries を保持する
#
# v0.1-v0.2 で発見された critical データ消失バグの回帰テスト:
#   - ProgressWriter.__init__ が self._data["entries"] = {} で初期化
#   - load_existing が ProgressData 戻り値を返すだけで self._data を更新しなかった
#   - そのため resume 後の mark_done → _flush が既存 entries を消していた
# 修正後は load_existing が self._data["entries"] / ["failed"] に既存内容を
# 統合するので、mark_done が既存+新規の両方を保持する。
# 参考: AGENTS.md「XML 安全性の鉄則 — 失敗・スキップ時は元の <Dest> を保持」の
# 進捗ファイル版に相当（翻訳済み成果物の消失防止）。
# ===========================================================================


@pytest.mark.asyncio
async def test_T84_resume_preserves_existing_entries_on_mark_done(
    tmp_path: Path,
) -> None:
    """T84: resume 後の mark_done が既存 entries を保持する（critical 回帰）。

    再現手順:
      1. 既存 progress.json（3件）を作成
      2. ProgressWriter で load_existing
      3. mark_done で新1件追加
      4. progress.json を読み直し、既存3件 + 新1件 = 4件であることを検証
    """
    # 既存 progress.json を作成（3件の訳文）
    progress_path = tmp_path / "test.json.iroiro-progress.json"
    existing_data = {
        "input_path": "test.xml",
        "input_hash": "hash_T84",
        "api_base": "http://localhost:8081/v1",
        "model": "test-model",
        "skip_records_fingerprint": "",
        "entries": {
            "701": "視覚的な美しさを。",
            "1102": "客がお金を払ってお尻を使えば、もっと稼げる。",
            "1184": "口塞ぎ",
        },
        "failed": [],
    }
    progress_path.write_text(
        json.dumps(existing_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # ProgressWriter を作成して load_existing
    writer = ProgressWriter(
        progress_path=progress_path,
        input_path=Path("test.xml"),
        input_hash="hash_T84",
        api_base="http://localhost:8081/v1",
        model="test-model",
        skip_records_fingerprint="",
    )
    existing = writer.load_existing()
    assert existing is not None
    assert len(existing.entries) == 3, "load_existing が既存3件を返す"

    # mark_done を呼ぶ（新4件目）
    await writer.mark_done(999, "新規訳文")

    # progress.json を読み直して検証
    raw = json.loads(progress_path.read_text(encoding="utf-8"))
    assert len(raw["entries"]) == 4, (
        f"既存3件 + 新1件 = 4件であるべき: 実際 {len(raw['entries'])}件"
    )
    # 既存3件が保持されている
    assert raw["entries"]["701"] == "視覚的な美しさを。"
    assert raw["entries"]["1102"] == "客がお金を払ってお尻を使えば、もっと稼げる。"
    assert raw["entries"]["1184"] == "口塞ぎ"
    # 新1件が追加されている
    assert raw["entries"]["999"] == "新規訳文"


@pytest.mark.asyncio
async def test_T84b_resume_preserves_existing_failed_on_mark_failed(
    tmp_path: Path,
) -> None:
    """T84b: resume 後の mark_failed も既存 failed リストを保持する。

    T84 の対となる failed 側の回帰テスト。``self._data["failed"]`` も
    load_existing で統合されるため、resume 後の mark_failed が
    既存 failed index を保持したまま追記される。
    """
    progress_path = tmp_path / "input.iroiro-progress.json"
    existing_data = {
        "input_path": "test.xml",
        "input_hash": "hash_T84b",
        "api_base": "http://localhost:8081/v1",
        "model": "test-model",
        "skip_records_fingerprint": "",
        "entries": {0: "訳文0"},
        "failed": [10, 20],  # 既存の failed index
    }
    progress_path.write_text(
        json.dumps(existing_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    writer = ProgressWriter(
        progress_path=progress_path,
        input_path=Path("test.xml"),
        input_hash="hash_T84b",
        api_base="http://localhost:8081/v1",
        model="test-model",
        skip_records_fingerprint="",
    )
    existing = writer.load_existing()
    assert existing is not None
    assert existing.failed == [10, 20]

    # 新たに mark_failed（新1件）+ mark_done も併せて検証
    await writer.mark_failed(30)
    await writer.mark_done(99, "新規訳文")

    raw = json.loads(progress_path.read_text(encoding="utf-8"))
    # 既存 entries が保持されつつ新1件追加
    assert raw["entries"] == {"0": "訳文0", "99": "新規訳文"}, (
        "既存 entries 保持 + 新規 mark_done 追加"
    )
    # 既存 failed が保持されつつ新1件追加
    assert raw["failed"] == [10, 20, 30], (
        f"既存 [10,20] + 新 [30] = [10,20,30]: 実際 {raw['failed']}"
    )


# ===========================================================================
# v0.4: T118-T121 — mark_failed 重複チェック / mark_done failed クリア
#
# Plan 004 §4.6 で明文化された **不変性**: ある index は同時に entries と
# failed に存在しない（``entries ∩ failed = ∅``）。これを保証するため両メソッドを拡張:
#   - ``mark_failed(i)``: ``failed`` に ``i`` が無ければ追加（重複排除）
#   - ``mark_done(i, ...)``: ``entries`` に ``i`` を追加後、``failed`` に ``i``
#     があれば削除（retry 成功時のクリア）
# これにより ``retry_failed=True`` で再試行 → 成功/再失敗 の両経路で
# progress.json と「Resuming: X translated, Y failed」メッセージが整合する。
#
# ※ T122 は独立したテスト関数でなく T23 のコメント更新（v0.4 の重複排除仕様に
#    合わせた docstring / コメントの修正）として扱う。T23 の assert 自体は維持。
# ===========================================================================


@pytest.mark.asyncio
async def test_T118_mark_failed_dedup(tmp_path: Path) -> None:
    """T118: 同じ index を2回 mark_failed しても failed は1個だけ（重複排除）。

    Plan 004 §4.6: ``mark_failed()`` は ``if index not in failed`` で重複を弾く。
    ``retry_failed=True`` で再試行 → 再失敗 を繰り返しても同じ index が重複して
    progress.json に書き込まれるのを防止する（failed リストの膨張防止）。
    """
    writer = _make_writer(tmp_path)

    await writer.mark_failed(3)
    await writer.mark_failed(3)  # 重複
    await writer.mark_failed(3)  # さらにもう1回

    data = writer.load_existing()
    assert data is not None
    assert data.failed.count(3) == 1, (
        f"同じ index は1回だけ記録される（重複排除）: 実際 {data.failed}"
    )
    assert data.failed == [3], f"failed は [3] のみ: 実際 {data.failed}"


@pytest.mark.asyncio
async def test_T119_mark_failed_distinct_indices(tmp_path: Path) -> None:
    """T119: 異なる index を mark_failed した場合は両方記録される（正常系）。

    重複チェックが「全ての呼出を無視する」のでなく「同じ index のみ無視する」
    ことを検証する（T118 の対になる正常系）。
    """
    writer = _make_writer(tmp_path)

    await writer.mark_failed(3)
    await writer.mark_failed(7)

    data = writer.load_existing()
    assert data is not None
    assert data.failed == [3, 7], (
        f"異なる index は両方記録される: 実際 {data.failed}"
    )


@pytest.mark.asyncio
async def test_T120_mark_done_does_not_touch_failed_when_absent(
    tmp_path: Path,
) -> None:
    """T120: ``mark_done(i, ...)`` 後・i が failed に無い → 追加なし（回帰保証）。

    Plan 004 §4.6: ``mark_done()`` は entries に追記するのみ。``failed`` に ``i``
    が無い場合は failed リストを触らない（従来動作・v0.4 でも変更無し）。
    「何も無い所から failed に index が増えることは無い」ことで回帰を保証する。
    """
    writer = _make_writer(tmp_path)

    # i=5 は初回・failed には無い
    await writer.mark_done(5, "訳文5")

    data = writer.load_existing()
    assert data is not None
    assert data.entries == {5: "訳文5"}
    assert data.failed == [], (
        f"mark_done は failed を触らない（i が failed に無い場合）: 実際 {data.failed}"
    )


@pytest.mark.asyncio
async def test_T121_mark_done_clears_failed_on_retry_success(
    tmp_path: Path,
) -> None:
    """T121: ``mark_done(i, ...)`` 後・i が failed に有った → failed から削除（v0.4 新機能）。

    Plan 004 §4.6: ``retry_failed=True`` で再試行して成功した場合、``mark_done()``
    が ``entries`` に ``i`` を追加した **後**、``failed`` に同じ ``i`` があれば削除する。
    これにより不変性 ``entries ∩ failed = ∅`` を保証する。T125（CLI 統合）と対になる
    ProgressWriter 単体レベルの検証。

    再現手順:
      1. ``failed=[5]`` を持つ progress.json を作成（load_existing で self._data に統合）
      2. ``mark_done(5, "新訳文")`` を呼ぶ（retry 成功を模擬）
      3. progress.json を読み直し、failed から 5 が消え、entries["5"] に訳文が入ったことを検証
    """
    progress_path = tmp_path / "input.iroiro-progress.json"
    existing_data = {
        "input_path": "test.xml",
        "input_hash": "hash_T121",
        "api_base": "http://localhost:8081/v1",
        "model": "test-model",
        "skip_records_fingerprint": "",
        "entries": {0: "訳文0"},  # 別 index は既に翻訳済
        "failed": [5],  # i=5 は前回失敗
    }
    progress_path.write_text(
        json.dumps(existing_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    writer = ProgressWriter(
        progress_path=progress_path,
        input_path=Path("test.xml"),
        input_hash="hash_T121",
        api_base="http://localhost:8081/v1",
        model="test-model",
        skip_records_fingerprint="",
    )
    existing = writer.load_existing()
    assert existing is not None
    assert existing.failed == [5], "前提: failed に 5 が入っている"

    # retry 成功: mark_done(5, ...) で entries に追加 → failed から 5 を削除
    await writer.mark_done(5, "再翻訳成功")

    raw = json.loads(progress_path.read_text(encoding="utf-8"))
    assert raw["entries"]["5"] == "再翻訳成功", (
        f"entries['5'] に再翻訳の訳文が入る: 実際 {raw['entries']!r}"
    )
    assert 5 not in raw["failed"], (
        f"failed から 5 が削除される（不変性: entries ∩ failed = ∅）: "
        f"実際 {raw['failed']!r}"
    )
    # 既存の entries[0] は保持される（T84 と同じ critical 回帰の保護）
    assert raw["entries"]["0"] == "訳文0"


@pytest.mark.asyncio
async def test_T130_mark_done_clears_all_duplicate_failed(tmp_path: Path) -> None:
    """T130: failed に重複 index がある場合、mark_done で全件削除される（不変性保証）。

    v0.4 Codex review 指摘（N1）: ``list.remove(index)`` は最初に見つかった要素しか
    消さないため、``failed=[5, 5]`` のような重複がある progress.json（v0.3 以前生成）
    との整合性で全件削除が必要。リスト内包表記で同 index を全件削除することで
    **不変性** ``entries ∩ failed = ∅`` を保証する。

    再現手順:
      1. ``failed=[5, 5]`` を持つ progress.json を作成（load_existing で self._data に統合）
      2. ``mark_done(5, "translated")`` を呼ぶ（retry 成功を模擬）
      3. progress.json を読み直し、``failed == []``（全件削除）・
         ``entries["5"] == "translated"`` を検証
    """
    progress_path = tmp_path / "input.iroiro-progress.json"
    existing_data = {
        "input_path": "test.xml",
        "input_hash": "hash_T130",
        "api_base": "http://localhost:8081/v1",
        "model": "test-model",
        "skip_records_fingerprint": "",
        "entries": {0: "訳文0"},  # 別 index は既に翻訳済
        "failed": [5, 5],  # ★ index 5 が重複（v0.3 以前生成の progress.json を模擬）
    }
    progress_path.write_text(
        json.dumps(existing_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    writer = ProgressWriter(
        progress_path=progress_path,
        input_path=Path("test.xml"),
        input_hash="hash_T130",
        api_base="http://localhost:8081/v1",
        model="test-model",
        skip_records_fingerprint="",
    )
    existing = writer.load_existing()
    assert existing is not None
    assert existing.failed == [5, 5], "前提: failed に 5 が2個入っている（重複）"

    # retry 成功: mark_done(5, ...) で entries に追加 → failed から 5 を **全件** 削除
    await writer.mark_done(5, "translated")

    raw = json.loads(progress_path.read_text(encoding="utf-8"))
    assert raw["entries"]["5"] == "translated", (
        f"entries['5'] に訳文が入る: 実際 {raw['entries']!r}"
    )
    assert raw["failed"] == [], (
        f"failed から 5 が全件削除される（list.remove は最初の1件しか消さないため"
        f"リスト内包表記で全削除が必要・不変性保証）: 実際 {raw['failed']!r}"
    )
    # 既存の entries[0] は保持される（T84 と同じ critical 回帰の保護）
    assert raw["entries"]["0"] == "訳文0"
