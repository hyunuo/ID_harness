import dataclasses
from pathlib import Path

from idharness.layout import (
    check_layout, decode, encode, field_width_bits, load_layout, load_layout_set,
)

MINI = Path("tests/fixtures/layouts/mini")


def test_mini_layout_is_consistent():
    assert check_layout(load_layout(MINI / "id-ctrl.yaml")) == []
    assert check_layout(load_layout(MINI / "id-ns.yaml")) == []


def test_check_layout_reports_gap_and_overlap():
    lay = load_layout(MINI / "id-ctrl.yaml")
    fields = []
    for f in lay.fields:
        if f.name == "VID":
            f = dataclasses.replace(f, size=3)
        if f.name == "RSVD9":
            continue
        fields.append(f)
    broken = dataclasses.replace(lay, fields=tuple(fields))
    errs = check_layout(broken)
    assert any("VID" in e and "overlap" in e for e in errs)
    assert any("gap" in e and "9" in e for e in errs)


def test_check_layout_bit_errors():
    lay = load_layout(MINI / "id-ctrl.yaml")
    sqes = next(f for f in lay.fields if f.name == "SQES")
    bits = sqes.bits + (dataclasses.replace(sqes.bits[0], name="X", hi=8, lo=5),)
    bad = dataclasses.replace(
        lay, fields=tuple(dataclasses.replace(f, bits=bits) if f is sqes else f for f in lay.fields))
    errs = check_layout(bad)
    assert any("SQES" in e and "width" in e for e in errs)
    assert any("SQES" in e and "bit overlap" in e for e in errs)


def test_check_layout_count_not_divisor():
    lay = load_layout(MINI / "id-ns.yaml")
    lbaf = next(f for f in lay.fields if f.name == "LBAF")
    bad = dataclasses.replace(
        lay, fields=tuple(dataclasses.replace(f, count=2) if f is lbaf else f for f in lay.fields))
    assert any("LBAF" in e and "count" in e for e in check_layout(bad))


def test_decode_roundtrip():
    lay = load_layout(MINI / "id-ctrl.yaml")
    raw = encode(lay, {"VID": 0x1E0F, "SN": b"AB12", "SQES": 0x66, "PSD[1].MP": 25})
    d = decode(lay, raw)
    assert d["VID"] == 0x1E0F and d["SN"] == b"AB12" and d["SQES"] == 0x66
    assert d["PSD[1].MP"] == 25 and d["PSD[0].MP"] == 0
    assert len(raw) == 16
    assert d["PSD[1]"] == bytes([25, 0])


def test_decode_uint_array_and_width():
    lay = load_layout(MINI / "id-ns.yaml")
    raw = encode(lay, {"NSZE": 0x01020304, "LBAF[2]": 9})
    assert raw == bytes([4, 3, 2, 1, 0, 0, 0, 9])
    d = decode(lay, raw)
    assert d["LBAF[2]"] == 9 and d["NSZE"] == 0x01020304
    lbaf = next(f for f in lay.fields if f.name == "LBAF")
    assert field_width_bits(lbaf) == 8
    assert field_width_bits(lay.fields[0]) == 32


def test_source_defaults_and_layout_set():
    s = load_layout_set(MINI)
    assert set(s) == {"id-ctrl", "id-ns"}
    assert all(f.source == "nvme-base-2.1" for f in s["id-ctrl"].fields)
    assert all(f.source == "nvm-cs-1.1" for f in s["id-ns"].fields)
    vs = next(f for f in s["id-ctrl"].fields if f.name == "VS")
    assert vs.vendor_specific and not vs.reserved
    assert next(f for f in s["id-ctrl"].fields if f.name == "RSVD9").reserved
