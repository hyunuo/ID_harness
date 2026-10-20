"""제품 정보(profile) 로드: extends 체인 병합, features 어휘 검증."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Profile:
    name: str
    layout_set: str
    specs: tuple[str, ...]
    features: dict[str, bool]
    values: dict[str, int | str]


def _read(name: str, root: Path) -> dict:
    path = Path(root) / f"{name}.yaml"
    if not path.is_file():
        raise ValueError(f"profile not found: {path}")
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"{path}: profile must be a mapping")
    return doc


def _merged(name: str, root: Path, chain: tuple[str, ...]) -> dict:
    if name in chain:
        raise ValueError(f"profile extends cycle: {' -> '.join(chain + (name,))}")
    doc = _read(name, root)
    parent = doc.get("extends")
    out: dict = _merged(str(parent), root, chain + (name,)) if parent else {
        "features": {}, "values": {}}
    for k, v in doc.items():
        if k == "extends":
            continue
        if k in ("features", "values"):
            out[k] = {**out.get(k, {}), **(v or {})}
        else:
            out[k] = v
    return out


def load_profile(name: str, root: Path, features_vocab: dict) -> Profile:
    doc = _merged(name, Path(root), ())
    features = dict(doc.get("features", {}))
    for key in features:
        if key not in features_vocab:
            raise ValueError(f"profile {name}: unknown feature {key!r}")
    return Profile(
        name=name,
        layout_set=str(doc.get("layout_set", "")),
        specs=tuple(doc.get("specs", ())),
        features=features,
        values=dict(doc.get("values", {})),
    )
