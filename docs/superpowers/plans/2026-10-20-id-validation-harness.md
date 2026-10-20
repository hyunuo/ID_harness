# NVMe Identify 검증 하네스 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 스펙별 전문 에이전트가 만든 규칙 DB를 기준으로, 테스트 PC의 id-ctrl/id-ns 덤프를 LLM 없이 결정론적으로 판정하고 근거가 붙은 리포트를 내는 하네스를 만든다.

**Architecture:** 오피스 PC에 Python 패키지 `idharness`(uv 실행)를 둔다. 이 패키지는 다음 일을 한다.
- ssh로 테스트 PC에서 nvme-cli 바이너리/텍스트 덤프를 수집한다.
- 레이아웃 YAML로 바이너리를 디코드한다.
- 규칙 YAML(작은 전용 식 언어)을 평가해 필드별 판정과 마크다운 리포트를 만든다.

규칙과 레이아웃은 `.claude/agents`의 스펙 전문 에이전트가 원본 스펙에서 추출하고, `rule-verifier`가 PDF와 교차 검증한다. 이 흐름은 `.claude/skills`로 묶는다.

**Tech Stack:** Python ≥3.12 (uv 관리), PyYAML, pytest, OpenSSH 클라이언트, Claude Code 서브에이전트와 skill.

**Spec:** `docs/superpowers/specs/2026-10-20-id-validation-harness-design.md`

## Global Constraints

- 판정(검증 엔진)에는 LLM을 사용하지 않는다. 같은 입력이면 출력이 바이트 단위로 같아야 한다. 이를 위해 규칙은 id 순으로, 필드는 오프셋 순으로 정렬한다.
- 런타임 의존성은 `pyyaml`만 쓴다. 개발 의존성은 `pytest`만 쓴다. 실행은 `uv run ...`으로 한다.
- 기준 스펙 기본값은 `nvme-base-2.1 + nvm-cs-1.1 + ocp-2.6`이고, 레이아웃 세트는 `nvme-2.1`이다.
- 출처 우선순위 rank는 `nvme-base-2.1`=10, `nvm-cs-1.1`=10, `ocp-2.6`=20이다. `policy-*`는 30으로 예약한다(1차에서는 구현하지 않음).
- 규칙 필드 구성: `id, source, ref, target, when, expect, level(shall|should), kind(value|format), status(cross-checked|uncertain|corrected), overrides, note, history`.
- 판정 등급: `FAIL, WARN, PASS, PASS_FORMAT, NO_RULE`. 플래그: `CHANGED, UNCERTAIN, CONFLICT, UNKNOWN, OVERRIDDEN`. 리포트에는 한국어 라벨로 표시한다.
- 덮어쓰기는 상위 rank 규칙이 `overrides`로 명시할 때만 한다. 그 외에는 규칙을 누적 적용한다.
- 테스트 PC에는 아무것도 설치하지 않는다. 장치는 사용자가 지정하며 `^/dev/nvme\d+$`에 맞아야 한다(컨트롤러 char device). 명령은 `sudo nvme ...`이고 sudo는 비밀번호 없이 실행된다.
- namespace는 `nvme list-ns`가 돌려주는 활성 NSID만 수집한다.
- vendor specific 필드(`vendor_specific: true`)는 판정과 커버리지에서 제외한다.
- 모든 파일 I/O는 `encoding="utf-8"`로 한다. CLI 시작 시 `sys.stdout.reconfigure(encoding="utf-8")`를 호출한다. Windows PowerShell 5.1에서 한국어가 깨지지 않게 하기 위해서다.
- `runs/`는 git에 넣지 않는다(`.gitignore`). 리포트에는 규칙 DB의 git commit hash를 기록한다.

## Review Focus

1. **잘린 덤프나 오류 텍스트가 섞인 덤프:** ssh 출력이 짧거나 nvme 오류 메시지가 `.bin`에 들어간 경우다. `validate`는 레이아웃 크기와 다르면 디코드하지 않고 파일명과 실제/기대 크기를 담은 오류로 멈춰야 한다. → Task 6 `test_load_run_rejects_wrong_size`
2. **수집 중 명령 실패:** 장치가 없거나, sudo가 실패하거나, list-ns 결과가 비어 있는 경우다. `collect`는 stderr를 보여주고 중단해야 한다. 완성된 것처럼 보이는 run 폴더(meta.json 있음)를 남기면 안 된다. → Task 7 `test_collect_failure_leaves_no_meta`
3. **제품 정보에 없는 기능이나 값을 규칙이 참조하는 경우:** 크래시하거나 조용히 PASS하면 안 된다. 해당 규칙은 UNKNOWN으로 처리하고, 리포트에 "프로필에 추가 필요: features.sanitize" 식으로 키별로 모아 보여준다. → Task 4 `test_missing_profile_key_is_unknown_not_pass`
4. **규칙 파일 오타나 깨진 식:** 필드명 오타, 중복 id, 하위 rank를 향하지 않는 overrides 등이다. `check-rules`는 파일명과 규칙 id가 붙은 오류를 **모두** 나열해야 한다(첫 오류에서 멈추지 않음). `validate`는 DB 오류가 있으면 실행을 거부해야 한다. → Task 3 `test_check_rules_collects_all_errors`, Task 6 `test_validate_refuses_broken_db`
5. **형식이 다른 기존 텍스트 로그:** `-H` 상세 줄이 섞이거나, 모르는 키가 있거나, 빈 줄과 헤더가 있는 경우다. 크래시 없이 무시하고 unmapped 목록에 올려야 한다. CHANGED는 매핑된 필드에만 붙인다. → Task 5 `test_parse_ignores_verbose_and_unknown_lines`

---

## 파일 구조

```
pyproject.toml                       uv 프로젝트, 엔트리포인트 idharness
.gitignore                           runs/, .venv/, __pycache__/
src/idharness/
  __init__.py
  sources.py      출처 레지스트리 로드 (rank)
  layout.py       레이아웃 모델/로드/정합성 검사/decode/encode
  expr.py         when/expect 식 파서·평가기 (eval 미사용)
  profile.py      제품 정보 로드 (extends 병합, features 어휘 검증)
  rules.py        규칙 모델/로드/자동 규칙 생성/정적 검사
  engine.py       규칙 평가, 덮어쓰기, 충돌, 필드 판정 집계, 커버리지
  baseline.py     nvme-cli 텍스트 로그 파서 + CHANGED 비교
  runs.py         run 폴더 로드(meta.json, *.bin 크기 검증)
  report.py       마크다운 리포트 + 터미널 요약
  collect.py      ssh 수집
  cli.py          collect | validate | check-rules | coverage
data/
  sources.yaml
  features.yaml                       제품 정보 features 어휘 (이름 → 설명, 관련 비트)
  baseline_aliases.yaml               nvme-cli 텍스트 키 → 레이아웃 경로 (기본은 대문자화)
  layouts/nvme-2.1/id-ctrl.yaml       Task 9
  layouts/nvme-2.1/id-ns.yaml         Task 13
  rules/<source>/<struct>/<group>.yaml
  profiles/default.yaml
  baselines/<product>/                id-ctrl.txt, id-ns-<nsid>.txt
.claude/agents/nvme-spec-expert.md, ocp-spec-expert.md, rule-verifier.md
.claude/skills/id-validate/SKILL.md, id-rule-extract/SKILL.md, id-rule-fix/SKILL.md
docs/adding-a-spec.md
tests/
  fixtures/layouts/mini/id-ctrl.yaml, id-ns.yaml   엔진 테스트용 소형 레이아웃
  fixtures/baseline/id-ctrl.txt, id-ns-1.txt       합성 nvme-cli 텍스트 로그
  test_*.py
  rules/test_<group>.py                            추출 그룹별 회귀 테스트
```

