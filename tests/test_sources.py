from pathlib import Path

from idharness.sources import load_sources


def test_load_sources_ranks():
    s = load_sources(Path("data/sources.yaml"))
    assert s["ocp-2.6"].rank == 20 and s["nvme-base-2.1"].rank == 10
    assert s["nvm-cs-1.1"].rank == 10


def test_source_files_exist():
    for src in load_sources(Path("data/sources.yaml")).values():
        assert Path(src.file).exists(), src.file
