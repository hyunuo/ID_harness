from pathlib import Path

import pytest

from idharness.expr import Ref, evaluate, parse
from idharness.layout import decode, load_layout_set
from idharness.rules import (Target, check_rules, expand_target, generate_auto_rules,
                             load_rules, normalize_ref, parse_target, source_rank)
from idharness.sources import load_sources

ROOT = Path(__file__).parent.parent
FIX = Path(__file__).parent / "fixtures"
mini_layouts = load_layout_set(FIX / "layouts" / "mini")
sources = load_sources(ROOT / "data" / "sources.yaml")


def test_parse_target_forms():
    assert parse_target("id-ctrl.PSD[*].MP") == Target("id-ctrl", "PSD", "*", "MP", None)
    assert parse_target("id-ctrl.SQES[7:4]") == Target("id-ctrl", "SQES", None, None, (7, 4))
    assert parse_target("id-ns.LBAF[*][7:4]") == Target("id-ns", "LBAF", "*", None, (7, 4))
    assert parse_target("id-ctrl.PSD[1]") == Target("id-ctrl", "PSD", 1, None, None)
    assert parse_target("id-ctrl.VID") == Target("id-ctrl", "VID", None, None, None)
    for bad in ("id-ctrl", "VID", "id-ctrl.", "id-ctrl.A[", "id-ctrl.A[x]", "id-ctrl.A[1:2:3]"):
        with pytest.raises(ValueError):
            parse_target(bad)


def test_auto_rules_for_reserved_and_ascii():
    autos = generate_auto_rules(mini_layouts)
    ids = {r.id for r in autos}
    assert {"AUTO-id-ctrl-RSVD9-RSVD", "AUTO-id-ctrl-OACS-15_4-RSVD",
            "AUTO-id-ctrl-SN-ASCII", "AUTO-id-ns-LBAF-7_4-RSVD",
            "AUTO-id-ctrl-PSD-RSVD1-RSVD"} <= ids
    assert not any("VS" in i for i in ids)
    by = {r.id: r for r in autos}
    r = by["AUTO-id-ctrl-OACS-15_4-RSVD"]
    assert r.expect_src == "zero($)" and r.auto and r.file == "<auto>"
    assert (r.level, r.kind, r.status, r.source) == ("shall", "format", "cross-checked", "nvme-base-2.1")
    assert r.target == Target("id-ctrl", "OACS", None, None, (15, 4))
    assert by["AUTO-id-ns-LBAF-7_4-RSVD"].target == Target("id-ns", "LBAF", "*", None, (7, 4))
    assert by["AUTO-id-ctrl-PSD-RSVD1-RSVD"].target == Target("id-ctrl", "PSD", "*", "RSVD1", None)
    a = by["AUTO-id-ctrl-SN-ASCII"]
    assert a.expect_src == "ascii($) and ljust($)" and a.ref == "Base 2.1 §1.4.2"
    assert check_rules(autos, mini_layouts, sources, {}) == []


def test_mini_rules_load_and_check_clean():
    rules, errs = load_rules(FIX / "rules" / "mini")
    assert errs == []
    assert [r.id for r in rules] == sorted(r.id for r in rules)
    all_rules = rules + generate_auto_rules(mini_layouts)
    assert check_rules(all_rules, mini_layouts, sources, {}) == []
    ocp = next(r for r in rules if r.id == "OCP-CTRL-SQES-MINES")
    assert ocp.overrides == ("NVME-CTRL-SQES-MINES",) and ocp.when is None and ocp.note
    assert next(r for r in rules if r.id == "NVME-CTRL-SQES-MINES").history == ()


def test_load_rules_missing_root(tmp_path):
    assert load_rules(tmp_path / "nope") == ([], [])


def test_check_rules_collects_all_errors():
    rules, load_errs = load_rules(FIX / "rules" / "broken")
    errs = load_errs + check_rules(rules, mini_layouts, sources, {})
    assert len(errs) >= 4
    assert any("SQESS" in e for e in errs)
    assert any("duplicate" in e for e in errs)
    assert any("overrides" in e for e in errs)
    assert all(".yaml" in e for e in errs)


def _rules_from(tmp_path, body):
    (tmp_path / "r.yaml").write_text(body, encoding="utf-8")
    return load_rules(tmp_path)


def _rule(id_, target, expect, extra=""):
    return (f"- id: {id_}\n  source: nvme-base-2.1\n  ref: x\n  target: {target}\n"
            f"  expect: \"{expect}\"\n  level: shall\n  kind: value\n  status: uncertain\n{extra}")


def test_idctrl_rule_cannot_reference_idns(tmp_path):
    rules, le = _rules_from(tmp_path, _rule("X1", "id-ctrl.VID", "id-ns.NLBAF >= 0"))
    assert le == []
    errs = check_rules(rules, mini_layouts, sources, {})
    assert len(errs) == 1 and "X1" in errs[0] and "id-ns" in errs[0]


def test_dollar_i_requires_wildcard_target(tmp_path):
    rules, _ = _rules_from(tmp_path, _rule("X1", "id-ctrl.VID", "$i == 0")
                           + _rule("X2", "id-ctrl.PSD[*].MP", "$i == 0"))
    errs = check_rules(rules, mini_layouts, sources, {})
    assert len(errs) == 1 and "X1" in errs[0] and "$i" in errs[0]