### 소형 테스트 레이아웃 (Task 1에서 생성, 이후 엔진 테스트 전부가 사용)

`tests/fixtures/layouts/mini/id-ctrl.yaml` (size 16, source `nvme-base-2.1`):

| 필드 | offset | size | type | 비고 |
|---|---|---|---|---|
| VID | 0 | 2 | uint | |
| SN | 2 | 4 | ascii | |
| OACS | 6 | 2 | uint | bits: 0 SECS, 1 FMT, 2 DST, 3 NSMS, 15:4 reserved |
| SQES | 8 | 1 | uint | bits: 7:4 MAXES, 3:0 MINES |
| RSVD9 | 9 | 1 | bytes | reserved: true |
| VS | 10 | 2 | bytes | vendor_specific: true |
| PSD | 12 | 2 | struct, count 2 (원소 1바이트) | 원소 필드: MP(offset 0, size 1, uint) |

`tests/fixtures/layouts/mini/id-ns.yaml` (size 8, source `nvm-cs-1.1`):

| 필드 | offset | size | type | 비고 |
|---|---|---|---|---|
| NSZE | 0 | 4 | uint | |
| NLBAF | 4 | 1 | uint | |
| LBAF | 5 | 3 | uint, count 3 (원소 1바이트) | bits: 3:0 LBADS, 7:4 reserved |

---

### Task 1: 프로젝트 골격, 출처 레지스트리, 레이아웃 모델

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `src/idharness/__init__.py`, `src/idharness/sources.py`, `src/idharness/layout.py`, `data/sources.yaml`, `tests/fixtures/layouts/mini/id-ctrl.yaml`, `tests/fixtures/layouts/mini/id-ns.yaml`
- Test: `tests/test_layout.py`, `tests/test_sources.py`

**Interfaces:**
- Produces:
  - `Source(id: str, title: str, version: str, file: str, rank: int)`; `load_sources(path: Path) -> dict[str, Source]`
  - `BitDef(name: str, hi: int, lo: int, reserved: bool, title: str)`
  - `FieldDef(name: str, offset: int, size: int, type: Literal["uint","ascii","bytes","struct"], title: str, ref: str, source: str, reserved: bool, vendor_specific: bool, bits: tuple[BitDef, ...], count: int, element: tuple[FieldDef, ...])`
    - `count > 1`이면 배열이다. 원소 크기는 `size // count`다.
    - `element`는 type=struct일 때 원소 내부 필드다(오프셋은 원소 기준).
  - `Layout(structure: str, size: int, source: str, status: str, fields: tuple[FieldDef, ...])`
  - `load_layout(path: Path) -> Layout`; `load_layout_set(root: Path) -> dict[str, Layout]` (key는 structure 이름)
  - `check_layout(layout: Layout) -> list[str]` — 바이트 갭과 겹침, 비트 겹침, 비트가 필드 폭을 넘는 경우, `size % count != 0`을 검사한다. 각 오류 메시지에 필드명을 넣는다.
  - `decode(layout: Layout, data: bytes) -> dict[str, int | bytes]`
    - 키는 정규 경로다: `"VID"`, `"PSD[0]"`, `"PSD[0].MP"`, `"LBAF[2]"`.
    - uint는 little-endian int, ascii와 bytes는 bytes로 디코드한다. struct 배열 원소 자체(`"PSD[0]"`)는 bytes다.
  - `encode(layout: Layout, values: dict[str, int | bytes]) -> bytes` — 지정하지 않은 바이트는 0이다. 테스트와 합성 덤프 생성에 쓴다.
  - `field_width_bits(field: FieldDef) -> int`

- [ ] **Step 1: uv 프로젝트를 만든다.**
  - `uv init --package --name idharness --python 3.12`를 실행하고 `pyyaml`과 `pytest`(dev)를 추가한다.
  - `[project.scripts] idharness = "idharness.cli:main"`을 등록한다.
  - `data/sources.yaml`에 세 출처를 넣는다. `file`은 `spec/` 아래 PDF 경로이고 rank는 Global Constraints 값이다.
  - 위 표대로 소형 레이아웃 두 개를 만든다.
- [ ] **Step 2: 실패하는 테스트를 쓴다.**

```python
def test_load_sources_ranks():
    s = load_sources(Path("data/sources.yaml"))
    assert s["ocp-2.6"].rank == 20 and s["nvme-base-2.1"].rank == 10

def test_mini_layout_is_consistent():
    assert check_layout(load_layout(MINI / "id-ctrl.yaml")) == []

def test_check_layout_reports_gap_and_overlap():
    # VID size를 3으로 바꾼 사본 → overlap with SN, RSVD9 제거한 사본 → gap at 9
    errs = check_layout(broken_layout)
    assert any("VID" in e and "overlap" in e for e in errs)
    assert any("gap" in e and "9" in e for e in errs)

def test_decode_roundtrip():
    lay = load_layout(MINI / "id-ctrl.yaml")
    raw = encode(lay, {"VID": 0x1E0F, "SN": b"AB12", "SQES": 0x66, "PSD[1].MP": 25})
    d = decode(lay, raw)
    assert d["VID"] == 0x1E0F and d["SN"] == b"AB12" and d["SQES"] == 0x66
    assert d["PSD[1].MP"] == 25 and d["PSD[0].MP"] == 0
    assert len(raw) == 16
```

- [ ] **Step 3: 실패를 확인한다.** `uv run pytest tests/test_layout.py tests/test_sources.py -v` → ImportError로 FAIL
- [ ] **Step 4: `sources.py`와 `layout.py`를 위 시그니처대로 구현한다.** YAML 키는 dataclass 필드명과 같게 하고, 비트 범위는 `"7:4"` 또는 `"3"` 문자열로 받는다.
- [ ] **Step 5: 통과를 확인한다.** 같은 명령 → PASS
- [ ] **Step 6: 커밋한다.** `git commit -m "feat: uv 프로젝트, 출처 레지스트리, 레이아웃 디코더"`

---

### Task 2: 식 언어 (when/expect)

**Files:**
- Create: `src/idharness/expr.py`
- Test: `tests/test_expr.py`

**Interfaces:**
- Consumes: 없음 (레이아웃과 독립)
- Produces:
  - `ExprError(Exception)` — 문법 오류. 메시지에 위치를 넣는다.
  - `Unknown(Exception)`, `reason: str` — 값이 없는 참조. 예: `"profile.features.sanitize"`, `"id-ctrl"`
  - `Ref(scope: str, path: str, bits: tuple[int, int] | None)`
    - `scope`는 구조 이름(`"id-ctrl"`, `"id-ns"`) 또는 `"profile"` 또는 `"$"`/`"$i"`다.
    - `path`의 예: `"SQES"`, `"PSD[0].MP"`, `"features.sanitize"`, `"values.VID"`
  - `parse(src: str) -> Node`; `refs(node: Node) -> set[Ref]`
  - `Env(Protocol)`: `resolve(ref: Ref) -> int | bytes | bool | str` — 값이 없으면 `Unknown`을 던진다.
  - `evaluate(node: Node, env: Env) -> int | bytes | bool | str`

