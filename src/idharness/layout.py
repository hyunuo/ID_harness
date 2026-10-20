"""레이아웃 모델, 로드, 정합성 검사, decode/encode."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

FieldType = Literal["uint", "ascii", "bytes", "struct"]


@dataclass(frozen=True)
class BitDef:
    name: str
    hi: int
    lo: int
    reserved: bool = False
    title: str = ""


@dataclass(frozen=True)
class FieldDef:
    name: str
    offset: int
    size: int
    type: FieldType
    title: str = ""
    ref: str = ""
    source: str = ""
    reserved: bool = False
    vendor_specific: bool = False
    bits: tuple[BitDef, ...] = ()
    count: int = 1
    element: tuple[FieldDef, ...] = ()


@dataclass(frozen=True)
class Layout:
    structure: str
    size: int
    source: str
    status: str
    fields: tuple[FieldDef, ...]


def _parse_range(text: str | int) -> tuple[int, int]:
    s = str(text)
    if ":" in s:
        hi, lo = s.split(":")
        return int(hi), int(lo)
    return int(s), int(s)


def _parse_bit(d: dict) -> BitDef:
    hi, lo = _parse_range(d["range"])
    return BitDef(name=d["name"], hi=hi, lo=lo, reserved=bool(d.get("reserved", False)),
                  title=d.get("title", ""))


def _parse_field(d: dict, default_source: str) -> FieldDef:
    source = d.get("source") or default_source
    return FieldDef(
        name=d["name"], offset=int(d["offset"]), size=int(d["size"]), type=d["type"],
        title=d.get("title", ""), ref=d.get("ref", ""), source=source,
        reserved=bool(d.get("reserved", False)),
        vendor_specific=bool(d.get("vendor_specific", False)),
        bits=tuple(_parse_bit(b) for b in d.get("bits", [])),
        count=int(d.get("count", 1)),
        element=tuple(_parse_field(e, source) for e in d.get("element", [])),
    )


def load_layout(path: Path) -> Layout:
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    source = doc.get("source", "")
    fields = sorted((_parse_field(f, source) for f in doc["fields"]), key=lambda f: f.offset)
    return Layout(structure=doc["structure"], size=int(doc["size"]), source=source,
                  status=doc.get("status", ""), fields=tuple(fields))


def load_layout_set(root: Path) -> dict[str, Layout]:
    out: dict[str, Layout] = {}
    for p in sorted(Path(root).glob("*.yaml")):
        lay = load_layout(p)
        out[lay.structure] = lay
    return out


def field_width_bits(field: FieldDef) -> int:
    if field.count > 1:
        return field.size // field.count * 8
    return field.size * 8


def _check_bits(f: FieldDef) -> list[str]:
    errs: list[str] = []
    width = field_width_bits(f)
    for b in f.bits:
        if b.hi < b.lo or b.lo < 0:
            errs.append(f"{f.name}.{b.name}: invalid bit range {b.hi}:{b.lo}")
        elif b.hi >= width:
            errs.append(f"{f.name}.{b.name}: bit {b.hi}:{b.lo} exceeds field width {width}")
    bits = sorted(f.bits, key=lambda b: (b.lo, b.hi))
    for i, a in enumerate(bits):
        for b in bits[i + 1:]:
            if b.lo <= a.hi:
                errs.append(f"{f.name}: bit overlap between {a.name} and {b.name}")
    return errs


def _check_span(fields: tuple[FieldDef, ...], size: int, where: str) -> list[str]:
    errs: list[str] = []
    pos = 0
    prev: FieldDef | None = None
    for f in sorted(fields, key=lambda f: f.offset):
        if f.offset < pos:
            errs.append(f"{where}{f.name}: overlap with {prev.name} at offset {f.offset}")
        elif f.offset > pos:
            errs.append(f"{where}gap at {pos}..{f.offset - 1} before {f.name}")
        if f.offset + f.size > pos:
            pos = f.offset + f.size
            prev = f
    if pos > size:
        errs.append(f"{where}{prev.name}: exceeds structure size {size}")
    elif pos < size:
        errs.append(f"{where}gap at {pos}..{size - 1} (trailing)")
    return errs


def check_layout(layout: Layout) -> list[str]:
    errs = _check_span(layout.fields, layout.size, "")
    for f in layout.fields:
        if f.count > 1 and f.size % f.count != 0:
            errs.append(f"{f.name}: size {f.size} not divisible by count {f.count}")
            continue
        errs.extend(_check_bits(f))
        if f.element:
            esize = f.size // f.count if f.count > 1 else f.size
            errs.extend(_check_span(f.element, esize, f"{f.name}[]."))
            for e in f.element:
                errs.extend(f"{f.name}[].{m}" for m in _check_bits(e))
    return errs


def _decode_one(f: FieldDef, raw: bytes) -> int | bytes:
    if f.type == "uint":
        return int.from_bytes(raw, "little")
    return bytes(raw)


def _items(f: FieldDef):
    """(key, offset, size, element_fields) for each logical item of a top-level field."""
    if f.count > 1:
        esize = f.size // f.count
        for i in range(f.count):
            yield f"{f.name}[{i}]", f.offset + i * esize, esize
    else:
        yield f.name, f.offset, f.size


def decode(layout: Layout, data: bytes) -> dict[str, int | bytes]:
    out: dict[str, int | bytes] = {}
    for f in layout.fields:
        for key, off, size in _items(f):
            chunk = data[off:off + size]
            if f.type == "struct":
                out[key] = bytes(chunk)
                for e in f.element:
                    out[f"{key}.{e.name}"] = _decode_one(e, chunk[e.offset:e.offset + e.size])
            else:
                out[key] = _decode_one(f, chunk)
    return out


def _encode_one(f: FieldDef, value: int | bytes, size: int) -> bytes:
    if isinstance(value, int):
        return value.to_bytes(size, "little")
    if len(value) > size:
        raise ValueError(f"{f.name}: value of {len(value)} bytes exceeds size {size}")
    return bytes(value).ljust(size, b"\x00")


def encode(layout: Layout, values: dict[str, int | bytes]) -> bytes:
    buf = bytearray(layout.size)
    for f in layout.fields:
        for key, off, size in _items(f):
            if key in values:
                buf[off:off + size] = _encode_one(f, values[key], size)
            if f.type == "struct":
                for e in f.element:
                    sub = f"{key}.{e.name}"
                    if sub in values:
                        o = off + e.offset
                        buf[o:o + e.size] = _encode_one(e, values[sub], e.size)
    return bytes(buf)
