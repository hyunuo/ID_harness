"""규칙 모델/로드, 자동 규칙 생성, 정적 검사."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from idharness.expr import ExprError, Node, Ref, parse, refs
from idharness.layout import FieldDef, Layout, field_width_bits
from idharness.sources import Source

AUTO_FILE = "<auto>"
LEVELS = ("shall", "should")
KINDS = ("value", "format")
STATUSES = ("cross-checked", "uncertain", "corrected")
POLICY_RANK = 30
_REQUIRED = ("id", "source", "ref", "target", "expect", "level", "kind", "status")

Bits = tuple[int, int]


@dataclass(frozen=True)
class Target:
    struct: str
    field: str
    index: int | Literal["*"] | None
    sub: str | None
    bits: Bits | None


@dataclass(frozen=True)
class Rule:
    id: str
    source: str
    ref: str
    target: Target
    when_src: str | None
    expect_src: str
    when: Node | None
    expect: Node
    level: str
    kind: str
    status: str
    overrides: tuple[str, ...]
    note: str
    history: tuple[dict, ...]
    auto: bool
    file: str


# ---- 비트/target 파싱 ----

def _parse_bits_text(text: str) -> Bits:
    m = re.fullmatch(r"\s*(\d+)\s*(?::\s*(\d+)\s*)?", text)
    if not m:
        raise ValueError(f"잘못된 비트 표기 [{text}]")
    hi = int(m.group(1))
    lo = int(m.group(2)) if m.group(2) is not None else hi
    if hi < lo:
        raise ValueError(f"비트 범위는 [hi:lo] (hi >= lo): [{text}]")
    return hi, lo


_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
_TARGET_RE = re.compile(rf"(id-[a-z-]+)\.({_NAME})(.*)", re.S)
_BRACKET_RE = re.compile(r"\[([^\]]*)\]")


def parse_target(s: str) -> Target:
    m = _TARGET_RE.fullmatch(s.strip())
    if not m:
        raise ValueError(f"잘못된 target {s!r}")
    struct, field, rest = m.groups()
    index: int | Literal["*"] | None = None
    sub: str | None = None
    bits: Bits | None = None
    pos = 0

    def brackets() -> None:
        nonlocal pos, index, bits
        while pos < len(rest) and rest[pos] == "[":
            bm = _BRACKET_RE.match(rest, pos)
            if not bm:
                raise ValueError(f"닫히지 않은 대괄호: {s!r}")
            body = bm.group(1).strip()
            pos = bm.end()
            if bits is not None:
                raise ValueError(f"비트 선택 뒤에 대괄호가 더 있음: {s!r}")
            if sub is None and index is None:
                if body == "*":
                    index = "*"
                elif re.fullmatch(r"\d+", body):
                    index = int(body)
                else:
                    bits = _parse_bits_text(body)
            else:
                bits = _parse_bits_text(body)

    brackets()
    if pos < len(rest) and rest[pos] == ".":
        if bits is not None:
            raise ValueError(f"비트 선택 뒤에 하위 필드가 올 수 없음: {s!r}")
        sm = re.compile(rf"\.({_NAME})").match(rest, pos)
        if not sm:
            raise ValueError(f"하위 필드 이름 필요: {s!r}")
        sub = sm.group(1)
        pos = sm.end()
        brackets()
    if pos != len(rest):
        raise ValueError(f"target 뒤에 남은 문자 {rest[pos:]!r}: {s!r}")
    return Target(struct, field, index, sub, bits)


# ---- 레이아웃 기준 해석 (검증과 평가가 공유) ----

def _find_field(layout: Layout, name: str) -> FieldDef:
    for f in layout.fields:
        if f.name == name:
            return f
    raise ValueError(f"{layout.structure}에 필드 {name} 없음")


def _locate(layout: Layout, f: FieldDef, index: int | None, sub: str | None,
            bits: Bits | None) -> tuple[str, Bits | None]:
    """검증 후 (decode 키, bits) 반환."""
    where = f"{layout.structure}.{f.name}"
    if f.count > 1:
        if index is None:
            raise ValueError(f"{where}는 배열(count {f.count}): index 필요")
        if not 0 <= index < f.count:
            raise ValueError(f"{where}[{index}] index range 0..{f.count - 1} 초과")
        key = f"{f.name}[{index}]"
    else:
        if index is not None:
            raise ValueError(f"{where}는 배열이 아니므로(not an array) index를 쓸 수 없음")
        key = f.name
    if sub is not None:
        names = {e.name: e for e in f.element}
        if f.type != "struct" or sub not in names:
            raise ValueError(f"{where}에 하위 필드 {sub} 없음")
        width = names[sub].size * 8
        key += f".{sub}"
        where += f".{sub}"
    else:
        width = field_width_bits(f)
    if bits is not None:
        hi, lo = bits
        if lo < 0 or hi < lo:
            raise ValueError(f"{where} 잘못된 비트 범위 {hi}:{lo}")
        if hi >= width:
            raise ValueError(f"{where} 비트 {hi}:{lo}가 폭 {width}를 넘음 (width)")
    return key, bits


_PATH_RE = re.compile(rf"({_NAME})(?:\[(\d+)\])?(?:\.({_NAME}))?")


def normalize_ref(ref: Ref, layouts: dict[str, Layout]) -> Ref:
    if ref.scope in ("$", "$i", "profile"):
        return ref
    layout = layouts.get(ref.scope)
    if layout is None:
        raise ValueError(f"알 수 없는 구조 {ref.scope}")
    m = _PATH_RE.fullmatch(ref.path)
    if not m:
        raise ValueError(f"{ref.scope}.{ref.path}: 지원하지 않는 경로")
    name, idx_s, sub = m.groups()
    f = _find_field(layout, name)
    index = int(idx_s) if idx_s is not None else None
    bits = ref.bits
    if index is None and sub is None and f.count > 1 and bits is not None and bits[0] == bits[1]:
        index, bits = bits[0], None
    key, bits = _locate(layout, f, index, sub, bits)
    return Ref(ref.scope, key, bits)


def expand_target(target: Target, layout: Layout
                  ) -> list[tuple[str, int | None, Bits | None]]:
    if target.struct != layout.structure:
        raise ValueError(f"target 구조 {target.struct}가 레이아웃 {layout.structure}와 다름")
    f = _find_field(layout, target.field)
    index, bits = target.index, target.bits
    if (f.count == 1 and isinstance(index, int) and target.sub is None and bits is None):
        index, bits = None, (index, index)
    if index == "*":
        if f.count <= 1:
            raise ValueError(f"{layout.structure}.{f.name}는 배열이 아니므로(not an array) [*]를 쓸 수 없음")
        indices: list[int | None] = list(range(f.count))
    else:
        indices = [index]  # type: ignore[list-item]
    out = []
    for i in indices:
        key, b = _locate(layout, f, i, target.sub, bits)
        out.append((key, i, b))
    return out


# ---- 로드 ----

def source_rank(source_id: str, sources: dict[str, Source]) -> int | None:
    if source_id in sources:
        return sources[source_id].rank
    if source_id.startswith("policy-"):
        return POLICY_RANK
    return None


def _build_rule(item: dict, file: str) -> Rule:
    missing = [k for k in _REQUIRED if k not in item]
    if missing:
        raise ValueError(f"필수 키 없음: {', '.join(missing)}")
    when_src = item.get("when")
    if when_src is None or str(when_src).strip() == "always":
        when_src = None
    else:
        when_src = str(when_src)
    expect_src = str(item["expect"])
    overrides = item.get("overrides") or ()
    if isinstance(overrides, str) or not isinstance(overrides, (list, tuple)):
        raise ValueError("overrides는 id 리스트여야 함")
    try:
        when = parse(when_src) if when_src is not None else None
        expect = parse(expect_src)
    except ExprError as e:
        raise ValueError(f"식 오류: {e}") from None
    return Rule(
        id=str(item["id"]), source=str(item["source"]), ref=str(item["ref"]),
        target=parse_target(str(item["target"])), when_src=when_src, expect_src=expect_src,
        when=when, expect=expect, level=str(item["level"]), kind=str(item["kind"]),
        status=str(item["status"]), overrides=tuple(str(o) for o in overrides),
        note=str(item.get("note", "") or ""),
        history=tuple(item.get("history") or ()), auto=False, file=file)


def load_rules(root: Path) -> tuple[list[Rule], list[str]]:
    root = Path(root)
    rules: list[Rule] = []
    errors: list[str] = []
    if not root.is_dir():
        return rules, errors
    for p in sorted(root.rglob("*.yaml")):
        file = p.relative_to(root).as_posix()
        try:
            doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        except (yaml.YAMLError, UnicodeDecodeError) as e:
            errors.append(f"{file}: ?: YAML 오류: {str(e).splitlines()[0] if str(e) else e}")
            continue
        if doc is None:
            continue
        if not isinstance(doc, list):
            errors.append(f"{file}: ?: 파일은 규칙 리스트여야 함")
            continue
        for item in doc:
            if not isinstance(item, dict):
                errors.append(f"{file}: ?: 규칙은 매핑이어야 함")
                continue
            rid = str(item.get("id", "?"))
            try:
                rules.append(_build_rule(item, file))
            except ValueError as e:
                errors.append(f"{file}: {rid}: {e}")
    rules.sort(key=lambda r: (r.id, r.file))
    return rules, errors


# ---- 자동 규칙 ----

def _bits_label(b: Bits) -> str:
    return f"{b[0]}_{b[1]}"


def generate_auto_rules(layouts: dict[str, Layout]) -> list[Rule]:
    out: list[Rule] = []

    def add(layout: Layout, rid: str, target: Target, expect: str, source: str, ref: str) -> None:
        out.append(Rule(
            id=rid, source=source, ref=ref, target=target, when_src=None, expect_src=expect,
            when=None, expect=parse(expect), level="shall", kind="format",
            status=layout.status, overrides=(), note="", history=(), auto=True, file=AUTO_FILE))

    def scan(layout: Layout, top: FieldDef, f: FieldDef, sub: str | None, ref: str) -> None:
        if f.vendor_specific:
            return
        s = layout.structure
        idx = "*" if top.count > 1 else None
        base = f"AUTO-{s}-{top.name}" + (f"-{sub}" if sub else "")
        if f.reserved:
            add(layout, f"{base}-RSVD", Target(s, top.name, idx, sub, None), "zero($)",
                f.source, ref)
            return
        if f.type == "ascii":
            add(layout, f"{base}-ASCII", Target(s, top.name, idx, sub, None),
                "ascii($) and ljust($)", f.source, "Base 2.1 §1.4.2")
        for b in f.bits:
            if b.reserved:
                add(layout, f"{base}-{_bits_label((b.hi, b.lo))}-RSVD",
                    Target(s, top.name, idx, sub, (b.hi, b.lo)), "zero($)", f.source, ref)

    for name in sorted(layouts):
        layout = layouts[name]
        for f in layout.fields:
            scan(layout, f, f, None, f.ref)
            if f.type == "struct" and not f.vendor_specific and not f.reserved:
                for e in f.element:
                    scan(layout, f, e, e.name, e.ref or f.ref)
    out.sort(key=lambda r: r.id)
    return out


# ---- 정적 검사 ----

def check_rules(rules: list[Rule], layouts: dict[str, Layout], sources: dict[str, Source],
                features: dict) -> list[str]:
    errs: list[str] = []
    by_id: dict[str, Rule] = {}
    for r in rules:
        if r.id in by_id:
            errs.append(f"{r.file}: {r.id}: duplicate rule id (first in {by_id[r.id].file})")
        else:
            by_id[r.id] = r

    for r in rules:
        def err(msg: str, r: Rule = r) -> None:
            errs.append(f"{r.file}: {r.id}: {msg}")

        if r.level not in LEVELS:
            err(f"level 값 오류 {r.level!r} (허용: {', '.join(LEVELS)})")
        if r.kind not in KINDS:
            err(f"kind 값 오류 {r.kind!r} (허용: {', '.join(KINDS)})")
        if r.status not in STATUSES:
            err(f"status 값 오류 {r.status!r} (허용: {', '.join(STATUSES)})")
        rank = source_rank(r.source, sources)
        if rank is None:
            err(f"등록되지 않은 source {r.source!r}")

        wildcard = r.target.index == "*"
        layout = layouts.get(r.target.struct)
        if layout is None:
            err(f"target 구조 {r.target.struct} 레이아웃 없음")
        else:
            try:
                expand_target(r.target, layout)
            except ValueError as e:
                err(f"target 오류: {e}")

        nodes = [n for n in (r.when, r.expect) if n is not None]
        seen: set[Ref] = set()
        for n in nodes:
            seen |= refs(n)
        for ref in sorted(seen, key=lambda x: (x.scope, x.path, x.bits or (-1, -1))):
            if ref.scope == "$i":
                if not wildcard:
                    err("$i는 [*] target에서만 쓸 수 있음")
            elif ref.scope == "profile":
                if ref.path.startswith("features.") and ref.path[len("features."):] not in features:
                    err(f"features.yaml에 없는 feature {ref.path[len('features.'):]!r}")
            elif ref.scope != "$":
                if r.target.struct == "id-ctrl" and ref.scope == "id-ns":
                    err(f"id-ctrl 규칙은 id-ns를 참조할 수 없음 ({ref.scope}.{ref.path})")
                    continue
                try:
                    normalize_ref(ref, layouts)
                except ValueError as e:
                    err(f"참조 오류: {e}")

        for oid in r.overrides:
            o = by_id.get(oid)
            if o is None:
                err(f"overrides 대상 {oid!r} 없음")
                continue
            orank = source_rank(o.source, sources)
            if rank is not None and orank is not None and not orank < rank:
                err(f"overrides 대상 {oid!r}의 rank({orank})가 이 규칙({rank})보다 낮지 않음")
    return errs