**문법 (확정):**
```
or    := and ('or' and)*
and   := not ('and' not)*
not   := 'not' not | cmp
cmp   := sum (('=='|'!='|'<'|'<='|'>'|'>='|'in') sum)?
sum   := term (('+'|'-') term)*        # '-'는 앞뒤 공백 필수 (식별자에 '-' 허용)
term  := atom (('*'|'<<'|'&') atom)*
atom  := INT | STRING | 'true' | 'false' | '$' bits? | '$i'
       | STRUCT '.' NAME ('[' INT ']')? ('.' NAME)? bits?
       | 'profile' '.' ('features'|'values') '.' NAME
       | FUNC '(' or (',' or)* ')' | '(' or ')' | '{' or (',' or)* '}'
bits  := '[' INT (':' INT)? ']'        # [hi:lo] 또는 [n]
INT   := 10진 | 0x.. | 0b..
STRUCT:= 'id-' [a-z-]+
FUNC  := ascii(x)    # 모든 바이트가 0x20..0x7E (Base 2.1 §1.4.2)
       | ljust(x)    # 첫 바이트가 0x20이 아니거나 전부 0x20 (왼쪽 정렬)
       | popcount(x)
```
- 배열 원소의 index는 `PSD[0]`, 비트 선택은 `SQES[7:4]`다. 둘의 구분은 파서가 하지 않는다. `Ref.path`에 첫 `[...]`를 넣을지는 다음 규칙으로 정한다: `'.'` 뒤에 NAME이 오거나 콜론이 없는 경우 path에 포함하고, 마지막 `[...]`는 bits로 둔다. `rules.py`가 레이아웃을 보고 최종 검증한다(Task 3).

- [ ] **Step 1: 실패하는 테스트를 쓴다.** `DictEnv`는 테스트용으로 dict에서 꺼내고, 없으면 `Unknown`을 던진다.

```python
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
```

- [ ] **Step 2: 실패를 확인한다.** `uv run pytest tests/test_expr.py -v` → FAIL
- [ ] **Step 3: `expr.py`를 구현한다.** 손으로 쓴 토크나이저와 재귀 하강 파서로 만들고 노드는 dataclass로 둔다. `eval`/`compile`은 쓰지 않는다. `and`/`or`는 단락 평가를 하므로, 왼쪽이 결론을 내면 오른쪽의 `Unknown`은 발생하지 않는다.
- [ ] **Step 4: 통과를 확인한다.** → PASS
- [ ] **Step 5: 커밋한다.** `git commit -m "feat: 규칙 식 언어 파서/평가기"`

---

### Task 3: 규칙, 제품 정보, 자동 규칙, 정적 검사

**Files:**
- Create: `src/idharness/rules.py`, `src/idharness/profile.py`, `data/features.yaml`(빈 매핑 `{}`), `data/profiles/default.yaml`, `tests/fixtures/rules/mini/*.yaml`
- Test: `tests/test_rules.py`, `tests/test_profile.py`

**Interfaces:**
- Consumes: Task 1 `Layout`, `FieldDef`, `load_sources`; Task 2 `parse`, `refs`, `Ref`, `ExprError`
- Produces:
  - `Target(struct: str, field: str, index: int | Literal["*"] | None, sub: str | None, bits: tuple[int, int] | None)`
    - `parse_target(s: str) -> Target`. 예: `"id-ctrl.PSD[*].MP"`, `"id-ctrl.SQES[7:4]"`
  - `Rule(id: str, source: str, ref: str, target: Target, when_src: str | None, expect_src: str, when: Node | None, expect: Node, level: str, kind: str, status: str, overrides: tuple[str, ...], note: str, history: tuple[dict, ...], auto: bool, file: str)`
  - `load_rules(root: Path) -> tuple[list[Rule], list[str]]` — `root/**/*.yaml`을 읽는다. 각 파일은 규칙 리스트다. 파싱 오류는 예외 대신 오류 문자열로 모은다(`"<file>: <rule id>: <msg>"`).
  - `generate_auto_rules(layouts: dict[str, Layout]) -> list[Rule]`
    - reserved 필드와 reserved 비트에 대해 `expect: "$ == 0"`, level shall, kind format을 만든다. id는 `AUTO-<struct>-<field>[-<bits>]-RSVD`이고 ref는 해당 필드의 ref다.
    - ascii 필드에 대해 `expect: "ascii($) and ljust($)"`를 만든다. id는 `AUTO-<struct>-<field>-ASCII`이고 ref는 `"Base 2.1 §1.4.2"`다.
    - source와 status는 레이아웃의 값을 따르고, `auto=True`로 둔다.
    - vendor_specific 필드는 제외한다.
  - `check_rules(rules: list[Rule], layouts: dict[str, Layout], sources: dict[str, Source], features: dict) -> list[str]` — 검사 항목:
    - id 중복
    - 등록되지 않은 source (`policy-*`는 rank 30으로 허용)
    - target이나 식 참조가 레이아웃에 없는 경우: 필드, 배열 index 범위, 비트 폭
    - id-ctrl 규칙이 id-ns를 참조하는 경우
    - `$i`를 `[*]`가 아닌 target에서 쓰는 경우
    - 존재하지 않거나 rank가 같거나 높은 규칙을 overrides가 가리키는 경우
    - features.yaml에 없는 `profile.features.X` 참조
    - level, kind, status 값 오류
  - `Profile(name: str, layout_set: str, specs: tuple[str, ...], features: dict[str, bool], values: dict[str, int | str])`
    - `load_profile(name: str, root: Path, features_vocab: dict) -> Profile` — `extends` 체인을 병합하고, 어휘에 없는 feature 키는 `ValueError`로 처리한다.

`data/profiles/default.yaml`:
```yaml
name: default
layout_set: nvme-2.1
specs: [nvme-base-2.1, nvm-cs-1.1, ocp-2.6]
features: {}
values: {}
```

- [ ] **Step 1: 실패하는 테스트를 쓴다.**

```python
def test_parse_target_forms():
    assert parse_target("id-ctrl.PSD[*].MP") == Target("id-ctrl", "PSD", "*", "MP", None)
    assert parse_target("id-ctrl.SQES[7:4]") == Target("id-ctrl", "SQES", None, None, (7, 4))

def test_auto_rules_for_reserved_and_ascii():
    ids = {r.id for r in generate_auto_rules(mini_layouts)}
    assert {"AUTO-id-ctrl-RSVD9-RSVD", "AUTO-id-ctrl-OACS-15_4-RSVD",
            "AUTO-id-ctrl-SN-ASCII", "AUTO-id-ns-LBAF-7_4-RSVD"} <= ids
    assert not any("VS" in i for i in ids)

def test_check_rules_collects_all_errors():
    # 픽스처: 필드 오타(SQESS), 중복 id, ocp→nvme가 아닌 nvme→ocp overrides, 깨진 식
    rules, load_errs = load_rules(FIX / "rules" / "broken")
    errs = load_errs + check_rules(rules, mini_layouts, sources, {})
    assert len(errs) >= 4
    assert any("SQESS" in e for e in errs)
    assert any("duplicate" in e for e in errs)
    assert any("overrides" in e for e in errs)
    assert all(".yaml" in e for e in errs)

def test_idctrl_rule_cannot_reference_idns(): ...
def test_profile_extends_and_unknown_feature():
    p = load_profile("child", FIX / "profiles", {"sanitize": {}})
    assert p.specs == ("nvme-base-2.1", "nvm-cs-1.1", "ocp-2.6") and p.features == {"sanitize": True}
    with pytest.raises(ValueError, match="sanitise"):
        load_profile("typo", FIX / "profiles", {"sanitize": {}})
```

- [ ] **Step 2: 실패를 확인한다.** `uv run pytest tests/test_rules.py tests/test_profile.py -v` → FAIL
- [ ] **Step 3: `rules.py`와 `profile.py`를 구현한다.**
- [ ] **Step 4: 통과를 확인한다.** → PASS
- [ ] **Step 5: 커밋한다.** `git commit -m "feat: 규칙/제품정보 로더, 자동 규칙, 정적 검사"`

---

### Task 4: 판정 엔진과 커버리지

**Files:**
- Create: `src/idharness/engine.py`
- Test: `tests/test_engine.py`

