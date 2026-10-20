from pathlib import Path

from idharness.engine import Instance, compute_coverage, evaluate_run
from idharness.layout import encode, load_layout_set
from idharness.profile import Profile
from idharness.rules import _build_rule
from idharness.sources import load_sources

ROOT = Path(__file__).parent.parent
FIX = Path(__file__).parent / "fixtures"
L = load_layout_set(FIX / "layouts" / "mini")
SOURCES = load_sources(ROOT / "data" / "sources.yaml")
ALL_SPECS = ("nvme-base-2.1", "nvm-cs-1.1", "ocp-2.6")

NVME = "nvme-base-2.1"
OCP = "ocp-2.6"


def R(id, target, expect, source=NVME, level="shall", kind="value", when=None,
      status="cross-checked", overrides=None):
    item = {"id": id, "source": source, "ref": "x", "target": target, "expect": expect,
            "level": level, "kind": kind, "status": status}
    if when is not None:
        item["when"] = when
    if overrides:
        item["overrides"] = overrides
    return _build_rule(item, "t.yaml")


def prof(specs=ALL_SPECS, features=None, values=None):
    return Profile("p", "mini", tuple(specs), features or {}, values or {})


def run(ctrl=None, rules=(), ns=None, nsid=1, profile=None):
    insts = []
    if ctrl is not None:
        insts.append(Instance("id-ctrl", None, encode(L["id-ctrl"], ctrl)))
    if ns is not None:
        insts.append(Instance("id-ns", nsid, encode(L["id-ns"], ns)))
    return evaluate_run(insts, L, list(rules), profile or prof(), SOURCES)


def unit(r, name, struct="id-ctrl"):
    return next(f for f in r.fields if f.struct == struct and f.unit == name)


def outs(u, rule_id):
    return [o for o in u.outcomes if o.rule_id == rule_id]


N1 = R("N1", "id-ctrl.SQES[7:4]", "$ == 6")


def test_value_rule_pass_and_fail():
    assert unit(run({"SQES": 0x66}, [N1]), "SQES").verdict == "PASS"
    r = run({"SQES": 0x44}, [N1])
    u = unit(r, "SQES")
    assert u.verdict == "FAIL"
    o = outs(u, "N1")[0]
    assert (o.result, o.actual, o.target_path, o.source) == ("fail", 4, "SQES[7:4]", NVME)


def test_format_only_is_pass_format():
    r = run({}, [])
    assert unit(r, "RSVD9").verdict == "PASS_FORMAT"
    assert unit(r, "VID").verdict == "NO_RULE"
    assert unit(r, "VID").flags == frozenset()
    assert unit(r, "PSD[0]").verdict == "PASS_FORMAT"
    r = run({"RSVD9": b"\x01"}, [])
    assert unit(r, "RSVD9").verdict == "FAIL"


def test_when_relation_b_gates_a():
    rule = R("W1", "id-ctrl.VID", "$ != 0", when="id-ctrl.OACS[3] == 1")
    u = unit(run({"OACS": 0, "VID": 0}, [rule]), "VID")
    assert outs(u, "W1")[0].result == "na" and u.verdict == "NO_RULE"
    u = unit(run({"OACS": 8, "VID": 0}, [rule]), "VID")
    assert u.verdict == "FAIL"
    u = unit(run({"OACS": 8, "VID": 5}, [rule]), "VID")
    assert u.verdict == "PASS"


def test_should_is_warn():
    rule = R("S1", "id-ctrl.VID", "$ != 0", level="should")
    assert unit(run({"VID": 0}, [rule]), "VID").verdict == "WARN"
    assert unit(run({"VID": 1}, [rule]), "VID").verdict == "PASS"
    # shall fail beats should fail
    shall = R("S0", "id-ctrl.VID", "$ == 7")
    assert unit(run({"VID": 0}, [rule, shall]), "VID").verdict == "FAIL"


