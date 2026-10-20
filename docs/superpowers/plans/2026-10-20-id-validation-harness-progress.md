# NVMe Identify 검증 하네스: 진행 현황

- 계획: `docs/superpowers/plans/2026-10-20-id-validation-harness.md`
- 설계: `docs/superpowers/specs/2026-10-20-id-validation-harness-design.md`
- 기준 시점: 2026-10-20, commit `08decb0` 이후
- 실행 방식: Subagent-driven. 작업마다 구현 에이전트가 작업하고, 리뷰를 거쳐 필요하면 수정 라운드를 돈다.
- 테스트: `uv run pytest -q` → **133 passed**

## 완료 (Task 1–8: 엔진·CLI·에이전트)

| Task | 내용 | 커밋 범위 | 리뷰 |
|---|---|---|---|
| 1 | uv 프로젝트, 출처 레지스트리, 레이아웃 디코더 | ddade10..a02c39e | 통과 |
| 2 | 규칙 식 언어 (파서/평가기, 신뢰할 수 없는 입력 방어) | a02c39e..67f8c7d | 수정 1회 후 통과 |
| 3 | 규칙/프로필 로더, 자동 규칙, 정적 검사 | 67f8c7d..49f7301 | 통과 |
| 4 | 판정 엔진 (누적/명시 덮어쓰기/충돌/UNKNOWN), 비트 커버리지 | 49f7301..a9f9837 | 수정 1회 후 통과 |
| 5 | nvme-cli 텍스트 기존 로그 파서, CHANGED | a9f9837..6de60e4 | 통과 (R11 판단) |
| 6 | run 로더, 마크다운 리포트, CLI validate/check-rules/coverage | 6de60e4..f2db50e | 수정 1회 후 통과 |
| 7 | ssh 덤프 수집, CLI collect | f2db50e..d60e2f9 | 수정 1회 후 통과 |
| 8 | 에이전트 3개, skill 3개, `docs/rule-authoring.md`, `docs/adding-a-spec.md` | d60e2f9..08decb0 | 수정 1회 후 통과 |

## 남은 작업 (Task 9–15: 실제 규칙 추출과 마무리)

**Task 9: id-ctrl 레이아웃 전체와 G1 규칙 (bytes 0–255)**
- 진행 중 중단됨. 산출물은 아직 없다.
- 1단계 테스트 `tests/test_data_integrity.py`는 작성됐지만 레이아웃이 없어 실패하는 상태라 커밋하지 않았다. 재개할 때 계획 Task 9 Step 1대로 다시 쓴다.
- 레이아웃 추출(Step 2)부터 다시 시작한다.

**Task 10–15**

| Task | 범위 |
|---|---|
| 10 | id-ctrl G2 (256–511) |
| 11 | id-ctrl G3+G4 (512–2047) |
| 12 | id-ctrl G5 PSD (2048–3071) |
| 13 | id-ns 레이아웃과 규칙 |
| 14 | OCP 2.6 규칙 |
| 15 | 최종 수용 테스트와 README. 실제 장비 실행은 host와 `/dev/nvmeX`를 받은 뒤 한다. |

**마지막 단계:** 브랜치 전체 최종 리뷰를 한다. 남겨 둔 Minor 목록을 함께 넘겨 분류하게 한다.

### 재개 방법

1. 새 세션에서는 `.claude/agents`의 `nvme-spec-expert`, `ocp-spec-expert`, `rule-verifier`와 `.claude/skills`의 `id-rule-extract`, `id-rule-fix`, `id-validate`가 등록된다.
2. Task 9–14는 메인 세션에서 `id-rule-extract` skill로 진행한다. skill이 서브에이전트를 부르기 때문이다.
3. 각 Task가 끝나면 계획의 공통 수용 기준을 확인한다.
   - (a) `check-rules`가 0
   - (b) 범위 커버리지
   - (c) 그룹 회귀 테스트
   - (d) 전체 테스트 통과
4. 각 Task가 끝나면 리뷰를 거친다.

## 진행 중 내린 판단 (Rulings)

각 줄은 무엇을 결정했는지, 그리고 틀렸을 때 비용이 무엇인지 순서로 적었다.

- **R1** CLI 테스트용 데이터 루트는 conftest가 tmp에 조립한다. 미니 레이아웃 파일은 한 곳에만 둔다.
  - 틀렸을 때: 테스트 픽스처만 고치면 된다.
- **R2** 사용자 동의에 따라 main에서 작업한다. 커밋할 때는 명시한 경로만 add한다. 사용자의 `guide/`, `업무설계서.md`를 보호하기 위해서다.
- **R3** Task 9–14는 메인 세션이 추출 흐름을 직접 지휘한다.
- **R4** 계획의 미니 id-ctrl 표가 14바이트로 계산되는 오류가 있었다. PSD를 2바이트 원소 2개(MP + 예약 RSVD1)로 바꿔 16바이트로 맞췄다.
  - 틀렸을 때: 픽스처만 고치면 된다.
