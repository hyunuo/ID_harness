from pathlib import Path

import pytest

from idharness.profile import load_profile

FIX = Path(__file__).parent / "fixtures"


def test_profile_extends_and_unknown_feature():
    p = load_profile("child", FIX / "profiles", {"sanitize": {}})
    assert p.specs == ("nvme-base-2.1", "nvm-cs-1.1", "ocp-2.6") and p.features == {"sanitize": True}
    assert p.name == "child" and p.layout_set == "nvme-2.1"
    with pytest.raises(ValueError, match="sanitise"):
        load_profile("typo", FIX / "profiles", {"sanitize": {}})


def test_profile_default_and_cycle(tmp_path):
    p = load_profile("default", FIX / "profiles", {})
    assert p.features == {} and p.values == {}
    (tmp_path / "a.yaml").write_text("name: a\nextends: b\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("name: b\nextends: a\n", encoding="utf-8")
    with pytest.raises(ValueError, match="cycle"):
        load_profile("a", tmp_path, {})


def test_real_default_profile():
    root = Path(__file__).parent.parent / "data"
    p = load_profile("default", root / "profiles", {})
    assert p.layout_set == "nvme-2.1"