def test_explicit_override_drops_lower():
    nvme = R("N4", "id-ctrl.SQES[7:4]", "$ == 4")
    ocp = R("O6", "id-ctrl.SQES[7:4]", "$ == 6", source=OCP, overrides=["N4"])
    u = unit(run({"SQES": 0x66}, [nvme, ocp]), "SQES")
    assert u.verdict == "PASS" and "OVERRIDDEN" in u.flags
    o = outs(u, "N4")[0]
    assert o.result == "overridden" and o.actual == 6
    assert "CONFLICT" not in u.flags


def test_override_inactive_when_when_false():
    nvme = R("N4", "id-ctrl.SQES[7:4]", "$ == 6")
    ocp = R("O6", "id-ctrl.SQES[7:4]", "$ == 6", source=OCP, overrides=["N4"],
            when="id-ctrl.VID == 1")
    u = unit(run({"SQES": 0x66, "VID": 0}, [nvme, ocp]), "SQES")
    assert outs(u, "N4")[0].result == "pass" and "OVERRIDDEN" not in u.flags


def test_override_is_instance_level():
    # overrider targets a different field; N-rule outcomes in the instance are all overridden
    nvme = R("N1", "id-ctrl.VID", "$ == 1")
    ocp = R("O1", "id-ctrl.SQES[7:4]", "$ == 6", source=OCP, overrides=["N1"])
    r = run({"SQES": 0x66, "VID": 9}, [nvme, ocp])
    u = unit(r, "VID")
    assert outs(u, "N1")[0].result == "overridden" and "OVERRIDDEN" in u.flags
    assert u.verdict == "NO_RULE"


def test_cross_source_contradiction_flags_conflict():
    nvme = R("N4", "id-ctrl.SQES[7:4]", "$ == 4")
    ocp = R("O6", "id-ctrl.SQES[7:4]", "$ == 6", source=OCP)
    r = run({"SQES": 0x66}, [nvme, ocp])
    u = unit(r, "SQES")
    assert u.verdict == "FAIL" and "CONFLICT" in u.flags
    assert r.db_errors == ()


def test_same_source_contradiction_is_db_error():
    a = R("A1", "id-ctrl.SQES[7:4]", "$ == 4")
    b = R("A2", "id-ctrl.SQES[7:4]", "$ == 6")
    r = run({"SQES": 0x66}, [a, b])
    assert r.db_errors == ("same-source contradiction: A1,A2",)
    assert "CONFLICT" not in unit(r, "SQES").flags


def test_cumulative_rules_not_conflict():
    nvme = R("N7", "id-ctrl.SQES[7:4]", "$ <= 7")
    ocp = R("O6", "id-ctrl.SQES[7:4]", "$ == 6", source=OCP)
    r = run({"SQES": 0x56}, [nvme, ocp])
    u = unit(r, "SQES")
    assert u.verdict == "FAIL" and "CONFLICT" not in u.flags and r.db_errors == ()


def test_missing_profile_key_is_unknown_not_pass():
    rule = R("R-NSM", "id-ctrl.OACS", "$ == 1", when="profile.features.nsm")
    r = run({"OACS": 0}, [rule])
    u = unit(r, "OACS")
    assert u.verdict != "PASS" and "UNKNOWN" in u.flags
    assert r.unknown_keys["profile.features.nsm"] == ("R-NSM",)
    o = outs(u, "R-NSM")[0]
    assert o.result == "unknown" and o.reason == "profile.features.nsm"
    # present feature: evaluates normally
    r = run({"OACS": 0}, [rule], profile=prof(features={"nsm": True}))
    assert unit(r, "OACS").verdict == "FAIL" and r.unknown_keys == {}
    r = run({"OACS": 0}, [rule], profile=prof(features={"nsm": False}))
    assert outs(unit(r, "OACS"), "R-NSM")[0].result == "na"


def test_profile_values_ref():
    rule = R("PV", "id-ctrl.VID", "$ == profile.values.vid")
    assert unit(run({"VID": 5}, [rule], profile=prof(values={"vid": 5})), "VID").verdict == "PASS"
    r = run({"VID": 5}, [rule])
    assert r.unknown_keys == {"profile.values.vid": ("PV",)}


