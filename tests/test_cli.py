import json

from idharness.cli import main
from idharness.layout import encode, load_layout_set
from pathlib import Path

L = load_layout_set(Path(__file__).parent / "fixtures" / "layouts" / "mini")


def make_run_dir(path):
    path.mkdir(exist_ok=True)
    (path / "meta.json").write_text(json.dumps(
        {"host": "h", "device": "/dev/nvme0", "nvme_version": "2.9",
         "collected_at": "2026-01-01T00:00:00", "nsids": [1]}), encoding="utf-8")
    (path / "id-ctrl.bin").write_bytes(encode(L["id-ctrl"], {"SQES": 6}))
    (path / "id-ns-1.bin").write_bytes(encode(L["id-ns"], {"NSZE": 10, "LBAF[0]": 0}))
    return path


def test_cli_validate_writes_report(tmp_path, capsys, FIX_DATA):
    run_dir = make_run_dir(tmp_path / "run")
    rc = main(["validate", str(run_dir), "--data", str(FIX_DATA)])
    assert rc == 0 and (run_dir / "report.md").exists() and "FAIL" in capsys.readouterr().out


def test_validate_refuses_broken_db(tmp_path, BROKEN_DATA):
    run_dir = make_run_dir(tmp_path / "run")
    assert main(["validate", str(run_dir), "--data", str(BROKEN_DATA)]) == 2
    assert not (run_dir / "report.md").exists()


def test_validate_bad_run_exits_2(tmp_path, capsys, FIX_DATA):
    run_dir = make_run_dir(tmp_path / "run")
    (run_dir / "id-ctrl.bin").write_bytes(b"\x00" * 15)
    assert main(["validate", str(run_dir), "--data", str(FIX_DATA)]) == 2
    assert "id-ctrl.bin" in capsys.readouterr().out


def test_check_rules_exit_codes(FIX_DATA, BROKEN_DATA, capsys):
    assert main(["check-rules", "--data", str(FIX_DATA)]) == 0
    assert main(["check-rules", "--data", str(BROKEN_DATA)]) == 1
    out = capsys.readouterr().out
    assert "BAD-TYPO" in out and "DUP-ONE" in out and "BAD-EXPR" in out


def test_coverage_range_lists_uncovered(capsys, FIX_DATA):
    assert main(["coverage", "--data", str(FIX_DATA), "--struct", "id-ctrl", "--range", "0:7"]) == 0
    out = capsys.readouterr().out
    assert "OACS" in out and "VID" in out and "SQES" not in out
    assert "uncovered" in out  # VID/SN have no explicit rules; auto rules may cover reserved bits only


def test_coverage_totals(capsys, FIX_DATA):
    assert main(["coverage", "--data", str(FIX_DATA)]) == 0
    out = capsys.readouterr().out
    assert "id-ctrl" in out and "id-ns" in out
