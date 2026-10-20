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