**Interfaces:**
- Consumes: Task 1 `Layout`, `decode`; Task 2 `evaluate`, `Unknown`; Task 3 `Rule`, `Profile`, `generate_auto_rules`; `Source`
- Produces:
  - `Instance(struct: str, nsid: int | None, data: bytes)`
  - `RuleOutcome(rule_id: str, source: str, target_path: str, result: Literal["pass","fail","na","overridden","unknown"], actual: int | bytes | None, reason: str)`
  - `FieldResult(struct: str, nsid: int | None, unit: str, offset: int, value: int | bytes, verdict: str, flags: frozenset[str], outcomes: tuple[RuleOutcome, ...], baseline: str | None)`
    - unit은 최상위 필드이거나 배열 원소다(`"PSD[0]"`). 하위 필드와 비트 대상은 그 unit에 귀속된다.
  - `Coverage(struct: str, total_bits: int, value_bits: int, format_bits: int, uncovered_units: tuple[str, ...])`
  - `RunResult(fields: tuple[FieldResult, ...], db_errors: tuple[str, ...], unknown_keys: dict[str, tuple[str, ...]], coverage: tuple[Coverage, ...], vendor_specific_skipped: int)`
    - `unknown_keys`는 누락된 참조에서 규칙 id들로의 매핑이다.
  - `evaluate_run(instances: list[Instance], layouts: dict[str, Layout], rules: list[Rule], profile: Profile, sources: dict[str, Source]) -> RunResult`
  - `compute_coverage(layouts, rules, profile) -> tuple[Coverage, ...]`

**판정 알고리즘 (확정):**
1. 사용할 규칙을 고른다: `rules + generate_auto_rules(layouts)` 중 source가 `profile.specs`에 있는 것만 쓴다(auto는 레이아웃 source 기준). 정렬은 id 순이다.
2. 인스턴스마다, 규칙마다 target을 펼친다(`[*]`는 0..count-1이고 `$i`를 바인딩한다). id-ns 인스턴스의 env는 `id-ctrl` 인스턴스 값을 참조할 수 있다.
3. `when`이 거짓이면 `na`다. `Unknown`이면 `unknown`이고 reason을 기록한다. `expect`가 참이면 `pass`, 거짓이면 `fail`, `Unknown`이면 `unknown`이다.
4. 덮어쓰기: 같은 인스턴스와 같은 target path에서 `when`이 참인 규칙이 `overrides`로 나열한 규칙은 `overridden`이다(평가 결과는 남기되 판정에서 제외). 해당 unit에는 `OVERRIDDEN` 플래그를 붙인다.
5. unit 판정은 아래 순서로 처음 해당하는 것이다.
   1. shall 규칙 중 fail이 있으면 `FAIL`
   2. should 규칙 중 fail이 있으면 `WARN`
   3. kind=value 규칙 중 pass가 있으면 `PASS`
   4. kind=format 규칙 중 pass가 있으면 `PASS_FORMAT`
   5. 그 외에는 `NO_RULE`
6. 플래그는 다음과 같다.
   - 사용한(pass/fail) 규칙 중 `status == "uncertain"`이 있으면 `UNCERTAIN`
   - unknown 결과가 있으면 `UNKNOWN`
7. 충돌 검사는 같은 인스턴스와 같은 target path에서, overridden이 아니고 when이 참인 규칙에 대해 한다. 대상 폭이 16비트 이하일 때만 한다. `$`에 0..2^w-1을 모두 대입하고, 다른 참조는 실제 값을 쓴다.
   - 출처별로 묶어 만족하는 값이 없으면 `db_errors`에 `"same-source contradiction: <ids>"`를 넣는다.
   - 출처별로는 만족하지만 전체로는 만족하는 값이 없으면 `CONFLICT` 플래그를 붙인다.
   - 대입 중 `Unknown`이 나오면 그 대상은 건너뛴다.
8. vendor_specific 필드는 unit에서 제외하고 개수만 센다.

**커버리지:** 비트 단위로 센다. 전체 비트는 reserved와 vendor_specific을 뺀 모든 필드 비트(배열 원소별)다. 규칙의 target 비트(전체 필드면 전부)를 kind별로 합집합한다. `when` 조건은 무시한다. `uncovered_units`는 어떤 규칙도 닿지 않은 unit이다.

- [ ] **Step 1: 실패하는 테스트를 쓴다.** 소형 레이아웃과 `encode`로 덤프를 만들고, 규칙은 테스트 안에서 YAML 문자열로 만든다.

```python
def test_value_rule_pass_and_fail():
    r = run({"SQES": 0x66}, rules=["id: N1\ntarget: id-ctrl.SQES[7:4]\nexpect: $ == 6\nkind: value ..."])
    assert unit(r, "SQES").verdict == "PASS"
    r = run({"SQES": 0x44}, rules=[same])
    assert unit(r, "SQES").verdict == "FAIL"

def test_format_only_is_pass_format():
    assert unit(run({}, rules=[]), "RSVD9").verdict == "PASS_FORMAT"   # auto reserved 규칙만
    assert unit(run({}, rules=[]), "VID").verdict == "NO_RULE"

def test_when_relation_b_gates_a():
    # "OACS[3]==1일 때만 VID != 0" 형태: when 거짓이면 na
    ...

def test_should_is_warn(): ...

def test_explicit_override_drops_lower():
    # nvme(rank10) "$ == 4", ocp(rank20) "$ == 6" overrides [nvme] → 값 6이면 PASS + OVERRIDDEN
    u = unit(run({"SQES": 0x66}, rules=[nvme_rule, ocp_rule_overriding]), "SQES")
    assert u.verdict == "PASS" and "OVERRIDDEN" in u.flags

def test_cross_source_contradiction_flags_conflict():
    # nvme "$ == 4", ocp "$ == 6" (overrides 없음) → FAIL + CONFLICT
    u = unit(run({"SQES": 0x66}, rules=[nvme_rule, ocp_rule]), "SQES")
    assert u.verdict == "FAIL" and "CONFLICT" in u.flags

def test_same_source_contradiction_is_db_error(): ...

def test_cumulative_rules_not_conflict():
    # nvme "$ <= 7", ocp "$ == 6" → 값 5이면 FAIL, CONFLICT 아님
    ...

def test_missing_profile_key_is_unknown_not_pass():
    r = run({"OACS": 0}, rules=["... when: profile.features.nsm\nexpect: $ == 1 ..."], features_vocab={"nsm": {}})
    u = unit(r, "OACS")
    assert u.verdict != "PASS" and "UNKNOWN" in u.flags
    assert r.unknown_keys["profile.features.nsm"] == ("R-NSM",)

def test_array_star_binds_index():
    # id-ns LBAF[*]: when $i > id-ns.NLBAF → expect $ == 0 ; NLBAF=1, LBAF[2]=9 → LBAF[2] FAIL, LBAF[1] 대상 아님
    ...

def test_idns_references_idctrl(): ...
def test_uncertain_flag(): ...
def test_rules_outside_profile_specs_ignored(): ...
def test_vendor_specific_excluded(): assert "VS" not in units(r) and r.vendor_specific_skipped == 1

def test_coverage_counts_bits():
    c = cov(rules=["target: id-ctrl.SQES[7:4] kind: value"])["id-ctrl"]
    # total = VID16 + SN32 + OACS 4(정의된 비트) + SQES8 + PSD 2*8 = 76
    assert c.total_bits == 76 and c.value_bits == 4

def test_deterministic_order():
    assert run(x) == run(x) and [f.offset for f in r.fields] == sorted(...)
```

- [ ] **Step 2: 실패를 확인한다.** `uv run pytest tests/test_engine.py -v` → FAIL
- [ ] **Step 3: `engine.py`를 위 알고리즘대로 구현한다.**
- [ ] **Step 4: 통과를 확인한다.** → PASS
- [ ] **Step 5: 커밋한다.** `git commit -m "feat: 판정 엔진(누적/명시 덮어쓰기/충돌/UNKNOWN)과 비트 커버리지"`

---

### Task 5: 기존 텍스트 로그 파서와 CHANGED

