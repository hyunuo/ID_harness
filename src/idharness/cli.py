"""CLI: validate | check-rules | coverage."""
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

from idharness.baseline import load_baseline
from idharness.engine import _units, compute_coverage, evaluate_run
from idharness.layout import Layout, check_layout, load_layout_set
from idharness.profile import Profile, load_profile
from idharness.report import render_markdown, render_summary
from idharness.rules import Rule, check_rules, expand_target, generate_auto_rules, load_rules
from idharness.runs import RunLoadError, load_run
from idharness.sources import Source, load_sources


@dataclass
class DB:
    profile: Profile | None
    layouts: dict[str, Layout]
    sources: dict[str, Source]
    features: dict
    aliases: dict
    rules: list[Rule]
    errors: list[str]


def _read_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    return doc if isinstance(doc, dict) else {}


def load_db(data: Path, profile_name: str) -> DB:
    """규칙 DB 로드와 정합성 검사 (DB gate의 오류 목록 포함)."""
    errors: list[str] = []
    sources: dict[str, Source] = {}
    try:
        sources = load_sources(data / "sources.yaml")
    except Exception as e:  # noqa: BLE001 - 어떤 로드 실패도 DB 오류로 보고
        errors.append(f"sources.yaml: {e}")
    try:
        features = _read_yaml(data / "features.yaml")
        aliases = _read_yaml(data / "baseline_aliases.yaml")
    except yaml.YAMLError as e:
        errors.append(f"features/aliases YAML 오류: {e}")
        features, aliases = {}, {}
    profile: Profile | None = None
    layouts: dict[str, Layout] = {}
    try:
        profile = load_profile(profile_name, data / "profiles", features)
        layouts = load_layout_set(data / "layouts" / profile.layout_set)
    except Exception as e:  # noqa: BLE001
        errors.append(f"profile {profile_name}: {e}")
    for name in sorted(layouts):
        errors += [f"layouts/{name}: {m}" for m in check_layout(layouts[name])]
    rules, load_errors = load_rules(data / "rules")
    errors += load_errors
    errors += check_rules(rules + generate_auto_rules(layouts), layouts, sources, features)
    return DB(profile, layouts, sources, features, aliases, rules, errors)


def _db_commit(data: Path) -> str | None:
    try:
        p = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=data, capture_output=True,
                           text=True, encoding="utf-8", timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    out = p.stdout.strip()
    return out if p.returncode == 0 and out else None


def _print_errors(errors: list[str]) -> None:
    for e in errors:
        print(e)


def cmd_check_rules(args) -> int:
    db = load_db(Path(args.data), args.profile)
    if db.errors:
        _print_errors(db.errors)
        print(f"규칙 DB 오류 {len(db.errors)}건")
        return 1
    print(f"OK: 규칙 {len(db.rules)}개, 레이아웃 {len(db.layouts)}개, 오류 없음")
    return 0


def cmd_validate(args) -> int:
    data = Path(args.data)
    db = load_db(data, args.profile)
    if db.errors or db.profile is None:
        _print_errors(db.errors)
        print(f"규칙 DB 오류 {len(db.errors)}건: 검증을 실행하지 않는다")
        return 2
    run_dir = Path(args.run_dir)
    try:
        meta, instances = load_run(run_dir, db.layouts)
        baseline = (load_baseline(Path(args.baseline), db.aliases, db.layouts)
                    if args.baseline else None)
    except (RunLoadError, ValueError) as e:
        print(e)
        return 2
    result = evaluate_run(instances, db.layouts, db.rules, db.profile, db.sources, baseline)
    by_id = {r.id: r for r in db.rules + generate_auto_rules(db.layouts)}
    md = render_markdown(result, meta, db.profile, by_id, _db_commit(data), db.layouts)
    report = run_dir / "report.md"
    report.write_text(md, encoding="utf-8")
    print(render_summary(result))
    print(f"리포트: {report}")
    return 0


def _parse_range(text: str) -> tuple[int, int]:
    a, _, b = text.partition(":")
    lo, hi = int(a, 0), int(b, 0)
    if lo > hi:
        raise ValueError(f"잘못된 --range: {text}")
    return lo, hi


def cmd_coverage(args) -> int:
    db = load_db(Path(args.data), args.profile)
    if db.profile is None:
        _print_errors(db.errors)
        return 2
    if db.errors:
        print(f"(경고: 규칙 DB 오류 {len(db.errors)}건, check-rules로 확인)")
    cov = {c.struct: c for c in compute_coverage(db.layouts, db.rules, db.profile)}
    structs = [args.struct] if args.struct else sorted(cov, key=lambda s: (s != "id-ctrl", s))
    for s in structs:
        if s not in cov:
            print(f"레이아웃 없음: {s}")
            return 2
    rng = None
    if args.range:
        try:
            rng = _parse_range(args.range)
        except ValueError as e:
            print(e)
            return 2
    active = [r for r in db.rules + generate_auto_rules(db.layouts)
              if r.source in db.profile.specs]
    for s in structs:
        c = cov[s]
        if rng is None:
            print(f"{s}: 값 검증 {c.value_bits}/{c.total_bits} 비트, 형식 검증 "
                  f"{c.format_bits}/{c.total_bits} 비트, 규칙 없는 unit {len(c.uncovered_units)}개")
            continue
        layout = db.layouts[s]
        counts: dict[str, set[str]] = {}
        for r in active:
            if r.target.struct != s:
                continue
            try:
                exp = expand_target(r.target, layout)
            except ValueError:
                continue
            for key, _i, _b in exp:
                counts.setdefault(key.split(".", 1)[0], set()).add(r.id)
        n_unc = 0
        n_total = 0
        for unit, off in _units(layout):
            if not rng[0] <= off <= rng[1]:
                continue
            n_total += 1
            mark = ""
            if unit in c.uncovered_units:
                mark = "  uncovered"
                n_unc += 1
            print(f"{s} {unit} offset=0x{off:x} ({off}) 규칙 {len(counts.get(unit, ()))}개{mark}")
        print(f"{s} 범위 {rng[0]}:{rng[1]}: unit {n_total}개, uncovered {n_unc}개")
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="idharness")
    sub = ap.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate", help="run 폴더를 검증하고 report.md를 쓴다")
    v.add_argument("run_dir")
    v.add_argument("--profile", default="default")
    v.add_argument("--baseline")
    v.add_argument("--data", default="data")
    v.set_defaults(fn=cmd_validate)

    c = sub.add_parser("check-rules", help="레이아웃/규칙 DB 정합성 검사")
    c.add_argument("--profile", default="default")
    c.add_argument("--data", default="data")
    c.set_defaults(fn=cmd_check_rules)

    g = sub.add_parser("coverage", help="비트 커버리지")
    g.add_argument("--profile", default="default")
    g.add_argument("--struct")
    g.add_argument("--range", help="포함 바이트 오프셋 a:b")
    g.add_argument("--data", default="data")
    g.set_defaults(fn=cmd_coverage)

    args = ap.parse_args(argv)
    return args.fn(args)


def entry() -> None:
    sys.exit(main())
