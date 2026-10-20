"""판정 엔진: 규칙 평가, 명시 덮어쓰기, 충돌 검사, unit 판정 집계, 비트 커버리지."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Literal

from idharness.expr import (BinOp, Call, ExprError, Node, Not, Ref, RefNode, SetLit,
                            Unknown, Value, evaluate, refs)
from idharness.layout import FieldDef, Layout, decode, field_width_bits
from idharness.profile import Profile
from idharness.rules import (Rule, expand_target, generate_auto_rules, normalize_ref)
from idharness.sources import Source

MAX_ENUM_BITS = 16


@dataclass(frozen=True)
class Instance:
    struct: str
    nsid: int | None
    data: bytes


@dataclass(frozen=True)
class RuleOutcome:
    rule_id: str
    source: str
    target_path: str
    result: Literal["pass", "fail", "na", "overridden", "unknown"]
    actual: int | bytes | None
    reason: str


@dataclass(frozen=True)
class FieldResult:
    struct: str
    nsid: int | None
    unit: str
    offset: int
    value: int | bytes
    verdict: str
    flags: frozenset[str]
    outcomes: tuple[RuleOutcome, ...]
    baseline: str | None


@dataclass(frozen=True)
class Coverage:
    struct: str
    total_bits: int
    value_bits: int
    format_bits: int
    uncovered_units: tuple[str, ...]


@dataclass(frozen=True)
class RunResult:
    fields: tuple[FieldResult, ...]
    db_errors: tuple[str, ...]
    unknown_keys: dict[str, tuple[str, ...]]
    coverage: tuple[Coverage, ...]
    vendor_specific_skipped: int


# ---- 레이아웃 보조 ----

def _struct_order(name: str) -> tuple[bool, str]:
    return (name != "id-ctrl", name)


def _items(f: FieldDef):
    """(key, offset) for each logical item of a top-level field."""
    if f.count > 1:
        esize = f.size // f.count
        for i in range(f.count):
            yield f"{f.name}[{i}]", f.offset + i * esize
    else:
        yield f.name, f.offset


def _units(layout: Layout) -> list[tuple[str, int]]:
    """판정 대상 unit (vendor_specific 제외), offset 순."""
    out = [(k, off) for f in layout.fields if not f.vendor_specific for k, off in _items(f)]
    out.sort(key=lambda u: (u[1], u[0]))
    return out


def _live_bits(width: int, f: FieldDef) -> frozenset[int]:
    if f.reserved:
        return frozenset()
    dead: set[int] = set()
    for b in f.bits:
        if b.reserved:
            dead.update(range(b.lo, b.hi + 1))
    return frozenset(b for b in range(width) if b not in dead)


def _leaves(layout: Layout) -> dict[str, frozenset[int]]:
    """decode 키별 (reserved/vendor_specific 제외) 살아 있는 비트 집합."""
    out: dict[str, frozenset[int]] = {}
    for f in layout.fields:
        if f.vendor_specific:
            continue
        for key, _ in _items(f):
            if f.type == "struct" and not f.reserved:
                for e in f.element:
                    if not e.vendor_specific:
                        out[f"{key}.{e.name}"] = _live_bits(e.size * 8, e)
            else:
                out[key] = _live_bits(field_width_bits(f), f)
    return out


def _find_field(layout: Layout, name: str) -> FieldDef:
    return next(f for f in layout.fields if f.name == name)


def _target_width(layout: Layout, rule: Rule, bits: tuple[int, int] | None) -> int:
    if bits is not None:
        return bits[0] - bits[1] + 1
    f = _find_field(layout, rule.target.field)
    if rule.target.sub is not None:
        return next(e for e in f.element if e.name == rule.target.sub).size * 8
    return field_width_bits(f)


def _bits_suffix(bits: tuple[int, int] | None) -> str:
    if bits is None:
        return ""
    hi, lo = bits
    return f"[{hi}]" if hi == lo else f"[{hi}:{lo}]"


def _unit_of(key: str) -> str:
    return key.split(".", 1)[0]


# ---- 식 보조 ----

def _norm_node(node: Node, layouts: dict[str, Layout]) -> Node:
    """구조 참조를 normalize_ref로 정규화한 새 AST (path = decode 키)."""
    if isinstance(node, RefNode):
        if node.ref.scope in ("$", "$i", "profile"):
            return node
        return dataclasses.replace(node, ref=normalize_ref(node.ref, layouts))
    if isinstance(node, Not):
        return dataclasses.replace(node, operand=_norm_node(node.operand, layouts))
    if isinstance(node, BinOp):
        return dataclasses.replace(node, left=_norm_node(node.left, layouts),
                                   right=_norm_node(node.right, layouts))
    if isinstance(node, Call):
        return dataclasses.replace(node, args=tuple(_norm_node(a, layouts) for a in node.args))
    if isinstance(node, SetLit):
        return dataclasses.replace(node, items=tuple(_norm_node(a, layouts) for a in node.items))
    return node


class _Env:
    def __init__(self, profile: Profile, decoded: dict[str, dict], own: str,
                 dollar: Value | None, index: int | None):
        self.profile, self.decoded, self.own = profile, decoded, own
        self.dollar, self.index = dollar, index

    def resolve(self, ref: Ref) -> Value:
        if ref.scope == "$":
            if self.dollar is None:
                raise ExprError("$ 값 없음")
            return self.dollar
        if ref.scope == "$i":
            if self.index is None:
                raise ExprError("배열이 아닌 target에서 $i 사용")
            return self.index
        if ref.scope == "profile":
            kind, _, name = ref.path.partition(".")
            table = self.profile.features if kind == "features" else self.profile.values
            if name not in table:
                raise Unknown(f"profile.{ref.path}")
            return table[name]
        dec = self.decoded.get(ref.scope)
        if dec is None:
            raise Unknown(ref.scope)
        if ref.path not in dec:
            raise Unknown(f"{ref.scope}.{ref.path}")
        return dec[ref.path]


def _eval_bool(node: Node, env: _Env, what: str) -> bool:
    v = evaluate(node, env)
    if not isinstance(v, bool):
        raise ExprError(f"{what} 결과가 bool이 아님")
    return v


@dataclass
class _Prep:
    rule: Rule
    when: Node | None
    expect: Node
    norm_err: str | None
    uses_dollar: bool


@dataclass
class _Ev:
    prep: _Prep
    unit: str
    path: str
    bits: tuple[int, int] | None
    index: int | None
    width: int
    when_true: bool = False
    result: str = "na"
    actual: int | bytes | None = None
    reason: str = ""
    unknown_key: str | None = None
    err: str | None = None


def _select(rules: list[Rule], layouts: dict[str, Layout], profile: Profile) -> list[_Prep]:
    chosen = [r for r in list(rules) + generate_auto_rules(layouts) if r.source in profile.specs]
    chosen.sort(key=lambda r: (r.id, r.file))
    out = []
    for r in chosen:
        err = None
        when, expect = r.when, r.expect
        try:
            when = _norm_node(r.when, layouts) if r.when is not None else None
            expect = _norm_node(r.expect, layouts)
        except ValueError as e:
            err = str(e)
        out.append(_Prep(r, when, expect, err, any(x.scope == "$" for x in refs(r.expect))))
    return out


def _evaluate_one(ev: _Ev, key: str, dec: dict, env_decoded: dict[str, dict],
                  profile: Profile) -> None:
    p = ev.prep
    try:
        if p.norm_err is not None:
            raise ExprError(p.norm_err)
        raw = dec[key]
        if ev.bits is not None:
            if not isinstance(raw, int):
                raise ExprError("비트 선택은 정수에만 가능")
            hi, lo = ev.bits
            raw = (raw >> lo) & ((1 << (hi - lo + 1)) - 1)
        ev.actual = raw
        env = _Env(profile, env_decoded, p.rule.target.struct, raw, ev.index)
        if p.when is not None:
            ev.when_true = _eval_bool(p.when, env, "when")
            if not ev.when_true:
                ev.result = "na"
                return
        else:
            ev.when_true = True
        ev.result = "pass" if _eval_bool(p.expect, env, "expect") else "fail"
    except Unknown as u:
        ev.result, ev.reason, ev.unknown_key = "unknown", u.reason, u.reason
    except ExprError as e:
        ev.result, ev.reason, ev.err = "unknown", f"식 오류: {e}", str(e)


def _enumerate_group(group: list[_Ev], profile: Profile, env_decoded: dict[str, dict]
                     ) -> tuple[bool, list[str]] | None:
    """(전체 만족 가능, 출처 내 모순 id들) 또는 건너뜀(None)."""
    width = group[0].width
    by_source: dict[str, list[_Ev]] = {}
    for e in group:
        by_source.setdefault(e.prep.rule.source, []).append(e)
    sat = {s: False for s in by_source}
    whole = False
    try:
        for v in range(1 << width):
            res: dict[str, bool] = {}
            for s, members in by_source.items():
                ok = True
                for e in members:
                    env = _Env(profile, env_decoded, e.prep.rule.target.struct, v, e.index)
                    if e.prep.when is not None and not _eval_bool(e.prep.when, env, "when"):
                        continue  # v에서 적용되지 않는 규칙
                    if not _eval_bool(e.prep.expect, env, "expect"):
                        ok = False
                        break
                res[s] = ok
                if ok:
                    sat[s] = True
            if all(res.values()):
                whole = True
                break
    except (Unknown, ExprError):
        return None
    bad = sorted(e.prep.rule.id for s, members in by_source.items() if not sat[s] for e in members)
    return whole, bad


def _verdict(evs: list[_Ev]) -> tuple[str, frozenset[str]]:
    live = [e for e in evs if e.result != "overridden"]
    used = [e for e in live if e.result in ("pass", "fail")]
    flags: set[str] = set()
    if any(e.prep.rule.status == "uncertain" for e in used):
        flags.add("UNCERTAIN")
    if any(e.result == "unknown" for e in live):
        flags.add("UNKNOWN")
    if any(e.result == "overridden" for e in evs):
        flags.add("OVERRIDDEN")

    def has(result: str, level: str | None = None, kind: str | None = None) -> bool:
        return any(e.result == result and (level is None or e.prep.rule.level == level)
                   and (kind is None or e.prep.rule.kind == kind) for e in live)

    if has("fail", "shall"):
        v = "FAIL"
    elif has("fail", "should"):
        v = "WARN"
    elif has("pass", kind="value"):
        v = "PASS"
    elif has("pass", kind="format"):
        v = "PASS_FORMAT"
    else:
        v = "NO_RULE"
    return v, frozenset(flags)


def evaluate_run(instances: list[Instance], layouts: dict[str, Layout], rules: list[Rule],
                 profile: Profile, sources: dict[str, Source]) -> RunResult:
    prepared = _select(rules, layouts, profile)
    db_errors: set[str] = set()
    unknown: dict[str, set[str]] = {}
    fields: list[FieldResult] = []
    vs_skipped = 0

    decoded_by_inst: list[dict[str, int | bytes]] = []
    first_dec: dict[str, dict] = {}
    for inst in instances:
        layout = layouts.get(inst.struct)
        if layout is None:
            raise ValueError(f"레이아웃 없음: {inst.struct}")
        if len(inst.data) != layout.size:
            raise ValueError(f"{inst.struct} 덤프 크기 {len(inst.data)} != 기대 {layout.size}")
        dec = decode(layout, inst.data)
        decoded_by_inst.append(dec)
    for inst, dec in sorted(zip(instances, decoded_by_inst),
                            key=lambda t: (-1 if t[0].nsid is None else t[0].nsid)):
        first_dec.setdefault(inst.struct, dec)

    def rt_error(p: _Prep, msg: str) -> None:
        db_errors.add(f"{p.rule.file}: {p.rule.id}: runtime expr error: {msg}")

    for inst, dec in zip(instances, decoded_by_inst):
        layout = layouts[inst.struct]
        env_decoded = {**first_dec, inst.struct: dec}
        evs: list[_Ev] = []
        for p in prepared:
            r = p.rule
            if r.target.struct != inst.struct:
                continue
            try:
                expansions = expand_target(r.target, layout)
            except ValueError as e:
                rt_error(p, f"target 오류: {e}")
                continue
            tf = _find_field(layout, r.target.field)
            if tf.vendor_specific or (r.target.sub is not None and any(
                    e.vendor_specific for e in tf.element if e.name == r.target.sub)):
                continue  # vendor_specific은 판정 제외
            for key, idx, bits in expansions:
                ev = _Ev(p, _unit_of(key), key + _bits_suffix(bits), bits, idx,
                         _target_width(layout, r, bits))
                _evaluate_one(ev, key, dec, env_decoded, profile)
                evs.append(ev)

        # R8: 런타임 식 오류는 덮어쓰기와 무관하게 기록
        for e in evs:
            if e.err is not None:
                rt_error(e.prep, e.err)

        # R7: 인스턴스 단위 명시 덮어쓰기
        by_id = {p.rule.id for p in prepared}
        overridden: set[str] = set()
        for e in evs:
            if e.when_true:
                overridden.update(o for o in e.prep.rule.overrides if o in by_id)
        for e in evs:
            if e.prep.rule.id in overridden:
                e.result = "overridden"

        for e in evs:
            if e.result == "unknown" and e.unknown_key is not None:
                unknown.setdefault(e.unknown_key, set()).add(e.prep.rule.id)


        # 충돌 검사
        conflict_units: set[str] = set()
        groups: dict[str, list[_Ev]] = {}
        for e in evs:
            if (e.result != "overridden" and e.when_true and e.prep.uses_dollar
                    and isinstance(e.actual, int) and e.width <= MAX_ENUM_BITS):
                groups.setdefault(e.path, []).append(e)
        for path in sorted(groups):
            g = groups[path]
            if all(e.result == "pass" for e in g):
                continue  # 실제 값이 전부 만족하므로 만족 가능
            res = _enumerate_group(g, profile, env_decoded)
            if res is None:
                continue
            whole, bad = res
            if bad:
                db_errors.add(f"same-source contradiction: {','.join(bad)}")
            elif not whole:
                conflict_units.add(g[0].unit)

        by_unit: dict[str, list[_Ev]] = {}
        for e in evs:
            by_unit.setdefault(e.unit, []).append(e)
        for f in layout.fields:
            if f.vendor_specific:
                vs_skipped += 1
        for unit_key, offset in _units(layout):
            uevs = by_unit.get(unit_key, [])
            verdict, flags = _verdict(uevs)
            if unit_key in conflict_units:
                flags = flags | {"CONFLICT"}
            outcomes = tuple(sorted(
                (RuleOutcome(e.prep.rule.id, e.prep.rule.source, e.path, e.result, e.actual, e.reason)
                 for e in uevs), key=lambda o: (o.rule_id, o.target_path)))
            fields.append(FieldResult(inst.struct, inst.nsid, unit_key, offset, dec[unit_key],
                                      verdict, frozenset(flags), outcomes, None))

    fields.sort(key=lambda f: (_struct_order(f.struct), -1 if f.nsid is None else f.nsid,
                               f.offset, f.unit))
    return RunResult(
        fields=tuple(fields), db_errors=tuple(sorted(db_errors)),
        unknown_keys={k: tuple(sorted(v)) for k, v in sorted(unknown.items())},
        coverage=compute_coverage(layouts, rules, profile), vendor_specific_skipped=vs_skipped)


# ---- 커버리지 ----

def compute_coverage(layouts: dict[str, Layout], rules: list[Rule], profile: Profile
                     ) -> tuple[Coverage, ...]:
    active = [r for r in list(rules) + generate_auto_rules(layouts) if r.source in profile.specs]
    out: list[Coverage] = []
    for name in sorted(layouts, key=_struct_order):
        layout = layouts[name]
        leaves = _leaves(layout)
        total = sum(len(b) for b in leaves.values())
        sets: dict[str, set[tuple[str, int]]] = {"value": set(), "format": set()}
        touched: set[str] = set()
        for r in active:
            if r.target.struct != name:
                continue
            try:
                expansions = expand_target(r.target, layout)
            except ValueError:
                continue
            for key, _idx, bits in expansions:
                touched.add(_unit_of(key))
                lks = [key] if key in leaves else [k for k in leaves if k.startswith(key + ".")]
                for lk in lks:
                    for b in leaves[lk]:
                        if bits is None or bits[1] <= b <= bits[0]:
                            sets[r.kind].add((lk, b))
        uncovered = tuple(u for u, _ in _units(layout) if u not in touched)
        out.append(Coverage(name, total, len(sets["value"]), len(sets["format"]), uncovered))
    return tuple(out)
