from pathlib import Path

from idharness.engine import Instance, evaluate_run
from idharness.layout import encode, load_layout_set
from idharness.profile import Profile
from idharness.report import render_markdown, render_summary
from idharness.rules import generate_auto_rules, load_rules
from idharness.sources import load_sources

ROOT = Path(__file__).parent.parent
FIX = Path(__file__).parent / "fixtures"
L = load_layout_set(FIX / "layouts" / "mini")
SOURCES = load_sources(ROOT / "data" / "sources.yaml")
RULES, _ = load_rules(FIX / "rules" / "mini")
PROFILE = Profile("default", "mini", ("nvme-base-2.1", "nvm-cs-1.1", "ocp-2.6"), {}, {})
META = {"host": "h1", "device": "/dev/nvme0", "nvme_version": "2.9", "skipped": ["id-zz.bin"],
        "collected_at": "2026-01-01T00:00:00", "nsids": [1]}


def make():
    insts = [Instance("id-ctrl", None, encode(L["id-ctrl"], {"VID": 0x1234, "SN": b"AB", "SQES": 5})),
             Instance("id-ns", 1, encode(L["id-ns"], {"NSZE": 100, "LBAF[0]": 0}))]
    result = evaluate_run(insts, L, RULES, PROFILE, SOURCES)
    by_id = {r.id: r for r in RULES + generate_auto_rules(L)}
    return result, META, PROFILE, by_id, "abc123"


def test_report_sections_and_evidence():
    md = render_markdown(*make())
    for h in ["## 요약", "## FAIL", "## WARN", "## 검토 필요", "## CHANGED",
              "## 덮어쓰기 적용", "## 전체 필드 결과", "## 커버리지", "## 고지"]:
        assert h in md
    assert "NVM-NS-LBAF-LBADS" in md and "NVM CS 1.1 §4.1" in md and "abc123" in md
    assert "id-zz.bin" in md and "0x1234 (4660)" in md and '"AB' in md


def test_report_is_deterministic():
    a = make()
    assert render_markdown(*a) == render_markdown(*a)


def test_summary_truncates_to_30():
    result, *_ = make()
    s = render_summary(result)
    assert "FAIL" in s and "WARN" in s


def section(md, name):
    start = md.index(f"## {name}\n")
    end = md.find("\n## ", start + 1)
    return md[start:end if end >= 0 else len(md)]


def test_fail_row_has_all_evidence_and_escapes_pipes():
    import dataclasses
    result, meta, profile, by_id, commit = make()
    r = by_id["NVM-NS-LBAF-LBADS"]
    by_id["NVM-NS-LBAF-LBADS"] = dataclasses.replace(r, expect_src="$ >= 9 | x", ref="Sec|4.1")
    sec = section(render_markdown(result, meta, profile, by_id, commit), "FAIL")
    row = next(ln for ln in sec.splitlines() if "NVM-NS-LBAF-LBADS" in ln)
\| \| \| \| \|a\|s\|s\|e\|r\|t\| \|"\|0\|x\|0\| \|(\|0\|)\|"\| \|i\|n\| \|r\|o\|w\| \|a\|n\|d\| \|"\|$\| \|>\|=\| \|9\| \|\\||\| \|x\|"\| \|i\|n\| \|r\|o\|w\| \|a\|n\|d\| \|"\|n\|v\|m\|-\|c\|s\|-\|1\|.\|1\|:\| \|S\|e\|c\|\\||\|4\|.\|1\|"\| \|i\|n\| \|r\|o\|w\|
    assert "id-ns#1" in row and "LBAF[0][3:0]" in row


def test_fail_row_shows_flags():
    result, meta, profile, by_id, commit = make()
    sec = section(render_markdown(result, meta, profile, by_id, commit), "WARN")
    row = next(ln for ln in sec.splitlines() if "OCP-CTRL-SQES-MINES" in ln)
    assert "불확실 규칙(UNCERTAIN)" in row and "덮어씀(OVERRIDDEN)" in row


def test_should_failure_on_fail_field_appears_in_warn_table():
    from idharness.rules import _build_rule
    def R(id, expect, level):
        return _build_rule({"id": id, "source": "nvme-base-2.1", "ref": "x", "target": "id-ctrl.VID",
                            "expect": expect, "level": level, "kind": "value",
                            "status": "cross-checked"}, "t.yaml")
    rules = [R("T-SHALL", "$ == 1", "shall"), R("T-SHOULD", "$ == 2", "should")]
    insts = [Instance("id-ctrl", None, encode(L["id-ctrl"], {"VID": 0}))]
    result = evaluate_run(insts, L, rules, PROFILE, SOURCES)
    by_id = {r.id: r for r in rules + generate_auto_rules(L)}
    md = render_markdown(result, META, PROFILE, by_id, None)
    fail, warn = section(md, "FAIL"), section(md, "WARN")
    assert "T-SHALL" in fail and "T-SHOULD" not in fail
    assert "T-SHOULD" in warn and "T-SHALL" not in warn
    assert "FAIL인 필드의 should 위반" in warn


def test_determinism_with_independently_built_results():
    a = make()
    insts = [Instance("id-ctrl", None, encode(L["id-ctrl"], {"VID": 0x1234, "SN": b"AB", "SQES": 5})),
             Instance("id-ns", 1, encode(L["id-ns"], {"NSZE": 100, "LBAF[0]": 0}))]
    result2 = evaluate_run(list(reversed(insts)), L, list(reversed(RULES)), PROFILE, SOURCES)
    assert render_markdown(*a) == render_markdown(result2, *a[1:])
    assert render_markdown(*a).endswith("\n")


def _synthetic(n_fail, n_warn):
    from idharness.engine import FieldResult, RunResult
    fs = [FieldResult("id-ctrl", None, f"U{i:03d}", i, i, "FAIL", frozenset(), (), None)
          for i in range(n_fail)]
    fs += [FieldResult("id-ctrl", None, f"W{i:03d}", 100 + i, i, "WARN", frozenset(), (), None)
           for i in range(n_warn)]
    return RunResult(tuple(fs), (), {}, (), 0)


def test_summary_total_cap_30_fail_first():
    s = render_summary(_synthetic(35, 5))
    rows = [ln for ln in s.splitlines() if ln.startswith("  FAIL") or ln.startswith("  WARN")]
    assert len(rows) == 30 and all(r.startswith("  FAIL") for r in rows)
    assert [ln for ln in s.splitlines() if "외 " in ln] == ["  외 10건"]


def test_summary_cap_spans_fail_and_warn():
    s = render_summary(_synthetic(20, 20))
    rows = [ln for ln in s.splitlines() if ln.startswith("  FAIL") or ln.startswith("  WARN")]
    assert len(rows) == 30 and sum(r.startswith("  WARN") for r in rows) == 10
    assert "  외 10건" in s.splitlines()


def test_summary_no_truncation_line_when_small():
    assert "외 " not in render_summary(_synthetic(3, 2))
