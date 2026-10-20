"""ssh로 테스트 PC에서 nvme Identify 덤프를 수집해 run 폴더를 만든다."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Callable

Runner = Callable[[str], bytes]

_DEVICE = re.compile(r"/dev/nvme\d+")
_NSID_LINE = re.compile(r"\[\s*\d+\]:\s*0x([0-9a-fA-F]+)")
_UNSAFE = re.compile(r"[^A-Za-z0-9._@-]")


class CommandError(Exception):
    def __init__(self, cmd: str, returncode: int, stderr: bytes | str = b""):
        super().__init__(cmd, returncode, stderr)
        self.cmd = cmd
        self.returncode = returncode
        self.stderr = stderr

    def __str__(self) -> str:
        err = self.stderr.decode("utf-8", errors="replace") if isinstance(
            self.stderr, bytes) else self.stderr
        return f"명령 실패 (rc={self.returncode}): {self.cmd}\n{err}"


def _check_host(host: str) -> None:
    if not host or host.startswith("-"):
        raise ValueError(f"잘못된 host: {host!r}")


def ssh_runner(host: str) -> Runner:
    _check_host(host)

    def run(cmd: str) -> bytes:
        p = subprocess.run(["ssh", "-o", "BatchMode=yes", host, cmd], capture_output=True)
        if p.returncode != 0:
            raise CommandError(cmd, p.returncode, p.stderr)
        return p.stdout

    return run


def _parse_nsids(out: bytes) -> list[int]:
    text = out.decode("utf-8", errors="replace")
    return sorted({int(m.group(1), 16) for m in _NSID_LINE.finditer(text)})


def collect(runner: Runner, host: str, device: str, out_root: Path, now: datetime) -> Path:
    _check_host(host)
    if not _DEVICE.fullmatch(device):
        raise ValueError(f"잘못된 device (예: /dev/nvme0): {device!r}")
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    run_dir = out_root / f"{now.strftime('%Y%m%d-%H%M%S')}_{_UNSAFE.sub('_', host)}_{device[5:]}"
    run_dir.mkdir()  # 이미 있으면 FileExistsError (덮어쓰지 않음)
    try:
        version = runner("nvme version")
        list_cmd = f"sudo nvme list-ns {device}"
        nsids = _parse_nsids(runner(list_cmd))
        if not nsids:
            raise CommandError(list_cmd, 0, "no active namespaces")
        (run_dir / "id-ctrl.bin").write_bytes(runner(f"sudo nvme id-ctrl {device} -b"))
        (run_dir / "id-ctrl.txt").write_bytes(runner(f"sudo nvme id-ctrl {device}"))
        for nsid in nsids:
            (run_dir / f"id-ns-{nsid}.bin").write_bytes(
                runner(f"sudo nvme id-ns {device} -n {nsid} -b"))
            (run_dir / f"id-ns-{nsid}.txt").write_bytes(
                runner(f"sudo nvme id-ns {device} -n {nsid}"))
        meta = {"host": host, "device": device,
                "nvme_version": version.decode("utf-8", errors="replace").strip(),
                "collected_at": now.isoformat(timespec="seconds"), "nsids": nsids}
        (run_dir / "meta.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    except BaseException:
        shutil.rmtree(run_dir, ignore_errors=True)
        raise
    return run_dir
