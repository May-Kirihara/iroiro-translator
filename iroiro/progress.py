"""進捗ファイル（progress.json）の並行安全な読み書き。

Plan §5.8 / §6.5 で規定される ``ProgressWriter`` と ``ProgressData`` を実装する。

設計の要点:
    * 並行安全: ``asyncio.Lock`` で ``mark_done`` / ``mark_failed`` を直列化。
    * 原子的書き込み: ``tmp -> os.replace`` でクラッシュ時にも本ファイルが破損しない。
    * ファイル命名: ``<input>.iroiro-progress.json``（``<input>`` は入力XMLのフルパス）。
    * ``input_path`` メタ情報: progress_path でなく入力XMLのパスを記録する（Plan §5.8 v0.3）。
    * ``input_hash`` 不一致 / JSON decode error は ``ValueError`` で停止する（自動修復しない）。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ProgressData:
    """``load_existing`` の戻り値（Plan §6.5）。

    Attributes:
        entries: ``index -> dest`` の辞書（再開時に再利用される訳文）。
        failed: 失敗した index のリスト（再試行せず保持）。
        input_hash: 入力XMLの SHA256。
        api_base: 使用した API エンドポイント。
        model: 使用したモデル名。
        skip_records_fingerprint: 使用した skip_records の fingerprint（v0.2 追加）。
            v0.1 形式の progress.json から読み込んだ場合は ``""``。
    """

    entries: dict[int, str]
    failed: list[int]
    input_hash: str
    api_base: str
    model: str
    skip_records_fingerprint: str


def compute_input_hash(path: Path) -> str:
    """入力XMLの SHA256 を計算する（hex 文字列、64文字）。

    Args:
        path: 入力XMLのパス。
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_skip_records_fingerprint(skip_records: frozenset[str]) -> str:
    """skip_records の SHA256（hex）を計算する（Plan §5.4）。

    ソートしてから計算することで順序に依存しない。
    **空集合の場合は空文字列 ``""`` を返す**（v0.1 progress.json との互換性のため）。
    ※ SHA256(b"") = ``"e3b0c442..."`` と区別するため、空集合は特例扱い。
    """
    if not skip_records:
        return ""
    canonical = "\n".join(sorted(skip_records))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ProgressWriter:
    """``progress.json`` への並行安全な読み書きを行う。

    ファイル命名: ``<input>.iroiro-progress.json``。

    並行安全性: ``mark_done`` / ``mark_failed`` は ``asyncio.Lock`` で直列化される。
    同一インスタンス内の ``_data`` を更新しつつ ``_flush`` で原子的書き込みを行う。

    再開: ``load_existing`` で既存ファイルを読み込む。
    ファイル不在は ``None``。JSON decode error / hash 不一致は ``ValueError``。
    """

    def __init__(
        self,
        progress_path: Path,
        input_path: Path,
        input_hash: str,
        api_base: str,
        model: str,
        skip_records_fingerprint: str,
    ) -> None:
        self._path = progress_path
        self._input_path = input_path
        self._input_hash = input_hash
        self._api_base = api_base
        self._model = model
        self._skip_records_fingerprint = skip_records_fingerprint
        self._lock = asyncio.Lock()
        self._data: dict[str, object] = {
            "input_path": str(input_path),
            "input_hash": input_hash,
            "api_base": api_base,
            "model": model,
            "skip_records_fingerprint": skip_records_fingerprint,
            "entries": {},
            "failed": [],
        }

    async def mark_done(self, index: int, dest: str) -> None:
        """``index`` を訳文 ``dest`` で完了扱いにする。

        entries dict に ``str(index) -> dest`` をセットして ``_flush`` する。

        v0.4（Plan 004 §4.6）: ``failed`` に同じ ``index`` があれば削除する。
        これにより ``retry_failed=True`` で再試行して成功した場合でも
        **不変性** ``entries ∩ failed = ∅`` を保証する。progress.json と
        「Resuming: X translated, Y failed」メッセージが常に整合する。

        v0.4 Codex review 対応（N1）: ``list.remove(index)`` は最初に見つかった
        要素しか消さないため、``failed=[5, 5]`` のような重複がある progress.json
        （v0.3 以前生成）との整合性で **同 index を全件削除** する必要がある。
        リスト内包表記で再構築することでこれを保証する。
        """
        async with self._lock:
            entries = self._data["entries"]
            assert isinstance(entries, dict)
            entries[str(index)] = dest
            # v0.4: retry 成功時に failed から index を全件削除（不変性保証）
            # ※ list.remove(index) は最初の1件しか消さないため、既存重複 progress.json
            #    （v0.3 以前生成）との整合性で全件削除が必要
            failed = self._data["failed"]
            assert isinstance(failed, list)
            if index in failed:
                self._data["failed"] = [x for x in failed if x != index]
            self._flush()

    async def mark_failed(self, index: int) -> None:
        """``index`` を失敗リストに追記する。

        v0.4（Plan 004 §4.6）: 重複チェックを追加。``failed`` に既に ``index`` が
        含まれている場合は append しない。``retry_failed=True`` で再試行 → 再失敗
        を繰り返しても同じ ``index`` が重複して progress.json に書き込まれるのを
        防止する（failed リストの膨張防止）。
        """
        async with self._lock:
            failed = self._data["failed"]
            assert isinstance(failed, list)
            if index not in failed:  # v0.4: 重複チェック
                failed.append(index)
            self._flush()

    def _flush(self) -> None:
        """原子的書き込み: tmp -> os.replace。

        ``asyncio.Lock`` 内で呼ばれるため同期 I/O で安全。
        ``tmp`` パスは ``<progress>.json.tmp``。前回クラッシュの残存 ``.tmp`` は上書きされる。
        """
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        payload = json.dumps(self._data, ensure_ascii=False, indent=2)
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, self._path)

    def load_existing(self) -> ProgressData | None:
        """既存の ``progress.json`` を読み込む。

        成功時は戻り値の ``ProgressData`` を返すと同時に、読み込んだ
        ``entries`` / ``failed`` を ``self._data`` へ統合する。これにより
        resume 後の ``mark_done`` / ``mark_failed`` が既存翻訳を保持した
        まま追記される（既存 entries が ``_flush`` で消失するのを防ぐ）。

        Returns:
            ``ProgressData``。ファイルが存在しない場合は ``None``。

        Raises:
            ValueError: JSON decode error、``input_hash`` が一致しない場合、
                または ``skip_records_fingerprint`` が現在の設定と一致しない場合。
                自動修復は行わず、ユーザーにファイル削除を促すことを想定。
        """
        if not self._path.exists():
            return None

        try:
            raw_text = self._path.read_text(encoding="utf-8")
        except OSError as e:
            raise ValueError(f"progress.json read error: {e}") from e

        try:
            raw = json.loads(raw_text)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"progress.json is corrupted (JSON decode error): {e}. "
                f"Please remove {self._path} and re-run."
            ) from e

        if not isinstance(raw, dict):
            raise ValueError(f"progress.json root is not an object: {type(raw).__name__}")

        existing_hash = raw.get("input_hash")
        if existing_hash != self._input_hash:
            raise ValueError(
                f"input_hash mismatch: progress.json has {existing_hash!r}, "
                f"current input is {self._input_hash!r}. "
                f"Please remove {self._path} if the input file has changed."
            )

        # v0.2: skip_records_fingerprint 検証（Plan §5.4）。
        # v0.1 形式の progress.json は同フィールドを持たないため ``""`` と解釈する。
        # 現在の fingerprint と一致しない場合は ValueError で停止（input_hash と同じパターン）。
        existing_skip_fp = str(raw.get("skip_records_fingerprint", ""))
        if existing_skip_fp != self._skip_records_fingerprint:
            raise ValueError(
                f"skip_records fingerprint mismatch: "
                f"progress.json has {existing_skip_fp!r}, "
                f"current skip_records is {self._skip_records_fingerprint!r}. "
                f"Please remove {self._path} if skip records have changed."
            )

        raw_entries = raw.get("entries", {})
        entries: dict[int, str] = {}
        if isinstance(raw_entries, dict):
            for k, v in raw_entries.items():
                try:
                    entries[int(k)] = str(v)
                except (TypeError, ValueError):
                    continue

        raw_failed = raw.get("failed", [])
        failed: list[int] = []
        if isinstance(raw_failed, list):
            for x in raw_failed:
                try:
                    failed.append(int(x))
                except (TypeError, ValueError):
                    continue

        # ★ critical fix: 既存の entries / failed を self._data に統合
        # これにより resume 後の mark_done / mark_failed が既存翻訳を
        # 保持したまま追加される（v0.1 からの潜在バグ修正）。
        # entries は dict[int, str] だが self._data["entries"] は str キーを
        # 想定（mark_done が str(index) で書き込むため）へ変換する。
        self._data["entries"] = {str(k): v for k, v in entries.items()}
        self._data["failed"] = list(failed)

        return ProgressData(
            entries=entries,
            failed=failed,
            input_hash=str(existing_hash),
            api_base=str(raw.get("api_base", "")),
            model=str(raw.get("model", "")),
            skip_records_fingerprint=existing_skip_fp,
        )