def test_array_star_binds_index():
    rule = R("L1", "id-ns.LBAF[*]", "$ == 0", when="$i > id-ns.NLBAF")
    r = run(ns={"NLBAF": 1, "LBAF[2]": 9})
    u2 = unit(r, "LBAF[2]", "id-ns")
    assert u2.verdict == "PASS_FORMAT"  # no rules yet: only auto
    r = evaluate_run([Instance("id-ns", 1, encode(L["id-ns"], {"NLBAF": 1, "LBAF[2]": 9}))],
                     L, [rule], prof(), SOURCES)
    assert unit(r, "LBAF[2]", "id-ns").verdict == "FAIL"
    assert outs(unit(r, "LBAF[1]", "id-ns"), "L1")[0].result == "na"
    assert outs(unit(r, "LBAF[0]", "id-ns"), "L1")[0].result == "na"
    assert outs(unit(r, "LBAF[2]", "id-ns"), "L1")[0].target_path == "LBAF[2]"


def test_idns_references_idctrl():
    rule = R("X1", "id-ns.NLBAF", "$ <= id-ctrl.SQES[3:0]", source="nvm-cs-1.1")
    r = run({"SQES": 0x03}, [rule], ns={"NLBAF": 2})
    assert unit(r, "NLBAF", "id-ns").verdict == "PASS"
    r = run({"SQES": 0x01}, [rule], ns={"NLBAF": 2})
    assert unit(r, "NLBAF", "id-ns").verdict == "FAIL"
    # no id-ctrl instance: unknown naming the struct
    r = run(None, [rule], ns={"NLBAF": 2})
    u = unit(r, "NLBAF", "id-ns")
    assert u.verdict != "PASS" and "UNKNOWN" in u.flags
    assert r.unknown_keys == {"id-ctrl": ("X1",)}


def test_uncertain_flag():
    rule = R("U1", "id-ctrl.VID", "$ == 1", status="uncertain")
    u = unit(run({"VID": 1}, [rule]), "VID")
    assert u.verdict == "PASS" and "UNCERTAIN" in u.flags
    u = unit(run({"VID": 2}, [rule]), "VID")
    assert u.verdict == "FAIL" and "UNCERTAIN" in u.flags
    rule_na = R("U2", "id-ctrl.VID", "$ == 1", status="uncertain", when="id-ctrl.OACS == 1")
    assert "UNCERTAIN" not in unit(run({"VID": 2}, [rule_na]), "VID").flags


def test_rules_outside_profile_specs_ignored():
    ocp = R("O6", "id-ctrl.SQES[7:4]", "$ == 6", source=OCP)
    r = run({"SQES": 0x44}, [ocp], profile=prof(specs=(NVME,)))
    u = unit(r, "SQES")
    assert u.verdict == "NO_RULE" and u.outcomes == ()
    # auto rules by their field's source: nvm-cs auto rules dropped when not in specs
    r = run(ns={"LBAF[0]": 0xF0}, profile=prof(specs=(NVME,)))
    assert unit(r, "LBAF[0]", "id-ns").verdict == "NO_RULE"
    r = run(ns={"LBAF[0]": 0xF0})
    assert unit(r, "LBAF[0]", "id-ns").verdict == "FAIL"


def test_vendor_specific_excluded():
    r = run({})
    assert "VS" not in {f.unit for f in r.fields if f.struct == "id-ctrl"}
    assert r.vendor_specific_skipped == 1


def test_runtime_expr_error_is_unknown_and_db_error():
    rule = R("E1", "id-ctrl.SN", "$ == 3")  # bytes vs int
    r = run({}, [rule])
    u = unit(r, "SN")
    o = outs(u, "E1")[0]
    assert o.result == "unknown" and o.reason.startswith("식 오류: ")
    assert u.verdict != "PASS" and "UNKNOWN" in u.flags
    assert len(r.db_errors) == 1
    assert r.db_errors[0].startswith("t.yaml: E1: runtime expr error: ")
    assert r.unknown_keys == {}
    # when error
    w = R("E2", "id-ctrl.VID", "$ == 0", when="id-ctrl.SN == 1")
    r = run({}, [w])
    assert outs(unit(r, "VID"), "E2")[0].result == "unknown"
    assert r.db_errors[0].startswith("t.yaml: E2: runtime expr error: ")


