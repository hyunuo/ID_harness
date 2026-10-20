"""출처 레지스트리 로드 (rank로 우선순위 결정)."""
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Source:
    id: str
    title: str
    version: str
    file: str
    rank: int


def load_sources(path: Path) -> dict[str, Source]:
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    out: dict[str, Source] = {}
    for item in doc["sources"]:
        s = Source(
            id=item["id"], title=item["title"], version=str(item["version"]),
            file=item["file"], rank=int(item["rank"]),
        )
        if s.id in out:
            raise ValueError(f"{path}: duplicate source id {s.id}")
        out[s.id] = s
    return out
