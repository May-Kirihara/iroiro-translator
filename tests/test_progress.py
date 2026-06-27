"""test_progress.py — ProgressWriter / 進捗ファイルのテスト（T19-T25, T46, T50）。

対象モジュール: `iroiro/progress.py`
シグネチャ契約（Plan §6.5）:
    @dataclass(slots=True)
    class ProgressData:
        entries: dict[int, str]
        failed: list[int]
        input_hash: str
        api_base: str
        model: str

    class ProgressWriter:
        def __init__(self, progress_path: Path, input_path: Path,
                     input_hash: str, api_base: str, model: str) -> None: ...
        async def mark_done(self, index: int, dest: str) -> None: ...
        async def mark_failed(self, index: int) -> None: ...
        def load_existing(self) -> ProgressData | None: ...

    def compute_input_hash(path: Path) -> str: ...

検証項目:
  - 原子書き込み（tmp + os.replace）で tmp 残存無し
  - asyncio.Lock で並行安全（concurrency 4 で 100 エントリ同時）
  - input_hash 不一致 / JSON decode error は ValueError で停止
  - input_path メタ情報が入力XMLのパスを指す
  - resume 時の failed index 保持
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from iroiro.progress import ProgressWriter, compute_input_hash

# ===========================================================================
# 共通ヘルパー
# ===========================================================================

def _make_writer(tmp_path: Path, input_hash: str = "testhash") -> ProgressWriter:
    """テスト用 ProgressWriter を作成。"""
    input_xml = tmp_path / "input.xml"
    input_xml.write_text("<x/>")
    progress_path = tmp_path / "input.iroiro-progress.json"
    return ProgressWriter(
        progress_path=progress_path,
        input_path=input_xml,
        input_hash=input_hash,
        api_base="http://localhost:8081/v1",
        model="test-model",
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
    """T23: mark_failed を呼ぶと failed リストに index が追加される。"""
    writer = _make_writer(tmp_path)
    await writer.mark_failed(5)
    await writer.mark_failed(7)
    await writer.mark_failed(5)  # 重複しても追記される（実装依存だが追記式）

    data = writer.load_existing()
    assert data is not None
    # 5, 7 が含まれる（重複含むかどうかは実装依存だが、少なくとも両方存在）
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