def test_non_bool_result_is_not_pass():
    rule = R("B1", "id-ctrl.VID", "$ + 1")
    r = run({"VID": 1}, [rule])
    assert outs(unit(r, "VID"), "B1")[0].result == "unknown"
    assert unit(r, "VID").verdict != "PASS" and len(r.db_errors) == 1


def test_dollar_is_sliced_and_struct_subfield():
    rule = R("P1", "id-ctrl.PSD[*].MP", "$ == $i + 1")
    r = run({"PSD[0].MP": 1, "PSD[1].MP": 3}, [rule])
    assert unit(r, "PSD[0]").verdict == "PASS"
    u1 = unit(r, "PSD[1]")
    assert u1.verdict == "FAIL"
    assert outs(u1, "P1")[0].target_path == "PSD[1].MP" and outs(u1, "P1")[0].actual == 3
    assert u1.value == encode(L["id-ctrl"], {"PSD[1].MP": 3})[14:16]


def test_dollar_index_without_array_is_error():
    rule = R("D1", "id-ctrl.VID", "$ == $i")  # check_rules would reject; engine must not pass
    r = run({"VID": 0}, [rule])
    assert outs(unit(r, "VID"), "D1")[0].result == "unknown"
    assert len(r.db_errors) == 1


def test_conflict_skipped_on_unknown_enumeration():
    a = R("A1", "id-ctrl.SQES[7:4]", "$ == 4 and profile.features.zz")
    b = R("B1", "id-ctrl.SQES[7:4]", "$ == 6", source=OCP)
    r = run({"SQES": 0x66}, [a, b])
    assert "CONFLICT" not in unit(r, "SQES").flags and r.db_errors == ()


def test_wide_targets_not_conflict_checked():
    a = R("A1", "id-ctrl.SN", "$ == 'abcd'")
    b = R("B1", "id-ctrl.SN", "$ == 'wxyz'", source=OCP)
    r = run({"SN": b"abcd"}, [a, b])
    assert "CONFLICT" not in unit(r, "SN").flags


def test_coverage_counts_bits():
    c = compute_coverage(L, [R("C1", "id-ctrl.SQES[7:4]", "$ == 6")], prof())
    cc = {x.struct: x for x in c}
    assert [x.struct for x in c] == ["id-ctrl", "id-ns"]
    x = cc["id-ctrl"]
    assert x.total_bits == 76 and x.value_bits == 4
    # auto: SN ascii (32 format bits); reserved auto rules add none
    assert x.format_bits == 32
    assert x.uncovered_units == ("VID",)  # reserved/ascii auto rules touch the others
    n = cc["id-ns"]
    assert n.total_bits == 32 + 8 + 3 * 4 and n.value_bits == 0 and n.format_bits == 0
    assert n.uncovered_units == ("NSZE", "NLBAF")


def test_coverage_whole_field_and_arrays():
    rules = [R("C1", "id-ctrl.VID", "$ != 0"),
             R("C2", "id-ctrl.PSD[*].MP", "$ < 9"),
             R("C3", "id-ctrl.OACS", "$ >= 0", kind="format"),
             R("C4", "id-ctrl.SQES[3:0]", "$ >= 0", kind="value", when="profile.features.q"),
             R("C5", "id-ctrl.SQES[7:6]", "$ >= 0", kind="value", source=OCP)]
    cc = {x.struct: x for x in compute_coverage(L, rules, prof())}
    x = cc["id-ctrl"]
    assert x.value_bits == 16 + 16 + 4 + 2
    assert x.format_bits == 32 + 4
    assert x.uncovered_units == ()
    cc = {x.struct: x for x in compute_coverage(L, rules, prof(specs=(NVME,)))}
    assert cc["id-ctrl"].value_bits == 16 + 16 + 4