- **R5** 자동 reserved 규칙은 `$ == 0` 대신 `zero($)`를 쓴다. bytes 타입 reserved 필드를 비교할 수 있게 하기 위해서다.
- **R6** `rules.py`가 `normalize_ref`와 `expand_target`를 공개하고, 엔진과 정적 검사가 같은 경로 해석을 공유한다.
- **R7** overrides는 인스턴스 단위로 적용한다. 상위 규칙의 `when`이 참이면 해당 인스턴스에서 하위 규칙 결과 전체를 제외한다.
  - 틀렸을 때: 배열 원소 단위로 세밀하게 덮어쓸 수 없다.
- **R8** 런타임 식 오류는 결과를 `unknown`으로 두고, 동시에 db_errors에 기록한다. PASS로는 절대 처리하지 않는다.
- **R9** `$`는 target 비트로 이미 잘린 값이다.
- **R10** 기존 로그 API는 레이아웃을 받는다. aliases 파일 형식은 `{keys, hex_keys:[ieee]}`이다. `RunResult.baseline_unmapped`를 추가했다.
- **R11** 리뷰어의 "non-ascii bytes는 비교 불가로 처리해야 한다"는 지적은 기각했다. R10의 해당 문구는 bytes 타입 필드를 뜻하고, 코드는 그대로 맞다.
  - 틀렸을 때: 쓰레기 바이트가 든 ascii 필드에 CHANGED가 붙을 수 있다. 참고 정보일 뿐 판정에는 영향이 없다.
- **R12** 터미널 요약은 FAIL과 WARN을 합쳐 최대 30줄이고, 넘으면 "외 N건" 한 줄을 붙인다.
- **R13** ssh에 `ConnectTimeout=10`, `stdin=DEVNULL`, 명령 타임아웃 120초를 넣었다. 계획의 고정 argv를 변경한 것이다.
  - 틀렸을 때: 120초를 넘는 정상 명령이 실패한다. identify 명령에서는 예상되지 않는다.
- **R14** `docs/rule-authoring.md`를 스키마와 문법의 유일한 참조 문서로 둔다.
- **R15** 스펙 에이전트는 `model: opus`로 고정한다. 추출 정확도를 우선했다.
  - 틀렸을 때: 토큰 비용이 증가한다.
- **설계 보완** 충돌 판정을 "동시에 만족하는 값이 없을 때"로 정의했다(설계 문서 §5.4). Task 4 리뷰에서 `when`이 `$`에 의존하는 경우도 반영했다.

## 보류한 Minor (최종 리뷰에서 분류)

- **T1**
  - `layout.py`의 `_items` docstring이 실제 동작과 다르다.
  - `encode`가 모르는 키를 무시한다.
  - `decode`에 길이 검사가 없다.
  - `load_layout`이 type과 중복 필드명을 검증하지 않는다.
  - 테스트가 repo 루트 기준 상대경로를 쓴다.
- **T2**
  - 문자열 이스케이프가 백슬래시를 제거한다.
  - 연산자 타입 오류의 col이 피연산자가 아니라 연산자 위치를 가리킨다.
  - `true == 1`이 True로 평가된다.
- **T3**
  - `PSD[3:3]`이 index로 해석된다.
  - 로드에 실패한 규칙 때문에 overrides 오류가 덧붙어 나온다.
  - bytes/ascii 필드의 비트 선택을 정적 검사에서 잡지 못한다.
  - `profile.py`에서 features가 매핑이 아니면 TypeError가 난다.
- **T4**
  - 엔진이 level/kind 검증을 `check_rules`에 의존한다(현재 validate가 이 검사를 통과해야만 실행하도록 막고 있다).
  - 16비트 충돌 열거 성능을 실제 레이아웃에서 측정해야 한다.
  - vendor-specific 규칙의 overrides가 무시된다.
- **T5**
  - hex_keys와 lbaf 범위 밖 처리에 테스트가 없다.
  - 키 조회가 O(keys×units)다.
- **T6**
  - `_cell`이 백슬래시를 이스케이프하지 않는다.
  - db_commit에 dirty 표시가 없다.
  - 오류를 stdout으로 출력한다.
  - CONFLICT 섹션에 값이 표시되지 않는다.
  - `id-ns-01.bin` 같은 파일명 엣지 케이스가 있다.
  - `--range` 오류 메시지가 불친절하다.
  - `engine._units`를 공개 함수로 바꿔야 한다.
- **T7**
  - 폴더명의 host를 정제한다. 폴더명에만 적용된다.
  - 빈 `-b` 출력이 0바이트 `.bin`으로 저장된다. validate의 크기 검사에서 걸러진다.
- **T8**
  - `rule-authoring.md` §3 예시가 `uncertain`인데 note가 비어 있다.
  - skill들에 위임 문구가 중복된다.
