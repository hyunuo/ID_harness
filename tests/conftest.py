import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
FIX = Path(__file__).parent / "fixtures"

_PROFILE = ("name: default\nlayout_set: mini\nspecs: [nvme-base-2.1, nvm-cs-1.1, ocp-2.6]\n"
            "features: {}\nvalues: {}\n")


def build_data_root(dest: Path, rules_dir: Path) -> Path:
    (dest / "layouts" / "mini").mkdir(parents=True)
    for p in (FIX / "layouts" / "mini").glob("*.yaml"):
        shutil.copy(p, dest / "layouts" / "mini" / p.name)
    shutil.copytree(rules_dir, dest / "rules")
    for n in ("sources.yaml", "baseline_aliases.yaml"):
        shutil.copy(ROOT / "data" / n, dest / n)
    (dest / "features.yaml").write_text("{}\n", encoding="utf-8")
    (dest / "profiles").mkdir()
    (dest / "profiles" / "default.yaml").write_text(_PROFILE, encoding="utf-8")
    return dest


@pytest.fixture
def FIX_DATA(tmp_path_factory):
    return build_data_root(tmp_path_factory.mktemp("fixdata") / "d", FIX / "rules" / "mini")


@pytest.fixture
def BROKEN_DATA(tmp_path_factory):
    return build_data_root(tmp_path_factory.mktemp("brokendata") / "d", FIX / "rules" / "broken")
