"""기존 nvme-cli 텍스트 로그 파서와 baseline 비교 (CHANGED는 정보용)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from idharness.layout import FieldDef, Layout

_LINE = re.compile(r"^(\w+(?:\s+\d+)?)\s*:\s*(.*)$")
_STEM = re.compile(r"^(id-ctrl|id-ns-(\d+))$")
_PAIR = re.compile(r"(\w+):(\S+)")


def parse_nvme_cli_text(text: str) -> dict[str, str]:
    """'key : value' 줄을 읽는다. 키는 소문자, 'ps  0'/'lbaf  2'는 공백 한 칸으로 정규화."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith("NVME ") or line[:1].isspace() or not line.strip():
            continue  # 헤더, verbose 비트 줄, 빈 줄
        m = _LINE.match(line.strip())
        if m:
            out[" ".join(m.group(1).lower().split())] = m.group(2)
    return out


@dataclass(frozen=True)
class Baseline:
    files: dict[tuple[str, int | None], dict[str, str]]
    unmapped: tuple[str, ...] = ()
    aliases: dict = field(default_factory=dict)
    layouts: dict[str, Layout] = field(default_factory=dict)


def _fields(layout: Layout) -> dict[str, FieldDef]:
    out: dict[str, FieldDef] = {}
    for f in layout.fields:
        if f.vendor_specific:
            continue
        if f.count > 1:
            for i in range(f.count):
                out[f"{f.name}[{i}]"] = f
        else:
            out[f.name] = f
    return out


def _unit_for_key(key: str, aliases: dict) -> str:
    m = re.fullmatch(r"(ps|lbaf) (\d+)", key)
    if m:
        return f"{'PSD' if m.group(1) == 'ps' else 'LBAF'}[{m.group(2)}]"
    return (aliases.get("keys") or {}).get(key, key.upper())


def baseline_from_texts(texts: dict[str, str], aliases: dict,
                        layouts: dict[str, Layout]) -> Baseline:
    files: dict[tuple[str, int | None], dict[str, str]] = {}
    unmapped: list[str] = []
    for stem, text in texts.items():
        m = _STEM.match(stem)
        if not m:
            continue
        struct, nsid = ("id-ctrl", None) if m.group(2) is None else ("id-ns", int(m.group(2)))
        parsed = parse_nvme_cli_text(text)
        files[(struct, nsid)] = parsed
        units = _fields(layouts[struct]) if struct in layouts else {}
        for key in parsed:
            if _unit_for_key(key, aliases) not in units:
                unmapped.append(f"{stem}: {key}")
    return Baseline(files, tuple(sorted(unmapped)), aliases, layouts)


def load_baseline(dir: Path, aliases: dict, layouts: dict[str, Layout]) -> Baseline:
    d = Path(dir)
    if not d.is_dir():
        raise ValueError(f"baseline dir not found: {d}")
    texts: dict[str, str] = {}
    for p in sorted(d.glob("*.txt")):
        if _STEM.match(p.stem):
            texts[p.stem] = p.read_text(encoding="utf-8")
    return baseline_from_texts(texts, aliases, layouts)


def _parse_int(s: str, hex_key: bool) -> int | None:
    s = s.strip()
    try:
        if s.lower().startswith("0x") or (hex_key and s):
            return int(s, 16)
        if s.isdigit():
            return int(s)
    except ValueError:
        pass
    return None


def baseline_value(b: Baseline, struct: str, nsid: int | None, unit: str,
                   value: int | bytes) -> tuple[str | None, bool | None]:
    """(원문, 변경 여부). 매핑이 없으면 (None, None), 비교 불가면 (원문, None)."""
    parsed = b.files.get((struct, nsid))
    layout = b.layouts.get(struct)
    if parsed is None or layout is None:
        return None, None
    fdef = _fields(layout).get(unit)
    if fdef is None:
        return None, None
    key = next((k for k in parsed if _unit_for_key(k, b.aliases) == unit), None)
    if key is None:
        return None, None
    raw = parsed[key]
    if key.startswith("ps "):
        return raw, None
    if key.startswith("lbaf ") and isinstance(value, int):
        changed: bool | None = None
        for name, text in _PAIR.findall(raw):
            if name.lower() not in ("lbads", "ms", "rp"):
                continue
            bd = next((x for x in fdef.bits if x.name == name.upper()), None)
            n = _parse_int(text, False)
            if bd is None or n is None:
                continue
            if (value >> bd.lo) & ((1 << (bd.hi - bd.lo + 1)) - 1) != n:
                return raw, True
            changed = False
        return raw, changed
    if fdef.type == "ascii" and isinstance(value, bytes):
        return raw, value.decode("latin-1").strip() != raw.strip()
    if isinstance(value, int):
        n = _parse_int(raw, key in (b.aliases.get("hex_keys") or []))
        return raw, None if n is None else n != value
    return raw, None
