"""규칙 when/expect 식 언어: 손으로 쓴 토크나이저, 재귀 하강 파서, 평가기.

Python의 eval/compile은 쓰지 않는다. 문법은 설계 문서(Task 2)를 따른다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, Union

Value = Union[int, bytes, bool, str]


class ExprError(Exception):
    """문법/타입 오류. 메시지에 열(col, 1부터)을 넣는다."""


class Unknown(Exception):
    """값이 없는 참조. reason은 리포트에 모아 보여줄 키다."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Ref:
    scope: str  # 구조 이름, "profile", "$", "$i"
    path: str
    bits: tuple[int, int] | None  # (hi, lo)


class Env(Protocol):
    def resolve(self, ref: Ref) -> Value: ...


# ---- 노드 ----

@dataclass(frozen=True)
class Node:
    col: int


@dataclass(frozen=True)
class Lit(Node):
    value: Value


@dataclass(frozen=True)
class RefNode(Node):
    ref: Ref


@dataclass(frozen=True)
class Not(Node):
    operand: Node


@dataclass(frozen=True)
class BinOp(Node):
    op: str
    left: Node
    right: Node


@dataclass(frozen=True)
class Call(Node):
    name: str
    args: tuple[Node, ...]


@dataclass(frozen=True)
class SetLit(Node):
    items: tuple[Node, ...]


# ---- 토크나이저 ----

@dataclass(frozen=True)
class Tok:
    kind: str  # INT STR ID OP EOF
    value: object
    col: int


_INT_RE = re.compile(r"0[xX][0-9a-fA-F]+|0[bB][01]+|\d+")
_ID_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:-[A-Za-z0-9_]+)*")
_OPS = ("==", "!=", "<=", ">=", "<<", "<", ">", "+", "-", "*", "&",
        "(", ")", "[", "]", "{", "}", ",", ".", ":")
_IDCHAR_RE = re.compile(r"[A-Za-z0-9_]")


def _tokenize(src: str) -> list[Tok]:
    toks: list[Tok] = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        col = i + 1
        if c.isspace():
            i += 1
        elif c == "$":
            if src.startswith("i", i + 1) and not _IDCHAR_RE.match(src, i + 2):
                toks.append(Tok("ID", "$i", col))
                i += 2
            else:
                toks.append(Tok("ID", "$", col))
                i += 1
        elif c.isdigit():
            m = _INT_RE.match(src, i)
            assert m
            if _IDCHAR_RE.match(src, m.end()):
                raise ExprError(f"잘못된 숫자 (col {col})")
            toks.append(Tok("INT", int(m.group(), 0), col))
            i = m.end()
        elif c in "'\"":
            j = i + 1
            buf = []
            while j < n and src[j] != c:
                if src[j] == "\\" and j + 1 < n:
                    j += 1
                buf.append(src[j])
                j += 1
            if j >= n:
                raise ExprError(f"닫히지 않은 문자열 (col {col})")
            toks.append(Tok("STR", "".join(buf), col))
            i = j + 1
        elif c.isalpha() or c == "_":
            m = _ID_RE.match(src, i)
            assert m
            toks.append(Tok("ID", m.group(), col))
            i = m.end()
        else:
            for op in _OPS:
                if src.startswith(op, i):
                    toks.append(Tok("OP", op, col))
                    i += len(op)
                    break
            else:
                raise ExprError(f"예상치 못한 문자 {c!r} (col {col})")
    toks.append(Tok("EOF", None, n + 1))
    return toks


# ---- 파서 ----

_FUNCS = ("ascii", "ljust", "popcount")
_CMP_OPS = ("==", "!=", "<=", ">=", "<", ">")
_STRUCT_RE = re.compile(r"id-[a-z-]+")


class _Parser:
    def __init__(self, src: str):
        self.toks = _tokenize(src)
        self.pos = 0

    @property
    def cur(self) -> Tok:
        return self.toks[self.pos]

    def peek(self, k: int = 1) -> Tok:
        return self.toks[min(self.pos + k, len(self.toks) - 1)]

    def next(self) -> Tok:
        t = self.cur
        self.pos += 1
        return t

    def err(self, msg: str, tok: Tok | None = None) -> ExprError:
        t = tok or self.cur
        return ExprError(f"{msg} (col {t.col})")

    def is_op(self, v: str, tok: Tok | None = None) -> bool:
        t = tok or self.cur
        return t.kind == "OP" and t.value == v

    def is_kw(self, v: str) -> bool:
        return self.cur.kind == "ID" and self.cur.value == v

    def expect_op(self, v: str) -> Tok:
        if not self.is_op(v):
            raise self.err(f"{v!r} 필요")
        return self.next()

    def expect_int(self) -> int:
        if self.cur.kind != "INT":
            raise self.err("정수 필요")
        return self.next().value  # type: ignore[return-value]

    def parse_all(self) -> Node:
        node = self.parse_or()
        if self.cur.kind != "EOF":
            raise self.err("식 뒤에 남은 토큰")
        return node

    def parse_or(self) -> Node:
        left = self.parse_and()
        while self.is_kw("or"):
            t = self.next()
            left = BinOp(t.col, "or", left, self.parse_and())
        return left

    def parse_and(self) -> Node:
        left = self.parse_not()
        while self.is_kw("and"):
            t = self.next()
            left = BinOp(t.col, "and", left, self.parse_not())
        return left

    def parse_not(self) -> Node:
        if self.is_kw("not"):
            t = self.next()
            return Not(t.col, self.parse_not())
        return self.parse_cmp()

    def parse_cmp(self) -> Node:
        left = self.parse_sum()
        t = self.cur
        if t.kind == "OP" and t.value in _CMP_OPS:
            self.next()
            return BinOp(t.col, t.value, left, self.parse_sum())  # type: ignore[arg-type]
        if self.is_kw("in"):
            self.next()
            right = self.parse_sum()
            if not isinstance(right, SetLit):
                raise self.err("'in' 오른쪽은 {...} 집합이어야 함", t)
            return BinOp(t.col, "in", left, right)
        return left

    def parse_sum(self) -> Node:
        left = self.parse_term()
        while self.cur.kind == "OP" and self.cur.value in ("+", "-"):
            t = self.next()
            left = BinOp(t.col, t.value, left, self.parse_term())  # type: ignore[arg-type]
        return left

    def parse_term(self) -> Node:
        left = self.parse_atom()
        while self.cur.kind == "OP" and self.cur.value in ("*", "<<", "&"):
            t = self.next()
            left = BinOp(t.col, t.value, left, self.parse_atom())  # type: ignore[arg-type]
        return left

    def parse_bits_body(self) -> tuple[int, int]:
        """'[' 는 이미 소비됨. INT (':' INT)? ']' 를 읽는다."""
        col_tok = self.cur
        hi = self.expect_int()
        lo = hi
        if self.is_op(":"):
            self.next()
            lo = self.expect_int()
        self.expect_op("]")
        if hi < lo:
            raise self.err("비트 범위는 [hi:lo] (hi >= lo)", col_tok)
        return hi, lo

    def parse_atom(self) -> Node:
        t = self.cur
        if t.kind == "INT":
            self.next()
            return Lit(t.col, t.value)  # type: ignore[arg-type]
        if t.kind == "STR":
            self.next()
            return Lit(t.col, t.value)  # type: ignore[arg-type]
        if t.kind == "OP":
            if t.value == "(":
                self.next()
                node = self.parse_or()
                self.expect_op(")")
                return node
            if t.value == "{":
                self.next()
                items = [self.parse_or()]
                while self.is_op(","):
                    self.next()
                    items.append(self.parse_or())
                self.expect_op("}")
                return SetLit(t.col, tuple(items))
            raise self.err(f"예상치 못한 토큰 {t.value!r}")
        if t.kind != "ID":
            raise self.err("식이 필요함")
        name: str = t.value  # type: ignore[assignment]
        if name in ("true", "false"):
            self.next()
            return Lit(t.col, name == "true")
        if name == "$":
            self.next()
            bits = None
            if self.is_op("["):
                self.next()
                bits = self.parse_bits_body()
            return RefNode(t.col, Ref("$", "", bits))
        if name == "$i":
            self.next()
            return RefNode(t.col, Ref("$i", "", None))
        if name == "profile":
            return self.parse_profile()
        if name in _FUNCS:
            return self.parse_call()
        if _STRUCT_RE.fullmatch(name):
            return self.parse_struct()
        raise self.err(f"알 수 없는 이름 {name!r}")

    def parse_profile(self) -> Node:
        t = self.next()
        self.expect_op(".")
        kind = self.cur
        if kind.kind != "ID" or kind.value not in ("features", "values"):
            raise self.err("profile.features 또는 profile.values 필요")
        self.next()
        self.expect_op(".")
        if self.cur.kind != "ID":
            raise self.err("이름 필요")
        nm = self.next().value
        return RefNode(t.col, Ref("profile", f"{kind.value}.{nm}", None))

    def parse_call(self) -> Node:
        t = self.next()
        self.expect_op("(")
        args = [self.parse_or()]
        while self.is_op(","):
            self.next()
            args.append(self.parse_or())
        self.expect_op(")")
        if len(args) != 1:
            raise self.err(f"{t.value}()는 인자 1개", t)
        return Call(t.col, t.value, tuple(args))  # type: ignore[arg-type]

    def parse_struct(self) -> Node:
        t = self.next()
        self.expect_op(".")
        if self.cur.kind != "ID":
            raise self.err("필드 이름 필요")
        path: str = self.next().value  # type: ignore[assignment]
        bits: tuple[int, int] | None = None
        while True:
            if self.is_op("."):
                nxt = self.peek()
                if nxt.kind != "ID":
                    raise self.err("필드 이름 필요", nxt)
                self.next()
                path += "." + self.next().value  # type: ignore[operator]
            elif self.is_op("["):
                # 콜론이 있으면 항상 bits. 없으면 뒤에 '.' 또는 '['가 올 때만 index.
                self.next()
                col_tok = self.cur
                first = self.expect_int()
                if self.is_op(":"):
                    self.next()
                    lo = self.expect_int()
                    self.expect_op("]")
                    if first < lo:
                        raise self.err("비트 범위는 [hi:lo] (hi >= lo)", col_tok)
                    bits = (first, lo)
                    break
                self.expect_op("]")
                if self.is_op(".") or self.is_op("["):
                    path += f"[{first}]"
                else:
                    bits = (first, first)
                    break
            else:
                break
        return RefNode(t.col, Ref(t.value, path, bits))  # type: ignore[arg-type]


def parse(src: str) -> Node:
    return _Parser(src).parse_all()


def refs(node: Node) -> set[Ref]:
    if isinstance(node, RefNode):
        return {node.ref}
    out: set[Ref] = set()
    if isinstance(node, Not):
        out |= refs(node.operand)
    elif isinstance(node, BinOp):
        out |= refs(node.left) | refs(node.right)
    elif isinstance(node, Call):
        for a in node.args:
            out |= refs(a)
    elif isinstance(node, SetLit):
        for a in node.items:
            out |= refs(a)
    return out


# ---- 평가 ----

def _is_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _need_bool(v: Value, node: Node, what: str) -> bool:
    if not isinstance(v, bool):
        raise ExprError(f"{what}에는 bool이 필요함 (col {node.col})")
    return v


def _need_int(v: Value, node: Node, what: str) -> int:
    if not _is_int(v):
        raise ExprError(f"{what}에는 정수가 필요함 (col {node.col})")
    return v  # type: ignore[return-value]


def _norm(a: Value, b: Value) -> tuple[Value, Value]:
    if isinstance(a, str) and isinstance(b, bytes):
        a = a.encode("latin-1")
    elif isinstance(a, bytes) and isinstance(b, str):
        b = b.encode("latin-1")
    return a, b


def _eq(a: Value, b: Value, node: Node) -> bool:
    a, b = _norm(a, b)
    num = (int, bool)
    if isinstance(a, num) and isinstance(b, num):
        return a == b
    if type(a) is not type(b):
        raise ExprError(f"타입이 다른 값 비교 (col {node.col})")
    return a == b


def evaluate(node: Node, env: Env) -> Value:
    if isinstance(node, Lit):
        return node.value
    if isinstance(node, RefNode):
        ref = node.ref
        v = env.resolve(Ref(ref.scope, ref.path, None))
        if ref.bits is not None:
            if not _is_int(v):
                raise ExprError(f"비트 선택은 정수에만 가능 (col {node.col})")
            hi, lo = ref.bits
            return (v >> lo) & ((1 << (hi - lo + 1)) - 1)  # type: ignore[operator]
        return v
    if isinstance(node, Not):
        return not _need_bool(evaluate(node.operand, env), node, "not")
    if isinstance(node, Call):
        v = evaluate(node.args[0], env)
        if node.name == "popcount":
            return bin(_need_int(v, node, "popcount")).count("1")
        if not isinstance(v, bytes):
            raise ExprError(f"{node.name}()에는 bytes가 필요함 (col {node.col})")
        if node.name == "ascii":
            return all(0x20 <= b <= 0x7E for b in v)
        return (not v) or v[0] != 0x20 or all(b == 0x20 for b in v)  # ljust
    if isinstance(node, SetLit):
        raise ExprError(f"집합은 'in' 오른쪽에서만 쓸 수 있음 (col {node.col})")
    assert isinstance(node, BinOp)
    op = node.op
    if op == "and":
        if not _need_bool(evaluate(node.left, env), node, "and"):
            return False
        return _need_bool(evaluate(node.right, env), node, "and")
    if op == "or":
        if _need_bool(evaluate(node.left, env), node, "or"):
            return True
        return _need_bool(evaluate(node.right, env), node, "or")
    if op == "in":
        left = evaluate(node.left, env)
        assert isinstance(node.right, SetLit)
        return any(_eq(left, evaluate(i, env), node) for i in node.right.items)
    left = evaluate(node.left, env)
    right = evaluate(node.right, env)
    if op == "==":
        return _eq(left, right, node)
    if op == "!=":
        return not _eq(left, right, node)
    if op in ("<", "<=", ">", ">="):
        a = _need_int(left, node, op)
        b = _need_int(right, node, op)
        return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
    a = _need_int(left, node, op)
    b = _need_int(right, node, op)
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "&":
        return a & b
    if op == "<<":
        if b < 0:
            raise ExprError(f"음수 시프트 (col {node.col})")
        return a << b
    raise ExprError(f"알 수 없는 연산자 {op} (col {node.col})")
