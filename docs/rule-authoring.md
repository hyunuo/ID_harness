# 규칙/레이아웃 작성 가이드

레이아웃과 규칙을 쓰는 사람과 에이전트가 따르는 **유일한 스키마 참조 문서**다. 에이전트와 skill은 이 문서를 가리키기만 하고 스키마를 복제하지 않는다. 예시는 `tests/fixtures/layouts/mini/*.yaml`, `tests/fixtures/rules/mini/*.yaml`에 있다.

## 1. data/ 디렉터리

```
data/sources.yaml                         출처 id, 버전, 파일, rank
data/features.yaml                        profile.features 어휘
data/profiles/<name>.yaml                 제품 정보 (specs, features, values)
data/layouts/<layout_set>/<struct>.yaml   구조 레이아웃 (예: nvme-2.1/id-ctrl.yaml)
data/rules/<source>/<struct>/<group>.yaml 규칙 묶음 (예: nvme-base-2.1/id-ctrl/caps.yaml)
```

규칙 파일의 최상위는 규칙 매핑의 **리스트**다. 파일 상단 주석에 범위(바이트)와 남긴 uncovered unit의 이유를 적는다.

## 2. 레이아웃 YAML

최상위 키: `structure`(`id-ctrl`, `id-ns`), `size`(바이트), `source`(기본 출처 id), `status`, `fields`.

필드 키:

| 키 | 의미 |
|---|---|
| `name`, `offset`, `size` | 이름, 시작 바이트, 바이트 수 (필수) |
| `type` | `uint`(little-endian 정수) `ascii` `bytes` `struct` (필수) |
| `title`, `ref` | 스펙 표기 이름, 근거 (`ref` 형식은 §7) |
| `source` | 필드별 출처. 없으면 최상위 `source` |
| `reserved: true` | reserved 영역. 자동 규칙이 0을 요구한다 |
| `vendor_specific: true` | 판정과 커버리지에서 제외 |
| `bits` | `[{name, range, reserved, title}]`. `range`는 `"3:0"` 또는 `"7"` |
| `count` | 배열 원소 수. `size`는 **전체 크기(원소 크기 x count)** |
| `element` | `type: struct`일 때 원소 내부 필드 목록(offset은 원소 기준) |

규칙:

- 필드는 빈틈과 겹침 없이 `0..size-1`을 채운다. reserved 영역도 `reserved: true` 필드로 쓴다. `check-rules`가 gap/overlap을 오류로 낸다.
- 배열 필드의 `bits`는 원소 한 개의 비트다. 같은 비트 정의가 모든 원소에 적용된다.
- id-ns의 `LBAF` 원소 비트 이름은 반드시 `MS`, `LBADS`, `RP`(나머지는 reserved)로 쓴다. 기준선 비교기가 이 이름에 의존한다.
- **`range`는 항상 따옴표로 감싼다**(`range: "3:0"`). 따옴표 없는 `3:0`은 YAML이 60진 정수(180)로 해석한다.

## 3. 규칙 YAML

필수 키: `id`, `source`, `ref`, `target`, `expect`, `level`, `kind`, `status`. 선택 키: `when`, `overrides`, `note`, `history`.

```yaml
- id: NVME-CTRL-SQES-MINES        # 전체 규칙에서 유일. OCP는 OCP-<요구사항ID>[-n]
  source: nvme-base-2.1           # data/sources.yaml의 id
  ref: "Base 2.1 Figure 275, §5.1.13.2.1, p.312"
  target: id-ctrl.SQES[3:0]
  when: profile.features.sanitize # 생략 또는 always = 무조건
  expect: "$ == 6"
  level: shall
  kind: value
  status: cross-checked
  note: ""
```

- `id`는 중복 불가. 관례는 `<출처약어>-<구조>-<필드>[-<비트>]`.
- `when`, `expect`에 `: ` 또는 `{`, `*`가 들어가면 반드시 따옴표로 감싼다.

### 의미

| 키 | 값 | 의미 |
|---|---|---|
| `level` | `shall` | 위반 시 FAIL |
| | `should` | 위반 시 WARN |
| `kind` | `value` | 값을 실제로 검증. 통과하면 PASS |
| | `format` | 형식만 검증(예: 범위, 정렬). 통과해도 PASS(형식만) |
| `status` | `cross-checked` | 원본 PDF로 독립 교차검증됨 |
| | `uncertain` | 확신 없음. 판정에 UNCERTAIN 플래그가 붙음. `note`에 이유 필수 |
| | `corrected` | 사용자 지적으로 수정됨. `history`에 이전 내용 기록 |

필드 판정은 FAIL > WARN > PASS(value 통과 1개 이상) > PASS(형식만) > 규칙 없음 순이다. 값이 없는 참조(프로필에 없는 feature 등)는 크래시나 PASS가 아니라 UNKNOWN이 된다.

## 4. target 문법

`<struct>.<FIELD>[index 또는 *][.SUB][bits]` 형태다.

- 필드 전체: `id-ctrl.VID`
- 비트: `id-ctrl.SQES[7:4]`, 단일 비트 `id-ctrl.OACS[1]` (배열이 아닌 필드의 `[n]`은 비트 n)
- 배열 원소: `id-ctrl.PSD[3]`, 전체 원소: `id-ctrl.PSD[*]`
- 원소 내부 필드: `id-ctrl.PSD[*].MP`
- 배열 원소의 비트: `id-ns.LBAF[*][7:4]`, `id-ns.LBAF[2][3:0]`
- 비트는 `[hi:lo]`(hi >= lo)이며 필드 폭 안이어야 한다.
- `[*]` target은 모든 원소에 같은 식을 적용한다. 배열 필드에 index 없이 target을 쓰면 오류다.

