import json
from pathlib import Path

import pytest

from idharness.layout import load_layout_set
from idharness.runs import RunLoadError, load_run

MINI = load_layout_set(Path(__file__).parent / "fixtures" / "layouts" / "mini")
META = {"host": "h", "device": "/dev/nvme0", "nvme_version": "2.x",
        "collected_at": "2026-01-01T00:00:00", "nsids": [1]}


def make_run(path: Path, files: dict, meta=True):
    if meta:
        (path / "meta.json").write_text(json.dumps(META), encoding="utf-8")
    for name, data in files.items():
        (path / name).write_bytes(data)


def test_load_run_rejects_wrong_size(tmp_path):
    make_run(tmp_path, {"id-ctrl.bin": b"\x00" * 15})
    with pytest.raises(RunLoadError, match=r"id-ctrl\.bin.*15.*16"):
        load_run(tmp_path, MINI)


def test_load_run_skips_struct_without_layout(tmp_path):
    make_run(tmp_path, {"id-ctrl.bin": b"\x00" * 16, "id-zz.bin": b"\x00" * 4})
    meta, insts = load_run(tmp_path, MINI)
    assert [i.struct for i in insts] == ["id-ctrl"] and meta["skipped"] == ["id-zz.bin"]


def test_load_run_missing_meta(tmp_path):
    make_run(tmp_path, {"id-ctrl.bin": b"\x00" * 16}, meta=False)
    with pytest.raises(RunLoadError, match="meta.json"):
        load_run(tmp_path, MINI)


def test_load_run_ns_nsid_and_order(tmp_path):
    make_run(tmp_path, {"id-ns-2.bin": b"\x00" * 8, "id-ns-1.bin": b"\x00" * 8,
                        "id-ctrl.bin": b"\x00" * 16})
    meta, insts = load_run(tmp_path, MINI)
    assert [(i.struct, i.nsid) for i in insts] == [("id-ctrl", None), ("id-ns", 1), ("id-ns", 2)]
    assert meta["skipped"] == []