**Files:**
- Create: `src/idharness/baseline.py`, `data/baseline_aliases.yaml`, `tests/fixtures/baseline/id-ctrl.txt`, `tests/fixtures/baseline/id-ns-1.txt`
- Modify: `src/idharness/engine.py` — `evaluate_run`에 `baseline: Baseline | None = None` 인자를 추가하고, `FieldResult.baseline`과 `CHANGED`를 채운다.
- Test: `tests/test_baseline.py`

**Interfaces:**
- Consumes: Task 4 `evaluate_run`, `FieldResult`
- Produces:
  - `parse_nvme_cli_text(text: str) -> dict[str, str]` — 키는 소문자 nvme-cli 키다.
    - `"key : value"` 줄을 읽는다.
    - `"ps    0 : mp:25.00W ..."`는 `"ps 0"`, `"lbaf  2 : ms:0 lbads:9 rp:0"`은 `"lbaf 2"`로 정규화한다. 값 문자열은 원문 그대로 둔다.
  - `Baseline(files: dict[tuple[str, int | None], dict[str, str]], unmapped: tuple[str, ...])`
    - `load_baseline(dir: Path, aliases: dict[str, str]) -> Baseline` — `id-ctrl.txt`와 `id-ns-<nsid>.txt`를 읽는다.
  - `baseline_value(b: Baseline, struct: str, nsid: int | None, unit: str, value: int | bytes) -> tuple[str | None, bool | None]`
    - 반환값은 (원문, 변경 여부)다. 매핑이 없으면 `(None, None)`이다.
  - 비교 규칙:
    - 정수는 `0x` 16진 또는 10진으로 파싱해 비교한다.
    - ascii는 양끝 공백을 잘라 비교한다.
    - `lbaf N`은 `lbads`, `ms`, `rp` 정수를 레이아웃 원소 값의 해당 비트와 비교한다. 비트 위치는 레이아웃 비트 이름 `LBADS/MS/RP`로 찾는다.
    - `ps N`은 1차에서 비교하지 않는다. 결과는 None이다.
  - 키 매핑은 `aliases.get(key, key.upper())`로 하고, 레이아웃에 없는 키는 `unmapped`에 넣는다.

합성 로그 형식(픽스처)은 nvme-cli 기본 출력을 흉내 낸다.
```
NVME Identify Controller:
vid       : 0x1e0f
ssvid     : 0x1e0f
sn        : AB12
oacs      : 0x8
sqes      : 0x66
frmw      : 0x16
  [4:4] : 0x1	Firmware Activate Without Reset Supported
ps      0 : mp:25.00W operational enlat:0 exlat:0 rrt:0 rrl:0
```

- [ ] **Step 1: 실패하는 테스트를 쓴다.**

```python
def test_parse_basic_and_indexed():
    d = parse_nvme_cli_text(FIX_TXT)
    assert d["vid"] == "0x1e0f" and d["ps 0"].startswith("mp:25.00W")

def test_parse_ignores_verbose_and_unknown_lines():
    d = parse_nvme_cli_text("NVME Identify Controller:\n\nvid : 0x1\n  [4:4] : 0x1\tFoo\nzzz : 3\n")
    assert d == {"vid": "0x1", "zzz": "3"}
    b = load_baseline_from_texts({"id-ctrl": "vid : 0x1\nzzz : 3\n"}, mini_layouts)
    assert "zzz" in b.unmapped[0]

def test_changed_flag():
    r = evaluate_run(insts({"VID": 0x1E0F, "SQES": 0x44}), ..., baseline=b_from_fixture)
    assert "CHANGED" in unit(r, "SQES").flags and "CHANGED" not in unit(r, "VID").flags
    assert unit(r, "SQES").baseline == "0x66"

def test_ascii_trim_compare(): ...
def test_lbaf_compare_uses_bits(): ...
```

- [ ] **Step 2: 실패를 확인한다.** `uv run pytest tests/test_baseline.py -v` → FAIL
- [ ] **Step 3: 구현한다.**
- [ ] **Step 4: 통과를 확인한다.** `uv run pytest -v` (전체) → PASS
- [ ] **Step 5: 커밋한다.** `git commit -m "feat: nvme-cli 텍스트 기존 로그 파서와 CHANGED (합성 샘플 기준)"`

---

### Task 6: run 로딩, 리포트, CLI(validate / check-rules / coverage)

**Files:**
- Create: `src/idharness/runs.py`, `src/idharness/report.py`, `src/idharness/cli.py`
- Test: `tests/test_runs.py`, `tests/test_report.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: Task 1–5 전부
- Produces:
  - run 폴더 규약(Task 7이 생성한다):
    - `meta.json` = `{"host", "device", "nvme_version", "collected_at", "nsids": [..]}`
    - 바이너리: `id-ctrl.bin`, `id-ns-<nsid>.bin`
    - 텍스트: `id-ctrl.txt`, `id-ns-<nsid>.txt`
  - `RunLoadError(Exception)`; `load_run(run_dir: Path, layouts: dict[str, Layout]) -> tuple[dict, list[Instance]]`
    - meta.json이 없거나 `.bin` 크기가 레이아웃 크기와 다르면 `RunLoadError`를 던진다. 메시지에 파일명과 실제/기대 크기를 넣는다.
    - 레이아웃이 없는 구조의 `.bin`(예: id-ns 레이아웃 추가 전)은 건너뛴다. 건너뛴 파일명은 `meta["skipped"]`에 넣어 리포트 헤더에 표시한다.
  - `render_markdown(result: RunResult, meta: dict, profile: Profile, rules_by_id: dict[str, Rule], db_commit: str | None) -> str`
  - `render_summary(result: RunResult) -> str` — 등급별 건수를 보여주고, FAIL/WARN은 최대 30줄까지만 보여준 뒤 `"외 N건"`으로 줄인다.
  - `main(argv: list[str] | None = None) -> int`
    - `idharness validate RUN_DIR [--profile default] [--baseline DIR] [--data data]` → `RUN_DIR/report.md`를 쓰고 요약을 출력한다. 종료 코드는 0이다. DB 오류가 있으면 2다.
    - `idharness check-rules [--data data]` → 레이아웃 정합성, 규칙 로드, 정적 검사 오류를 모두 출력한다. 오류가 없으면 0, 있으면 1이다.
    - `idharness coverage [--profile default] [--struct id-ctrl] [--range 0:255]` → 구조별 비트 커버리지를 보여준다. `--range`가 있으면 그 바이트 범위의 unit별로 규칙 수와 uncovered를 보여준다(추출 작업 수용 기준에 쓴다).
    - `--data`는 레이아웃, 규칙, 프로필, sources, features, aliases의 루트다. 테스트에서는 픽스처 루트를 넘긴다.

**리포트 섹션 순서 (확정, 한국어):**
1. 헤더: host, device, 수집 시각, nvme-cli 버전, 프로필, 스펙 조합, 규칙 DB commit
2. 요약 표: 구조/NSID별 등급 건수
3. FAIL: 구조 | 필드 | 실제값 | 기대(규칙 expect) | 규칙 id | 출처·근거(ref) | 플래그
4. WARN: 같은 열
5. 검토 필요
   - 규칙 충돌(CONFLICT)
   - uncertain 규칙으로 판정된 항목
   - 판정 불가: 프로필에 추가가 필요한 키별 규칙 목록
   - 규칙 DB 오류
6. CHANGED: 필드 | 기존 | 현재 | 판정
7. 덮어쓰기 적용(OVERRIDDEN): 상위 규칙 → 제외된 하위 규칙
8. 전체 필드 결과: 오프셋 순
9. 커버리지와 vendor specific 제외 건수
10. 고지: CHANGED 비교는 합성 샘플로만 검증됨

값 표기: uint는 `0x..`(10진 병기), ascii는 따옴표로 감싼 문자열, bytes는 16바이트까지 hex로 쓰고 그 이상은 `…(N bytes)`로 줄인다.

- [ ] **Step 1: 실패하는 테스트를 쓴다.**

```python
def test_load_run_rejects_wrong_size(tmp_path):
    make_run(tmp_path, {"id-ctrl.bin": b"\x00" * 15})
    with pytest.raises(RunLoadError, match=r"id-ctrl\.bin.*15.*16"):
        load_run(tmp_path, mini_layouts)

