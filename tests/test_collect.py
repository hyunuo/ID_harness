import json
from datetime import datetime
from pathlib import Path

import pytest

from idharness import collect as collect_mod
from idharness.cli import main
from idharness.collect import CommandError, collect, ssh_runner
from idharness.layout import load_layout_set
from idharness.runs import load_run

MINI = load_layout_set(Path(__file__).parent / "fixtures" / "layouts" / "mini")
NOW = datetime(2026, 10, 20, 15, 0, 0)
DEV = "/dev/nvme0"

LIST_NS = b"[   0]:0x1\n[   1]:0x2\nnoise line\n"


def ok_responses() -> dict:
    return {
        "nvme version": "nvme version 2.9.1 (git 2.9.1)\n".encode(),
        f"sudo nvme list-ns {DEV}": LIST_NS,
        f"sudo nvme id-ctrl {DEV} -b": b"\x01" * 16,
        f"sudo nvme id-ctrl {DEV}": b"NVME Identify Controller:\nvid : 0x1\n",
        f"sudo nvme id-ns {DEV} -n 1 -b": b"\x02" * 8,
        f"sudo nvme id-ns {DEV} -n 1": b"NVME Identify Namespace 1:\r\nnsze : 0x1\n",
        f"sudo nvme id-ns {DEV} -n 2 -b": b"\x03" * 8,
        f"sudo nvme id-ns {DEV} -n 2": b"NVME Identify Namespace 2:\n",
    }


class FakeRunner:
    def __init__(self, responses: dict, fail_on: str | None = None):
        self.responses = responses
        self.fail_on = fail_on
        self.calls: list[str] = []

    def __call__(self, cmd: str) -> bytes:
        self.calls.append(cmd)
        if self.fail_on is not None and self.fail_on in cmd:
            raise CommandError(cmd, 1, b"boom")
        return self.responses[cmd]


def test_collect_writes_run(tmp_path):
    fake = FakeRunner(ok_responses())
    run = collect(fake, "tp1", DEV, tmp_path, NOW)
    assert run.name == "20261020-150000_tp1_nvme0"
    meta = json.loads((run / "meta.json").read_text("utf-8"))
    assert meta == {"host": "tp1", "device": DEV, "nvme_version": "nvme version 2.9.1 (git 2.9.1)",
                    "collected_at": "2026-10-20T15:00:00", "nsids": [1, 2]}
    assert (run / "id-ns-2.bin").read_bytes() == b"\x03" * 8
    assert (run / "id-ctrl.bin").read_bytes() == b"\x01" * 16
    assert (run / "id-ns-1.txt").read_bytes() == b"NVME Identify Namespace 1:\r\nnsze : 0x1\n"
    assert (run / "id-ctrl.txt").exists()
    assert "sudo nvme id-ns /dev/nvme0 -n 2 -b" in fake.calls
    assert fake.calls[0] == "nvme version"


def test_collected_run_loads(tmp_path):
    run = collect(FakeRunner(ok_responses()), "tp1", DEV, tmp_path, NOW)
    meta, insts = load_run(run, MINI)
    assert [(i.struct, i.nsid) for i in insts] == [("id-ctrl", None), ("id-ns", 1), ("id-ns", 2)]
    assert meta["nsids"] == [1, 2]


def test_device_injection_rejected(tmp_path):
    fake = FakeRunner(ok_responses())
    for bad in ("/dev/nvme0; rm -rf /", "/dev/nvme0n1", "/dev/nvme0\n", "nvme0", "", "/dev/nvme٣"):
        with pytest.raises(ValueError):
            collect(fake, "tp1", bad, tmp_path, NOW)
    assert fake.calls == [] and list(tmp_path.iterdir()) == []


def test_host_injection_rejected():
    for bad in ("", "-oProxyCommand=evil"):
        with pytest.raises(ValueError):
            ssh_runner(bad)


