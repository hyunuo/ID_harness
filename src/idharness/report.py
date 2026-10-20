"""마크다운 리포트와 터미널 요약 (결정적 출력)."""
from __future__ import annotations

from idharness.engine import FieldResult, RunResult
from idharness.layout import Layout
from idharness.profile import Profile
from idharness.rules import Rule

VERDICT_LABEL = {"FAIL": "FAIL", "WARN": "WARN", "PASS": "PASS", "PASS_FORMAT": "PASS(형식만)",
                 "NO_RULE": "규칙 없음"}
FLAG_LABEL = {"CHANGED": "변경됨(CHANGED)", "UNCERTAIN": "불확실 규칙(UNCERTAIN)",
              "CONFLICT": "규칙 충돌(CONFLICT)", "UNKNOWN": "판정 불가(UNKNOWN)",
              "OVERRIDDEN": "덮어씀(OVERRIDDEN)"}
_FLAG_ORDER = ["CHANGED", "UNCERTAIN", "CONFLICT", "UNKNOWN", "OVERRIDDEN"]
_VERDICT_ORDER = ["FAIL", "WARN", "PASS", "PASS_FORMAT", "NO_RULE"]
SUMMARY_LIMIT = 30


def _printable(v: bytes) -> bool:
    s = v.rstrip(b"\x00 ")
    return bool(s) and all(0x20 <= b < 0x7F for b in s)


def fmt_value(v: int | bytes | None, type_: str | None = None) -> str:
    """uint는 0x(10진), ascii는 따옴표, bytes는 16바이트까지 hex."""
    if v is None:
        return "-"
    if isinstance(v, int):
        return f"0x{v:x} ({v})"
    if type_ == "ascii" or (type_ is None and _printable(v)):
        return '"' + v.rstrip(b"\x00 ").decode("ascii", "replace") + '"'
    if len(v) > 16:
        return v[:16].hex() + f"…({len(v)} bytes)"
    return v.hex() if v else "(empty)"


def _cell(s: object) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def _table(header: list[str], rows: list[list[object]]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(_cell(c) for c in r) + " |" for r in rows]
    return out


def _inst(f: FieldResult) -> str:
    return f.struct if f.nsid is None else f"{f.struct}#{f.nsid}"


def _flags(f: FieldResult) -> str:
    return ", ".join(FLAG_LABEL[x] for x in _FLAG_ORDER if x in f.flags) or "-"


def _types(layouts: dict[str, Layout] | None) -> dict[tuple[str, str], str]:
    if not layouts:
        return {}
    return {(s, fd.name): fd.type for s, lay in layouts.items() for fd in lay.fields}


def _type_of(types: dict, f: FieldResult) -> str | None:
    return types.get((f.struct, f.unit.split("[")[0]))


def _fail_rows(result: RunResult, rules: dict[str, Rule], verdict: str, types: dict
               ) -> list[list[object]]:
    level = "shall" if verdict == "FAIL" else "should"
    rows: list[list[object]] = []
    for f in result.fields:
        if f.verdict != verdict:
            continue
        for o in f.outcomes:
            r = rules.get(o.rule_id)
            if o.result != "fail" or r is None or r.level != level:
                continue
            # 비트/하위 필드 target이면 실제값이 unit 전체 타입과 다를 수 있어 타입은 unit 값에만 적용
            t = _type_of(types, f) if o.target_path == f.unit else None
            rows.append([_inst(f), o.target_path, fmt_value(o.actual, t), r.expect_src,
                         o.rule_id, f"{r.source}: {r.ref}", _flags(f)])
    return rows