## 5. 식 문법 (when / expect)

`eval`을 쓰지 않는 자체 파서다. 결과는 bool이어야 한다.

- `$`: target 값(target의 비트로 이미 잘린 값). `$i`: `[*]` target의 원소 index (`[*]` target에서만 사용 가능).
- 구조 참조: `id-ctrl.FIELD`, `id-ctrl.FIELD[7:4]`, `id-ns.LBAF[2][3:0]`, `id-ns.NLBAF`. **id-ctrl 규칙은 id-ns를 참조할 수 없다.**
- 제품 정보: `profile.features.<이름>`(bool), `profile.values.<이름>`(값). 프로필에 없으면 UNKNOWN.
- 연산자: `== != < <= > >= in {a, b, c} and or not + - * << &`. 이름에 하이픈이 있으므로 **이항 빼기는 공백을 둔다**(`a - b`). 괄호 사용 가능.
- 정수는 10진, `0x`, `0b`. 문자열은 `'AB  '` (ascii 필드와 정확 비교).
- 함수: `ascii(x)`(bytes가 전부 출력 가능 ASCII 0x20..0x7E인가), `ljust(x)`(bytes가 왼쪽 정렬인가: 앞에 공백이 없거나 전부 공백), `popcount(x)`(1인 비트 수), `zero(x)`(정수/bytes가 전부 0인가).
- 예: `"$ in {0, 1, 2}"`, `"$ <= 1 << 12"`, `"id-ctrl.OACS[3] == 1"`, `"$i <= id-ns.NLBAF"`.

## 6. 자동 규칙 (손으로 쓰지 않는다)

레이아웃에서 엔진이 자동 생성한다. 에이전트가 같은 규칙을 다시 쓰면 중복이다.

- `reserved: true` 필드와 reserved 비트: `zero($)` (level shall, kind format). id는 `AUTO-...-RSVD`.
- `ascii` 필드: `ascii($) and ljust($)`. id는 `AUTO-...-ASCII`.
- `vendor_specific` 필드는 제외된다.

따라서 규칙 파일에는 의미 있는 값 규칙(범위, 고정값, capability 연동 등)만 쓴다. 커버리지는 `uv run idharness coverage --struct <s> --range <a:b>`로 확인한다.

## 7. ref 작성

`ref`는 **Figure 번호 + 섹션 + PDF 페이지**를 모두 담는다. 예: `"Base 2.1 Figure 275, §5.1.13.2.1, p.312"`. OCP는 요구사항 ID를 쓴다 (`"OCP 2.6 NVMe-1, p.20"`).

- 위치는 md에서 찾되 판단은 반드시 PDF 해당 페이지(Read 도구의 `pages`)로 확인한다.
- md 표가 페이지 경계에서 끊기면 `Col6/Col7` 같은 가짜 열과 중복된 설명 텍스트가 나온다. 이런 곳은 md를 믿지 말고 PDF에서 확인한다.

## 8. capability 비트와 features

capability 비트(예: OACS, ONCS)는 "제품이 기능 X를 지원하면 비트 Y가 1이어야 한다" 규칙이 있어야 의미 있는 PASS가 된다. `when: profile.features.<x>`로 쓴다.

새 feature는 `data/features.yaml`에 먼저 추가한다. 키가 어휘에 없으면 `check-rules`가 오류를 낸다.

```yaml
sanitize:
  description: "Sanitize 명령 지원"
  bits: [id-ctrl.OACS[8], id-ctrl.SANICAP]   # 관련 비트
```

## 9. overrides

- `overrides: [<규칙 id>]`는 **더 높은 rank의 출처가 낮은 rank 규칙과 실제로 모순될 때만** 쓴다. 대상의 rank는 이 규칙의 rank보다 **낮아야** 한다(같거나 높으면 오류).
- 모순이 아닌 추가 요구(더 엄격한 조건 등)는 덮어쓰지 말고 규칙을 누적한다. 명시 없이 출처끼리 결과가 엇갈리면 엔진이 FAIL에 CONFLICT("검토 필요")를 붙인다.
- 덮어쓴 규칙은 판정에서 빠지고 OVERRIDDEN 플래그가 붙는다.
- rank: nvme-base-2.1=10, nvm-cs-1.1=10, ocp-2.6=20, `policy-*`=30(예약, 미구현).

## 10. history

`status: corrected` 규칙은 수정 전 내용을 남긴다. 항목은 시간 순 리스트다.

```yaml
  status: corrected
  history:
    - date: "2026-10-20"
      previous: {when: always, expect: "$ <= 64", level: shall}
      reason: "사용자 지적: Figure 275 p.312 확인 결과 상한은 128"
```

`previous`에는 수정 전 `when`, `expect`, `level`을 넣는다. `date`는 따옴표로 감싼다(YAML 날짜 자동 변환 방지).

## 11. 작성 후 점검

1. `uv run idharness check-rules`가 종료 코드 0이어야 한다. 오류는 파일명과 규칙 id와 함께 전부 나열된다.
2. `uv run idharness coverage --struct <s> --range <a:b>`로 범위의 unit마다 규칙이 있는지 본다.
3. 함정 요약: range 따옴표, LBAF 비트 이름 `MS/LBADS/RP`, `$i`는 `[*]` target에서만, id-ctrl 규칙에서 id-ns 참조 금지, 가짜 열(`Col6/Col7`) 주의, 자동 규칙 중복 금지.