def test_ssh_runner_argv(monkeypatch):
    seen = {}

    class P:
        returncode = 0
        stdout = b"out"
        stderr = b""

    def fake_run(argv, **kw):
        seen["argv"], seen["kw"] = argv, kw
        return P()

    monkeypatch.setattr(collect_mod.subprocess, "run", fake_run)
    assert ssh_runner("tp1")("nvme version") == b"out"
    assert seen["argv"] == ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                            "tp1", "nvme version"]
    assert "ConnectTimeout=10" in seen["argv"]
    assert seen["kw"]["timeout"] == 120 and seen["kw"]["stdin"] == collect_mod.subprocess.DEVNULL
    assert not seen["kw"].get("shell")


def test_ssh_runner_raises_command_error(monkeypatch):
    class P:
        returncode = 5
        stdout = b""
        stderr = b"denied"

    monkeypatch.setattr(collect_mod.subprocess, "run", lambda *a, **k: P())
    with pytest.raises(CommandError) as ei:
        ssh_runner("tp1")("x")
    assert ei.value.returncode == 5 and ei.value.stderr == b"denied" and ei.value.cmd == "x"


def test_collect_failure_leaves_no_meta(tmp_path):
    fake = FakeRunner(ok_responses(), fail_on="id-ns")
    with pytest.raises(CommandError):
        collect(fake, "tp1", DEV, tmp_path, NOW)
    assert list(tmp_path.iterdir()) == []


def test_empty_list_ns_is_error(tmp_path):
    resp = ok_responses()
    resp[f"sudo nvme list-ns {DEV}"] = b"nothing here\n"
    with pytest.raises(CommandError, match="no active namespaces"):
        collect(FakeRunner(resp), "tp1", DEV, tmp_path, NOW)
    assert list(tmp_path.iterdir()) == []


def test_existing_run_folder_not_overwritten(tmp_path):
    collect(FakeRunner(ok_responses()), "tp1", DEV, tmp_path, NOW)
    with pytest.raises(FileExistsError):
        collect(FakeRunner(ok_responses()), "tp1", DEV, tmp_path, NOW)
    assert (tmp_path / "20261020-150000_tp1_nvme0" / "meta.json").exists()


def test_out_root_created(tmp_path):
    run = collect(FakeRunner(ok_responses()), "tp1", DEV, tmp_path / "a" / "runs", NOW)
    assert run.is_dir()


def test_cli_collect_ok(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("idharness.cli.ssh_runner", lambda host: FakeRunner(ok_responses()))
    rc = main(["collect", "--host", "tp1", "--device", DEV, "--out", str(tmp_path)])
    assert rc == 0 and "_tp1_nvme0" in capsys.readouterr().out


def test_cli_collect_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("idharness.cli.ssh_runner",
                        lambda host: FakeRunner(ok_responses(), fail_on="id-ctrl"))
    assert main(["collect", "--host", "tp1", "--device", DEV, "--out", str(tmp_path)]) == 3
    out = capsys.readouterr().out
    assert "id-ctrl" in out and "boom" in out
    assert main(["collect", "--host", "tp1", "--device", "/dev/sda", "--out", str(tmp_path)]) == 2
    assert main(["collect", "--host=-bad", "--device", DEV, "--out", str(tmp_path)]) == 2


def test_ssh_runner_timeout(monkeypatch):
    def boom(argv, **kw):
        raise collect_mod.subprocess.TimeoutExpired(argv, 120)

    monkeypatch.setattr(collect_mod.subprocess, "run", boom)
    with pytest.raises(CommandError) as ei:
        ssh_runner("tp1")("x")
    assert ei.value.returncode == -1 and ei.value.stderr == b"timeout after 120s"


def test_cli_collect_missing_ssh(tmp_path, monkeypatch, capsys):
    def boom(argv, **kw):
        raise FileNotFoundError("ssh")

    monkeypatch.setattr(collect_mod.subprocess, "run", boom)
    assert main(["collect", "--host", "tp1", "--device", DEV, "--out", str(tmp_path)]) == 2
    assert "ssh" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []
