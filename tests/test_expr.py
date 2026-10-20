import pytest

from idharness.expr import ExprError, Ref, Unknown, evaluate, parse, refs


class DictEnv:
    """테스트용 Env. 키: (scope, path) 튜플 또는 "$" / "$i"."""

    def __init__(self, values):
        self.values = values

    def resolve(self, ref):
        key = ref.scope if ref.scope in ("$", "$i") else (ref.scope, ref.path)
        if key not in self.values:
            raise Unknown(key if isinstance(key, str) else f"{ref.scope}.{ref.path}")
        return self.values[key]


def test_bits_and_compare():
    env = DictEnv({("id-ctrl", "SQES"): 0x66})
    assert evaluate(parse("id-ctrl.SQES[7:4] == 6"), env) is True


def test_dollar_in_set_and_hex():
    assert evaluate(parse("$ in {0x0, 0b10}"), DictEnv({"$": 2})) is True


def test_hyphen_identifier_vs_minus():
    env = DictEnv({("id-ns", "NLBAF"): 3, "$i": 2})
    assert evaluate(parse("$i <= id-ns.NLBAF - 1"), env) is True


def test_profile_missing_raises_unknown():
    with pytest.raises(Unknown) as e:
        evaluate(parse("profile.features.sanitize"), DictEnv({}))
    assert e.value.reason == "profile.features.sanitize"


def test_ascii_and_ljust():
    assert evaluate(parse("ascii($) and ljust($)"), DictEnv({"$": b"AB  "})) is True
    assert evaluate(parse("ljust($)"), DictEnv({"$": b" AB "})) is False
    assert evaluate(parse("ascii($)"), DictEnv({"$": b"A\x00"})) is False


def test_refs_lists_struct_and_profile():
    r = refs(parse("id-ctrl.OACS[3] == 1 and profile.values.VID == $"))
    assert Ref("id-ctrl", "OACS", (3, 3)) in r and Ref("profile", "values.VID", None) in r


def test_parse_error_has_position():
    with pytest.raises(ExprError, match="col"):
        parse("$ == == 1")


def test_no_python_eval():
    with pytest.raises(ExprError):
        parse("__import__('os')")


def test_ref_shapes():
    r = refs(parse("$[7:4] == 1 and $i == 0 and profile.features.sanitize"))
    assert Ref("$", "", (7, 4)) in r
    assert Ref("$i", "", None) in r
    assert Ref("profile", "features.sanitize", None) in r


def test_index_vs_bits_split():
    r = refs(parse("id-ns.LBAF[2][3:0] == 9 and id-ctrl.PSD[0].MP == 1 and id-ctrl.PSD[0] == 1"))
    assert Ref("id-ns", "LBAF[2]", (3, 0)) in r
    assert Ref("id-ctrl", "PSD[0].MP", None) in r
    assert Ref("id-ctrl", "PSD", (0, 0)) in r


def test_unknown_reason_for_struct_ref():
    with pytest.raises(Unknown) as e:
        evaluate(parse("id-ctrl.SQES == 1"), DictEnv({}))
    assert e.value.reason == "id-ctrl.SQES"


def test_short_circuit_skips_unknown():
    env = DictEnv({"$": 0})
    assert evaluate(parse("$ == 1 and profile.features.x"), env) is False
    assert evaluate(parse("$ == 0 or profile.features.x"), env) is True
    with pytest.raises(Unknown):
        evaluate(parse("$ == 0 and profile.features.x"), env)


def test_string_vs_bytes_exact():
    assert evaluate(parse("$ == 'AB  '"), DictEnv({"$": b"AB  "})) is True
    assert evaluate(parse("$ == 'AB'"), DictEnv({"$": b"AB  "})) is False


def test_arith_and_bitand():
    env = DictEnv({"$": 0b1010})
    assert evaluate(parse("$ & 0x2 == 2"), env) is True
    assert evaluate(parse("1 << 3 + 1 == 9"), env) is True  # '+' binds looser than '<<'
    assert evaluate(parse("2 * 3 - 1 == 5"), env) is True


def test_popcount_and_not():
    assert evaluate(parse("popcount($) == 3"), DictEnv({"$": 0b10101})) is True
    assert evaluate(parse("not (popcount($) == 3)"), DictEnv({"$": 0b10101})) is False


def test_ljust_edge_cases():
    assert evaluate(parse("ljust($)"), DictEnv({"$": b"    "})) is True
    assert evaluate(parse("ljust($)"), DictEnv({"$": b""})) is True


def test_bit_slice_on_non_int_is_error():
    with pytest.raises(ExprError):
        evaluate(parse("$[3:0] == 1"), DictEnv({"$": b"A"}))


def test_unknown_function_is_parse_error():
    with pytest.raises(ExprError, match="col"):
        parse("len($) == 1")


def test_in_requires_set_literal():
    with pytest.raises(ExprError):
        parse("$ in 3")


def test_trailing_garbage_and_bad_chars():
    for bad in ("$ == 1 )", "$ == ", "$ ; 1", "id-ctrl.", "$[1:2:3]"):
        with pytest.raises(ExprError, match="col"):
            parse(bad)


def test_bool_literals():
    assert evaluate(parse("true and not false"), DictEnv({})) is True