def render_markdown(result: RunResult, meta: dict, profile: Profile, rules_by_id: dict[str, Rule],
                    db_commit: str | None, layouts: dict[str, Layout] | None = None) -> str:
    types = _types(layouts)
    L: list[str] = ["# NVMe Identify 검증 리포트", ""]
    skipped = meta.get("skipped") or []
    L += [f"- host: {meta.get('host', '-')}", f"- device: {meta.get('device', '-')}",
          f"- 수집 시각: {meta.get('collected_at', '-')}",
          f"- nvme-cli 버전: {meta.get('nvme_version', '-')}",
          f"- 프로필: {profile.name}", f"- 스펙 조합: {' + '.join(profile.specs)}",
          f"- 규칙 DB commit: {db_commit or '알 수 없음'}",
          f"- 레이아웃이 없어 건너뛴 파일: {', '.join(skipped) if skipped else '없음'}", ""]

    L += ["## 요약", ""]
    groups: dict[tuple, list[FieldResult]] = {}
    for f in result.fields:
        groups.setdefault((f.struct, -1 if f.nsid is None else f.nsid), []).append(f)
    hdr = (["구조/NSID"] + [VERDICT_LABEL[v] for v in _VERDICT_ORDER]
           + [FLAG_LABEL[x] for x in _FLAG_ORDER])
    rows: list[list[object]] = []
    for (struct, nsid), fs in groups.items():
        rows.append([struct if nsid < 0 else f"{struct}#{nsid}"]
                    + [sum(1 for f in fs if f.verdict == v) for v in _VERDICT_ORDER]
                    + [sum(1 for f in fs if x in f.flags) for x in _FLAG_ORDER])
    L += _table(hdr, rows) + [""]

    fh = ["구조", "필드", "실제값", "기대(규칙 expect)", "규칙 id", "출처·근거(ref)", "플래그"]
    for v in ("FAIL", "WARN"):
        L += [f"## {v}", ""]
        rs = _fail_rows(result, rules_by_id, v, types)
        L += (_table(fh, rs) if rs else ["없음"]) + [""]

    L += ["## 검토 필요", "", "### 규칙 충돌(CONFLICT)", ""]
    L += [f"- {_inst(f)} {f.unit}: "
          + ", ".join(sorted({o.rule_id for o in f.outcomes if o.result != "overridden"}))
          for f in result.fields if "CONFLICT" in f.flags] or ["없음"]
    L += ["", "### 불확실(uncertain) 규칙으로 판정된 항목", ""]
    unc: list[str] = []
    for f in result.fields:
        if "UNCERTAIN" not in f.flags:
            continue
        ids = sorted({o.rule_id for o in f.outcomes
                      if o.result in ("pass", "fail") and o.rule_id in rules_by_id
                      and rules_by_id[o.rule_id].status == "uncertain"})
        unc.append(f"- {_inst(f)} {f.unit} [{VERDICT_LABEL[f.verdict]}]: {', '.join(ids)}")
    L += unc or ["없음"]
    L += ["", "### 판정 불가: 프로필에 추가 필요", ""]
    L += [f"- 프로필에 추가 필요: {k} (규칙: {', '.join(ids)})"
          for k, ids in result.unknown_keys.items()] or ["없음"]
    L += ["", "### 규칙 DB 오류", ""]
    L += [f"- {e}" for e in result.db_errors] or ["없음"]
    L += [""]

    L += ["## CHANGED", ""]
    ch = [f for f in result.fields if "CHANGED" in f.flags]
    L += (_table(["필드", "기존", "현재", "판정"],
                 [[f"{_inst(f)} {f.unit}", f.baseline, fmt_value(f.value, _type_of(types, f)),
                   VERDICT_LABEL[f.verdict]] for f in ch]) if ch else ["없음"]) + [""]
    L += ["### 매핑되지 않은 기존 로그 키", ""]
    L += [f"- {k}" for k in result.baseline_unmapped] or ["없음"]
    L += [""]

    L += ["## 덮어쓰기 적용(OVERRIDDEN)", ""]
    ov: list[str] = []
    for f in result.fields:
        for o in f.outcomes:
            if o.result != "overridden":
                continue
            ups = sorted(r.id for r in rules_by_id.values() if o.rule_id in r.overrides
                         and any(x.rule_id == r.id for x in f.outcomes))
            ov.append(f"- {_inst(f)} {o.target_path}: {', '.join(ups) or '?'} → 제외됨 {o.rule_id}")
    L += ov or ["없음"]
    L += [""]

    L += ["## 전체 필드 결과", ""]
    L += _table(["구조", "오프셋", "필드", "값", "판정", "플래그"],
                [[_inst(f), f"0x{f.offset:x}", f.unit, fmt_value(f.value, _type_of(types, f)),
                  VERDICT_LABEL[f.verdict], _flags(f)] for f in result.fields]) + [""]

    L += ["## 커버리지", ""]
    for c in result.coverage:
        L.append(f"- {c.struct}: 값 검증 {c.value_bits}/{c.total_bits} 비트, "
                 f"형식 검증 {c.format_bits}/{c.total_bits} 비트, "
                 f"규칙 없는 unit {len(c.uncovered_units)}개"
                 + (f" ({', '.join(c.uncovered_units)})" if c.uncovered_units else ""))
    L += [f"- vendor specific 제외: {result.vendor_specific_skipped}건", ""]

    L += ["## 고지", "",
          "- CHANGED 비교는 합성 샘플로만 검증되었다. 실제 장치의 nvme-cli 출력 형식과 다를 수 있다.",
          ""]
    return "\n".join(L)


def render_summary(result: RunResult) -> str:
    counts = {v: sum(1 for f in result.fields if f.verdict == v) for v in _VERDICT_ORDER}
    L = ["검증 요약: " + ", ".join(f"{VERDICT_LABEL[v]} {counts[v]}" for v in _VERDICT_ORDER)]
    for v in ("FAIL", "WARN"):
        items = [f"  {v} {_inst(f)} {f.unit} = {fmt_value(f.value)}"
                 for f in result.fields if f.verdict == v]
        L += items[:SUMMARY_LIMIT]
        if len(items) > SUMMARY_LIMIT:
            L.append(f"  외 {len(items) - SUMMARY_LIMIT}건")
    nconf = sum(1 for f in result.fields if "CONFLICT" in f.flags)
    nunk = sum(1 for f in result.fields if "UNKNOWN" in f.flags)
    L.append(f"검토 필요: 규칙 충돌 {nconf}, 판정 불가 {nunk}, 규칙 DB 오류 {len(result.db_errors)}")
    return "\n".join(L)
