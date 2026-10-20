"""run 폴더 로드: meta.json과 *.bin (크기 검증)."""
from __future__ import annotations

import json
import re
from pathlib import Path

from idharness.engine import Instance
from idharness.layout import Layout

_BIN = re.compile(r"^(id-[a-z]+(?:-[a-z]+)*?)(?:-(\d+))?\.bin$")


class RunLoadError(Exception):
    pass


def load_run(run_dir: Path, layouts: dict[str, Layout]) -> tuple[dict, list[Instance]]:
    run_dir = Path(run_dir)
    meta_path = run_dir / "meta.json"
    if not meta_path.is_file():
        raise RunLoadError(f"meta.json 없음: {meta_path}")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as e:
        raise RunLoadError(f"meta.json 읽기 실패: {meta_path}: {e}") from e
    if not isinstance(meta, dict):
        raise RunLoadError(f"meta.json은 객체여야 함: {meta_path}")

    instances: list[Instance] = []
    skipped: list[str] = []
    for p in sorted(run_dir.glob("*.bin")):
        m = _BIN.match(p.name)
        if not m:
            skipped.append(p.name)
            continue
        struct = m.group(1)
        nsid = int(m.group(2)) if m.group(2) is not None else None
        layout = layouts.get(struct)
        if layout is None:
            skipped.append(p.name)
            continue
        data = p.read_bytes()
        if len(data) != layout.size:
            raise RunLoadError(
                f"{p.name}: 크기 불일치 (실제 {len(data)} bytes, 기대 {layout.size} bytes)")
        instances.append(Instance(struct, nsid, data))
    instances.sort(key=lambda i: (i.struct != "id-ctrl", i.struct,
                                  -1 if i.nsid is None else i.nsid))
    meta["skipped"] = sorted(skipped)
    return meta, instances
