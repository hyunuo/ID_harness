from pathlib import Path

import pytest
import yaml

from idharness.baseline import (baseline_from_texts, baseline_value, load_baseline,
                                parse_nvme_cli_text)
from idharness.engine import Instance, evaluate_run
from idharness.layout import encode, load_layout_set
from idharness.profile import Profile
from idharness.sources import load_sources

ROOT = Path(__file__).parent.parent
FIX = Path(__file__).parent / "fixtures"
L = load_layout_set(FIX / "layouts" / "mini")
ALIASES = yaml.safe_load((ROOT / "data" / "baseline_aliases.yaml").read_text(encoding="utf-8"))
FIX_TXT = (FIX / "baseline" / "id-ctrl.txt").read_text(encoding="utf-8")
B = load_baseline(FIX / "baseline", ALIASES, L)
PROF = Profile("p", "mini", ("nvme-base-2.1",), {}, {})
SOURCES = load_sources(ROOT / "data" / "sources.yaml")


def run(ctrl=None, ns=None, baseline=B):
    insts = []
    if ctrl is not None:
        insts.append(Instance("id-ctrl", None, encode(L["id-ctrl"], ctrl)))
    if ns is not None:
        insts.append(Instance("id-ns", 1, encode(L["id-ns"], ns)))
    return evaluate_run(insts, L, [], PROF, SOURCES, baseline=baseline)


def unit(r, name, struct="id-ctrl"):
    return next(f for f in r.fields if f.struct == struct and f.unit == name)


def test_parse_basic_and_indexed():
    d = parse_nvme_cli_text(FIX_TXT)
    assert d["vid"] == "0x1e0f" and d["ps 0"].startswith("mp:25.00W")
    d2 = parse_nvme_cli_text((FIX / "baseline" / "id-ns-1.txt").read_text(encoding="utf-8"))
    assert d2["lbaf 1"].startswith("ms:8")


def test_parse_ignores_verbose_and_unknown_lines():
    d = parse_nvme_cli_text("NVME Identify Controller:\n\nvid : 0x1\n  [4:4] : 0x1\tFoo\nzzz : 3\n")
    assert d == {"vid": "0x1", "zzz": "3"}
    b = baseline_from_texts({"id-ctrl": "vid : 0x1\nzzz : 3\n"}, ALIASES, L)
    assert b.unmapped == ("id-ctrl: zzz",)


def test_load_baseline_missing_dir_and_unmapped_sorted(tmp_path):
    with pytest.raises(ValueError, match="nope"):
        load_baseline(tmp_path / "nope", ALIASES, L)
    b = baseline_from_texts({"id-ctrl": "b : 1\na : 2\n", "id-ns-3": "x : 1\n",
                             "other": "y : 1\n"}, ALIASES, L)
    assert b.unmapped == ("id-ctrl: a", "id-ctrl: b", "id-ns-3: x")
    b2 = baseline_from_texts({"id-ctrl": "vid : 1\n"}, ALIASES, {})
    assert b2.unmapped == ("id-ctrl: vid",)


def test_changed_flag():
    r = run({"VID": 0x1E0F, "SQES": 0x44})
    assert "CHANGED" in unit(r, "SQES").flags and "CHANGED" not in unit(r, "VID").flags
    assert unit(r, "SQES").baseline == "0x66"
    assert unit(r, "VID").baseline == "0x1e0f"
    assert unit(r, "SQES").verdict == "NO_RULE"
    assert r.baseline_unmapped == ("id-ctrl: frmw",)
    assert unit(run({"VID": 1}, baseline=None), "VID").baseline is None


def test_ascii_trim_compare():
    r = run({"SN": b"AB12"})
    assert "CHANGED" not in unit(r, "SN").flags and unit(r, "SN").baseline == "AB12"
    r = run({"SN": b"AB13"})
    assert "CHANGED" in unit(r, "SN").flags


def test_lbaf_compare_uses_bits():
    r = run(ns={"LBAF[0]": 9, "LBAF[1]": 12, "LBAF[2]": 9})
    assert "CHANGED" not in unit(r, "LBAF[0]", "id-ns").flags
    assert "CHANGED" not in unit(r, "LBAF[1]", "id-ns").flags
    assert unit(r, "LBAF[2]", "id-ns").baseline is None
    r = run(ns={"LBAF[0]": 10, "LBAF[1]": 12})
    assert "CHANGED" in unit(r, "LBAF[0]", "id-ns").flags
    # ms=8 in the log has no MS bit in the mini layout, so only lbads is compared
    assert "CHANGED" not in unit(r, "LBAF[1]", "id-ns").flags


def test_ps_not_compared_and_parse_failure():
    r = run({"VID": 1})
    assert unit(r, "PSD[0]").baseline.startswith("mp:") and "CHANGED" not in unit(r, "PSD[0]").flags
    b = baseline_from_texts({"id-ctrl": "vid : garbage\n"}, ALIASES, L)
    assert baseline_value(b, "id-ctrl", None, "VID", 1) == ("garbage", None)
    assert baseline_value(b, "id-ctrl", None, "SQES", 1) == (None, None)