def test_load_run_skips_struct_without_layout(tmp_path):
    make_run(tmp_path, {"id-ctrl.bin": b"\x00" * 16, "id-zz.bin": b"\x00" * 4})
    meta, insts = load_run(tmp_path, mini_layouts)
    assert [i.struct for i in insts] == ["id-ctrl"] and meta["skipped"] == ["id-zz.bin"]

def test_report_sections_and_evidence():
    md = render_markdown(result_with_one_fail, meta, profile, rules_by_id, "abc123")
    for h in ["## 요약", "## FAIL", "## WARN", "## 검토 필요", "## CHANGED", "## 커버리지"]:
        assert h in md
    assert "OCP-NVMe-CFG-14" in md and "NVMe-CFG-14" in md and "abc123" in md

def test_report_is_deterministic(): assert render_markdown(*a) == render_markdown(*a)

def test_cli_validate_writes_report(tmp_path, capsys):
    rc = main(["validate", str(run_dir), "--data", str(FIX_DATA)])
    assert rc == 0 and (run_dir / "report.md").exists() and "FAIL" in capsys.readouterr().out

def test_validate_refuses_broken_db(tmp_path):
    assert main(["validate", str(run_dir), "--data", str(BROKEN_DATA)]) == 2

def test_check_rules_exit_codes():
    assert main(["check-rules", "--data", str(FIX_DATA)]) == 0
    assert main(["check-rules", "--data", str(BROKEN_DATA)]) == 1

def test_coverage_range_lists_uncovered(capsys): ...
```

- [ ] **Step 2: 실패를 확인한다.** `uv run pytest tests/test_runs.py tests/test_report.py tests/test_cli.py -v` → FAIL
- [ ] **Step 3: 구현한다.** db_commit은 `git rev-parse --short HEAD`로 얻고, 실패하면 None으로 둔다.
- [ ] **Step 4: 통과를 확인한다.** `uv run pytest -v` → PASS
- [ ] **Step 5: 커밋한다.** `git commit -m "feat: run 로더, 마크다운 리포트, CLI validate/check-rules/coverage"`

---

### Task 7: ssh 수집과 CLI collect

**Files:**
- Create: `src/idharness/collect.py`
- Modify: `src/idharness/cli.py` — `collect` 서브커맨드를 추가한다.
- Test: `tests/test_collect.py`

**Interfaces:**
- Consumes: Task 6 run 폴더 규약
- Produces:
  - `CommandError(Exception)` (cmd, returncode, stderr)
  - `Runner = Callable[[str], bytes]` — 원격 셸 명령 문자열을 받아 stdout 바이트를 돌려준다. 실패하면 `CommandError`를 던진다.
  - `ssh_runner(host: str) -> Runner` — `subprocess.run(["ssh", "-o", "BatchMode=yes", host, cmd], capture_output=True)`
  - `collect(runner: Runner, host: str, device: str, out_root: Path, now: datetime) -> Path`
    1. device를 `^/dev/nvme\d+$`로 검증한다. 맞지 않으면 ValueError다.
    2. `nvme version`
    3. `sudo nvme list-ns <dev>` → `[   0]:0x1` 형식의 각 줄에서 16진 NSID를 파싱한다. 결과가 비면 CommandError다.
    4. `sudo nvme id-ctrl <dev> -b`와 `sudo nvme id-ctrl <dev>`
    5. NSID마다 `sudo nvme id-ns <dev> -n <nsid> -b`와 텍스트 출력
    6. 결과는 `out_root/<YYYYmmdd-HHMMSS>_<host>_<nvmeN>/`에 쓰고, **마지막에** `meta.json`을 쓴다.
    7. 중간에 실패하면 이미 만든 폴더를 지우고 다시 예외를 던진다.
  - CLI `idharness collect --host H --device /dev/nvme0 [--out runs]` → run 폴더 경로를 출력한다.

- [ ] **Step 1: 실패하는 테스트를 쓴다.** `FakeRunner`는 명령 문자열에서 응답으로 가는 dict이고 호출 순서를 기록한다.

```python
def test_collect_writes_run(tmp_path):
    run = collect(fake_ok, "tp1", "/dev/nvme0", tmp_path, datetime(2026, 10, 20, 15, 0, 0))
    assert run.name == "20261020-150000_tp1_nvme0"
    meta = json.loads((run / "meta.json").read_text("utf-8"))
    assert meta["nsids"] == [1, 2] and (run / "id-ns-2.bin").exists()
    assert "sudo nvme id-ns /dev/nvme0 -n 2 -b" in fake_ok.calls

def test_device_injection_rejected():
    with pytest.raises(ValueError):
        collect(fake_ok, "tp1", "/dev/nvme0; rm -rf /", tmp_path, now)
    with pytest.raises(ValueError):
        collect(fake_ok, "tp1", "/dev/nvme0n1", tmp_path, now)

def test_collect_failure_leaves_no_meta(tmp_path):
    with pytest.raises(CommandError):
        collect(fake_fails_on_idns, "tp1", "/dev/nvme0", tmp_path, now)
    assert list(tmp_path.iterdir()) == []