def test_deterministic_order():
    rules = [R("Z1", "id-ctrl.VID", "$ == 0"), R("A1", "id-ctrl.VID", "$ >= 0"),
             R("M1", "id-ctrl.SQES[7:4]", "$ >= 0"), R("M0", "id-ctrl.SQES[3:0]", "$ >= 0")]
    rr = list(reversed(rules))
    r1 = run({"SQES": 0x12}, rules, ns={"NLBAF": 1})
    r2 = run({"SQES": 0x12}, rr, ns={"NLBAF": 1})
    assert r1 == r2 and run({"SQES": 0x12}, rules, ns={"NLBAF": 1}) == r1
    ctrl = [f for f in r1.fields if f.struct == "id-ctrl"]
    assert [f.offset for f in ctrl] == sorted(f.offset for f in ctrl)
    assert [f.struct for f in r1.fields] == ["id-ctrl"] * len(ctrl) + ["id-ns"] * (len(r1.fields) - len(ctrl))
    u = unit(r1, "SQES")
    assert [(o.rule_id, o.target_path) for o in u.outcomes] == sorted(
        (o.rule_id, o.target_path) for o in u.outcomes)


def test_multiple_ns_instances_sorted():
    insts = [Instance("id-ns", 2, encode(L["id-ns"], {})), Instance("id-ns", 1, encode(L["id-ns"], {})),
             Instance("id-ctrl", None, encode(L["id-ctrl"], {}))]
    r = evaluate_run(insts, L, [], prof(), SOURCES)
    keys = [(f.struct, f.nsid) for f in r.fields]
    assert [k for k in dict.fromkeys(keys)] == [("id-ctrl", None), ("id-ns", 1), ("id-ns", 2)]


def test_conflict_respects_when_depending_on_dollar():
    a = R("A1", "id-ctrl.SQES[7:4]", "$ == 7", when="$ > 5")
    b = R("B1", "id-ctrl.SQES[7:4]", "$ == 3", source=OCP)
    r = run({"SQES": 0x60}, [a, b])
    assert "CONFLICT" not in unit(r, "SQES").flags and r.db_errors == ()
    a2 = R("A1", "id-ctrl.SQES[7:4]", "$ == 7", when="$ > 5")
    a3 = R("A2", "id-ctrl.SQES[7:4]", "$ < 5")
    r = run({"SQES": 0x60}, [a2, a3])
    assert r.db_errors == ()
    # genuine contradiction still detected
    c = R("C1", "id-ctrl.SQES[7:4]", "$ == 7", when="$ > 5")
    d = R("D1", "id-ctrl.SQES[7:4]", "$ == 6", source=OCP)
    r = run({"SQES": 0x60}, [c, d])
    assert "CONFLICT" in unit(r, "SQES").flags


def test_overridden_rule_runtime_error_still_recorded():
    bad = R("E1", "id-ctrl.SN", "$ == 3")
    ocp = R("O1", "id-ctrl.VID", "$ == 0", source=OCP, overrides=["E1"])
    r = run({}, [bad, ocp])
    assert outs(unit(r, "SN"), "E1")[0].result == "overridden"
    assert len(r.db_errors) == 1 and r.db_errors[0].startswith("t.yaml: E1: runtime expr error: ")


def test_vendor_specific_subfield_excluded_from_verdict():
    import dataclasses
    lay = L["id-ctrl"]
    fields = []
    for f in lay.fields:
        if f.name == "PSD":
            els = tuple(dataclasses.replace(e, reserved=False, vendor_specific=True)
                        if e.name == "RSVD1" else e for e in f.element)
            f = dataclasses.replace(f, element=els)
        fields.append(f)
    layouts = {**L, "id-ctrl": dataclasses.replace(lay, fields=tuple(fields))}
    rule = R("V1", "id-ctrl.PSD[*].RSVD1", "$ == 'zz'")
    data = Instance("id-ctrl", None, encode(layouts["id-ctrl"], {}))
    r = evaluate_run([data], layouts, [rule], prof(), SOURCES)
    u = unit(r, "PSD[0]")
    assert u.verdict == "NO_RULE" and u.outcomes == ()
    assert r.db_errors == ()