def test_profile_feature_vocab(tmp_path):
    rules, _ = _rules_from(tmp_path, _rule("X1", "id-ctrl.VID", "profile.features.sanitize == true")
                           + _rule("X2", "id-ctrl.VID", "profile.values.foo == 1"))
    errs = check_rules(rules, mini_layouts, sources, {})
    assert len(errs) == 1 and "sanitize" in errs[0]
    assert check_rules(rules, mini_layouts, sources, {"sanitize": {}}) == []


def test_bad_enums_bad_source_policy_and_override_rank(tmp_path):
    body = (_rule("A", "id-ctrl.VID", "$ >= 0").replace("level: shall", "level: must")
            + _rule("B", "id-ctrl.VID", "$ >= 0").replace("source: nvme-base-2.1", "source: nope")
            + _rule("C", "id-ctrl.VID", "$ >= 0").replace("source: nvme-base-2.1", "source: policy-x")
            + _rule("D", "id-ctrl.VID", "$ >= 0", extra="  overrides: [C, MISSING, D]\n"))
    rules, le = _rules_from(tmp_path, body)
    assert le == []
    errs = check_rules(rules, mini_layouts, sources, {})
    assert any(": A: " in e and "level" in e for e in errs)
    assert any("nope" in e for e in errs)
    assert not any(": C: " in e for e in errs)
    assert sum("overrides" in e for e in errs) == 3
    assert source_rank("policy-x", sources) == 30 and source_rank("zzz", sources) is None
    assert source_rank("ocp-2.6", sources) == 20


def test_load_errors_missing_keys_and_bad_yaml(tmp_path):
    (tmp_path / "a.yaml").write_text("- id: Q\n  source: nvme-base-2.1\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("foo: [", encoding="utf-8")
    (tmp_path / "c.yaml").write_text("{a: 1}", encoding="utf-8")
    rules, errs = load_rules(tmp_path)
    assert rules == [] and len(errs) == 3
    assert errs[0].startswith("a.yaml: Q: ") and "target" in errs[0]
    assert all(".yaml" in e for e in errs)


def test_normalize_ref():
    def n(scope, path, bits=None):
        return normalize_ref(Ref(scope, path, bits), mini_layouts)

    assert n("id-ctrl", "OACS", (3, 3)) == Ref("id-ctrl", "OACS", (3, 3))
    assert n("id-ctrl", "PSD", (0, 0)) == Ref("id-ctrl", "PSD[0]", None)
    assert n("id-ctrl", "PSD[1]", None) == Ref("id-ctrl", "PSD[1]", None)
    assert n("id-ctrl", "PSD[0].MP", (3, 0)) == Ref("id-ctrl", "PSD[0].MP", (3, 0))
    assert n("id-ns", "LBAF[2]", (3, 0)) == Ref("id-ns", "LBAF[2]", (3, 0))
    assert n("$", "", (1, 0)) == Ref("$", "", (1, 0))
    assert n("$i", "", None) == Ref("$i", "", None)
    assert n("profile", "features.x", None) == Ref("profile", "features.x", None)
    for scope, path, bits, msg in [
        ("id-ctrl", "NOPE", None, "NOPE"),
        ("id-ctrl", "PSD", (2, 2), "range"),
        ("id-ctrl", "PSD[2]", None, "range"),
        ("id-ctrl", "PSD", None, "index"),
        ("id-ctrl", "PSD[0].XX", None, "XX"),
        ("id-ctrl", "VID[0]", None, "array"),
        ("id-ctrl", "SQES", (8, 0), "width"),
        ("id-ns", "LBAF[0]", (8, 0), "width"),
        ("id-ctrl", "PSD[0].MP", (8, 0), "width"),
        ("id-xx", "A", None, "id-xx"),
    ]:
        with pytest.raises(ValueError, match=msg):
            n(scope, path, bits)


def test_expand_target():
    def ex(s, lay="id-ctrl"):
        return expand_target(parse_target(s), mini_layouts[lay])

    assert ex("id-ctrl.PSD[*].MP") == [("PSD[0].MP", 0, None), ("PSD[1].MP", 1, None)]
    assert ex("id-ctrl.SQES[7:4]") == [("SQES", None, (7, 4))]
    assert ex("id-ctrl.OACS[3]") == [("OACS", None, (3, 3))]
    assert ex("id-ctrl.PSD[1]") == [("PSD[1]", 1, None)]
    assert ex("id-ns.LBAF[*][7:4]", "id-ns") == [(f"LBAF[{i}]", i, (7, 4)) for i in range(3)]
    for bad in ("id-ctrl.NOPE", "id-ctrl.PSD[5]", "id-ctrl.PSD", "id-ctrl.VID[*]",
                "id-ctrl.PSD[*].ZZ", "id-ctrl.SQES[8:0]", "id-ctrl.VID.X"):
        with pytest.raises(ValueError):
            ex(bad)


def test_zero_rule_evaluates_on_decoded_reserved_bytes():
    vals = decode(mini_layouts["id-ctrl"], bytes(16))

    class E:
        def resolve(self, ref):
            return vals["RSVD9"]

    assert evaluate(parse("zero($)"), E()) is True