def test_empty_list_ns_is_error(): ...
```

- [ ] **Step 2: 실패를 확인한다.** `uv run pytest tests/test_collect.py -v` → FAIL
- [ ] **Step 3: 구현한다.**
- [ ] **Step 4: 통과를 확인한다.** `uv run pytest -v` → PASS
- [ ] **Step 5: 커밋한다.** `git commit -m "feat: ssh 기반 덤프 수집"`

---

### Task 8: 에이전트, skill, 스펙 추가 절차 문서

**Files:**
- Create: `.claude/agents/nvme-spec-expert.md`, `.claude/agents/ocp-spec-expert.md`, `.claude/agents/rule-verifier.md`, `.claude/skills/id-validate/SKILL.md`, `.claude/skills/id-rule-extract/SKILL.md`, `.claude/skills/id-rule-fix/SKILL.md`, `docs/adding-a-spec.md`
- Test: `tests/test_agents_skills.py`

**Interfaces:**
- Consumes: Task 6–7 CLI 명령, 규칙/레이아웃 YAML 스키마(Task 1, 3)
- Produces: 아래 이름의 에이전트와 skill. Task 9–14가 사용한다.

**각 파일이 반드시 담을 내용:**
- **`nvme-spec-expert`**
  - 담당: `nvme-base-2.1`, `nvm-cs-1.1`. tools: Read, Grep, Glob, Write, Edit, Bash
  - 위치는 md에서 찾고, 판단은 PDF 해당 페이지(Read `pages`)로 확인한다. md의 페이지 경계 표에서 `Col6/Col7` 같은 가짜 열과 중복 설명이 나오는 문제를 명시한다.
  - 규칙/레이아웃 스키마를 따르고 `ref`에 Figure 번호, 섹션, 페이지를 넣는다.
  - shall은 level shall, should는 should로 쓴다.
  - "기능 지원 → 비트" 규칙은 `when: profile.features.<x>`로 쓰고, 새 feature는 `data/features.yaml`에 설명과 관련 비트를 함께 추가한다.
  - 확신이 없으면 `status: uncertain`과 `note`를 남긴다.
  - 작업 후 `uv run idharness check-rules`가 0이어야 한다.
- **`ocp-spec-expert`**
  - 담당: `ocp-2.6`. 요구사항 ID 하나를 규칙 하나 이상으로 만든다. `id`는 `OCP-<요구사항ID>[-n]`이다.
  - NVMe 규칙과 실제로 반대되는 요구일 때만 `overrides`를 쓴다.
  - OCP 2.6이 NVMe 2.0e를 전제한다는 점과 차이가 의심되는 경우 `note`를 남긴다.
- **`rule-verifier`**: tools: Read, Grep, Glob, Edit, Bash
  - 지정된 레이아웃/규칙 파일을 **원본 PDF 페이지와 독립적으로** 대조한다(md만 보고 판단하지 않음).
  - 각 규칙의 `status`를 `cross-checked` 또는 `uncertain`으로 바꾸고, uncertain이면 `note`에 이유를 쓴다.
  - 스스로 규칙 내용을 고치지 않고, 수정 제안 목록을 반환한다.
- **`id-rule-extract`**: 인자는 `<source> <struct> <byte-range> <group-name>`
  1. 해당 expert에 위임해 `data/rules/<source>/<struct>/<group>.yaml`(필요하면 레이아웃)을 쓴다.
  2. `rule-verifier`에 위임한다.
  3. 수정 제안을 expert에 되돌려 반영한다(최대 1회 왕복, 남는 건 uncertain).
  4. `check-rules`가 0이어야 한다.
  5. `coverage --struct <struct> --range <range>`를 출력한다.
  6. 그룹 회귀 테스트 `tests/rules/test_<group>.py`를 작성한다. 그룹의 대표 규칙 3개 이상에 대해, 위반 덤프는 FAIL에 해당 규칙 id, 준수 덤프는 PASS를 확인한다.
  7. 커밋한다.
- **`id-validate`**: 인자는 host, device, profile, (선택) baseline 디렉터리
  1. `collect`를 실행한다.
  2. `validate`를 실행한다.
  3. 요약을 FAIL/WARN/검토 필요 순으로 한국어로 설명한다. 판정을 바꾸지 않고 근거만 해석한다.
  4. 리포트 경로를 알려주고, 틀린 판정이 있으면 `id-rule-fix`로 이어간다고 안내한다.
- **`id-rule-fix`**: 입력은 run 폴더, 규칙 id 또는 필드, 사용자 이유
  1. 출처에 맞는 expert에 위임해 PDF로 재확인한다.
  2. 규칙을 고치고 `status: corrected`로 바꾼다. `history`에 `{date, previous: {when, expect, level}, reason}`을 추가한다.
  3. `check-rules`를 실행한다.
  4. 같은 run으로 `validate`를 다시 돌려 전후 판정 차이를 보여준다.
  5. 커밋한다.
- **`docs/adding-a-spec.md`**: 새 스펙을 추가하는 절차다.
  1. `spec/`에 PDF와 md를 넣는다.
  2. `data/sources.yaml`에 id와 rank를 등록한다.
  3. `<spec>-expert.md`를 기존 파일을 복제해 담당 출처만 바꿔 만든다.
  4. 프로필 `specs`에 추가한다.
  5. `id-rule-extract`를 실행한다.

  policy 출처는 `policy-<개정판>`과 rank 30으로 예약됨을 적는다(설계 §9).

- [ ] **Step 1: 실패하는 테스트를 쓴다.**

```python
AGENTS = ["nvme-spec-expert", "ocp-spec-expert", "rule-verifier"]
SKILLS = ["id-validate", "id-rule-extract", "id-rule-fix"]

def test_agent_frontmatter():
    for a in AGENTS:
        fm = frontmatter(Path(f".claude/agents/{a}.md"))
        assert fm["name"] == a and fm["description"] and fm["tools"]

def test_skill_frontmatter_and_cli_refs():
    for s in SKILLS:
        text = Path(f".claude/skills/{s}/SKILL.md").read_text("utf-8")
        fm = frontmatter_text(text)
        assert fm["name"] == s and fm["description"]
        assert "uv run idharness" in text

def test_skills_only_reference_existing_subcommands():
    for s in SKILLS:
        for sub in re.findall(r"uv run idharness (\S+)", read(s)):
            assert sub in {"collect", "validate", "check-rules", "coverage"}
```

- [ ] **Step 2: 실패를 확인한다.** `uv run pytest tests/test_agents_skills.py -v` → FAIL
- [ ] **Step 3: 위 내용으로 파일들을 작성한다.**
- [ ] **Step 4: 통과를 확인한다.** → PASS
- [ ] **Step 5: 커밋한다.** `git commit -m "feat: 스펙 전문/교차검증 에이전트와 검증·추출·수정 skill"`

---

> **Task 9–14 실행 주의:** 이 작업들은 `id-rule-extract` skill로 서브에이전트(`nvme-spec-expert`, `ocp-spec-expert`, `rule-verifier`)를 부른다. 그래서 **메인 세션에서 실행**해야 한다. 서브에이전트 구현자는 다른 에이전트를 부를 수 없다.
>
> 각 작업의 수용 기준은 공통으로 다음과 같다.
> - (a) `uv run idharness check-rules` 종료 코드가 0이다.
> - (b) `uv run idharness coverage --struct <s> --range <r>` 출력에서 해당 범위의 모든 unit에 규칙이 1개 이상 있다(auto 포함). 남는 uncovered unit은 그룹 YAML 상단 주석에 이유를 적는다.
> - (c) `tests/rules/test_<group>.py`가 통과한다.
> - (d) `uv run pytest -v` 전체가 통과한다.
>
> 커버리지 숫자(value_bits / total_bits)는 커밋 메시지에 남긴다.

### Task 9: id-ctrl 레이아웃 전체 + 시범 그룹 G1 (bytes 0–255, 흐름 관통)

**Files:**
- Create: `data/layouts/nvme-2.1/id-ctrl.yaml`, `data/rules/nvme-base-2.1/id-ctrl/g1-caps-features.yaml`, `tests/rules/test_g1_caps_features.py`, `tests/test_data_integrity.py`

**Interfaces:**
- Consumes: Task 8 skill과 에이전트, Task 6 CLI
- Produces: 실제 id-ctrl 레이아웃 (size 4096). 이후 id-ctrl 그룹 작업과 Task 13의 id-ns 교차 참조가 사용한다.

- [ ] **Step 1: `tests/test_data_integrity.py`를 쓴다.**
  - `data/` 실제 데이터에 대해 `check_layout`이 오류 없음을 확인한다.
  - `check_rules`가 오류 없음을 확인한다.
  - id-ctrl size가 4096인지 확인한다.
  - 이 시점에는 레이아웃이 없으므로 FAIL을 확인한다.
- [ ] **Step 2: `nvme-spec-expert`로 id-ctrl 레이아웃 전체를 추출한다.**
  - 범위: Base 2.1 Figure 312 (md 14580–15260행 부근, PDF p.321~)
  - 그룹 구성: Controller Capabilities and Features 0–255, Admin Command Set Attributes & Optional Controller Capabilities 256–511, NVM Command Set Attributes 512–1791, Fabric Specific 1792–2047, Power State Descriptors 2048–3071(PSD struct ×32, 원소 32바이트, 원소 필드는 Base의 Power State Descriptor figure), Vendor Specific 3072–4095(`vendor_specific: true`)
  - NVM CS 1.1 Figure 117에서 정의하는 필드는 `source: nvm-cs-1.1`로 둔다.
- [ ] **Step 3: `rule-verifier`로 레이아웃을 교차 검증한다.** test_data_integrity가 PASS하는지 확인한다.
- [ ] **Step 4: `id-rule-extract nvme-base-2.1 id-ctrl 0:255 g1-caps-features`를 실행한다.**
- [ ] **Step 5: 흐름 관통을 확인한다.**
  - `encode`로 G1 규칙을 준수하는 합성 id-ctrl을 만든다.
  - `tests/fixtures/runs/synthetic-ok/`에 run 폴더 규약대로 둔다. 이 run에는 id-ctrl만 둔다. id-ns는 Task 13에서 추가한다.
  - `uv run idharness validate tests/fixtures/runs/synthetic-ok`의 출력에서 G1 범위 FAIL이 0인지 확인한다.
- [ ] **Step 6: 수용 기준 (a)–(d)를 확인한 뒤 커밋한다.** `git commit -m "data: id-ctrl 레이아웃 + G1 규칙 (coverage x/y)"`

### Task 10: id-ctrl G2 — Admin Command Set Attributes & Optional Controller Capabilities (256–511)
- **Files:** `data/rules/nvme-base-2.1/id-ctrl/g2-admin-attrs.yaml`, `tests/rules/test_g2_admin_attrs.py` (필요하면 `data/features.yaml`)
- [ ] **Step 1:** `id-rule-extract nvme-base-2.1 id-ctrl 256:511 g2-admin-attrs`를 실행한다. OACS, FRMW, LPA, SANICAP 등 capability 비트는 `profile.features` 조건 규칙을 포함한다.
- [ ] **Step 2:** 수용 기준 (a)–(d)를 확인하고 커밋한다.

### Task 11: id-ctrl G3+G4 — NVM Command Set Attributes, Fabric Specific (512–2047)
- **Files:** `data/rules/nvme-base-2.1/id-ctrl/g3-nvm-attrs.yaml`, `data/rules/nvm-cs-1.1/id-ctrl/g3-nvm-cs.yaml`, `data/rules/nvme-base-2.1/id-ctrl/g4-fabric.yaml`, `tests/rules/test_g3_g4.py`
- [ ] **Step 1:** `id-rule-extract`를 `512:1791 g3-nvm-attrs`로 실행한다(Base와 NVM CS 각각).
- [ ] **Step 2:** `1792:2047 g4-fabric`를 실행한다. PCIe 컨트롤러 기준 규칙(Discovery/Fabrics 전용 필드의 값)은 `profile.values` 또는 note로 처리한다.
- [ ] **Step 3:** 수용 기준을 확인하고 커밋한다.

### Task 12: id-ctrl G5 — Power State Descriptors (2048–3071)
- **Files:** `data/rules/nvme-base-2.1/id-ctrl/g5-psd.yaml`, `tests/rules/test_g5_psd.py`
- [ ] **Step 1:** `id-rule-extract nvme-base-2.1 id-ctrl 2048:3071 g5-psd`를 실행한다.
  - `PSD[*]` target과 `$i`를 쓴다.
  - 예: `when: $i > id-ctrl.NPSS` → 원소 전체가 0. 이 규칙의 정확성은 스펙으로 확인한다.
- [ ] **Step 2:** 수용 기준을 확인하고 커밋한다.

### Task 13: id-ns 레이아웃 + 규칙 (NVM CS 1.1 Figure 114)
- **Files:** `data/layouts/nvme-2.1/id-ns.yaml`, `data/rules/nvm-cs-1.1/id-ns/n1-basic.yaml`(0–127), `data/rules/nvm-cs-1.1/id-ns/n2-lbaf.yaml`(128–383, `LBAF[*]` ×64, 원소 4바이트), `data/rules/nvm-cs-1.1/id-ns/n3-rest.yaml`(384–4095, VS는 vendor_specific), `tests/rules/test_idns.py`
- [ ] **Step 1:** `nvme-spec-expert`로 id-ns 레이아웃을 추출한다(md 3774행 부근, Figure 114). 그다음 `rule-verifier`로 교차 검증한다. 이때 Task 9의 `test_data_integrity`에 id-ns size 4096 검사를 추가한다.
- [ ] **Step 2:** `id-rule-extract`를 n1, n2, n3에 대해 실행한다. id-ctrl 교차 참조 규칙을 포함한다(예: ONCS, NSFEAT/THINP, NN, MNAN 관련). `tests/rules/test_idns.py`에 id-ctrl을 참조하는 규칙 1개 이상의 위반과 준수 케이스를 넣는다.
- [ ] **Step 3:** `synthetic-ok` run에 준수 id-ns를 넣고 `validate`로 FAIL 0을 확인한다.
- [ ] **Step 4:** 수용 기준을 확인하고 커밋한다.

### Task 14: OCP 2.6 규칙
- **Files:** `data/rules/ocp-2.6/<section>.yaml` (요구사항 섹션별, 예: `nvme-cfg.yaml`, `nvme-ad.yaml`, `nvme-opt.yaml`, `std-log.yaml` …), `tests/rules/test_ocp.py`
- [ ] **Step 1:** `ocp-spec-expert`로 OCP 2.6 요구사항 표 전체(약 1500행)를 훑는다. id-ctrl과 id-ns 필드 값으로 판정 가능한 요구사항을 추린다. 직접 언급된 18건(`NVMe-CFG-7/8/14/15/19, NVMe-AD-2/6/17/18/23/24, NVMe-OPT-7/9/10/15, STD-LOG-18/22, DP-CFG-11`)이 기본이고, "기능 X를 지원해야 한다"에서 비트로 이어지는 간접 요구사항도 포함한다. 추린 목록과 제외 사유를 `data/rules/ocp-2.6/README.md`에 남긴다.
- [ ] **Step 2:** 섹션별로 `id-rule-extract ocp-2.6 <struct> <range> <section>`을 실행한다. 범위는 해당 요구사항이 닿는 필드를 기준으로 잡는다. NVMe 규칙과 실제로 반대되는 경우에만 `overrides`를 쓴다.
- [ ] **Step 3:** `tests/rules/test_ocp.py`를 쓴다. `NVMe-CFG-14`(SQES[7:4]==6), `NVMe-CFG-15`(CQES[7:4]==4), `NVMe-CFG-19`(HMPRE==0 and HMMIN==0), `NVMe-AD-17`(SANICAP NODMMAS==01b)의 위반과 준수 케이스를 넣는다.
- [ ] **Step 4:** `synthetic-ok`를 OCP 준수로 갱신하고 `validate` FAIL 0을 확인한다. 수용 기준을 확인하고 커밋한다.

### Task 15: 최종 수용 확인과 사용 안내
- **Files:** `README.md`, `tests/test_acceptance.py`
- [ ] **Step 1:** `tests/test_acceptance.py`를 쓴다.
  - 실제 `data/`와 `synthetic-ok` run으로 FAIL 0, CONFLICT 0, db_errors 0을 확인한다.
  - 대표 위반 5종(SQES, CQES, reserved 비트 1, SN 비ASCII, LBAF[NLBAF+1] 비0)을 하나씩 주입한 사본마다, 기대한 규칙 id가 FAIL로 나오는지 확인한다.
  - 같은 입력을 두 번 렌더링해 리포트가 동일한지 확인한다.
- [ ] **Step 2:** `uv run pytest -v` 전체 PASS를 확인한다. `uv run idharness coverage`의 구조별 숫자를 기록한다.
- [ ] **Step 3:** `README.md`를 쓴다(한국어).
  - 설치: `uv sync`
  - 사용: `id-validate` skill / `idharness collect` → `validate`
  - 리포트 읽는 법(등급, 플래그)
  - 규칙 수정(`id-rule-fix`), 스펙 추가(`docs/adding-a-spec.md`)
  - 한계: CHANGED는 합성 샘플만, 정책 미구현
- [ ] **Step 4:** 실제 장비로 확인한다(사용자가 host와 device를 줄 때). `id-validate`로 한 번 실행해 결과를 사용자에게 보여준다. 결과가 이상하면 `id-rule-fix` 흐름으로 처리한다.
- [ ] **Step 5:** 커밋한다. `git commit -m "docs: README, 최종 수용 테스트"`
