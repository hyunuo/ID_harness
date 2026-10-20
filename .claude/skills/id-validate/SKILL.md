---
name: id-validate
description: 테스트 PC의 NVMe Identify 덤프를 수집하고 규칙 DB로 검증한 뒤, FAIL/WARN/검토 필요 항목을 한국어로 해석한다. 인자는 host, device, profile, (선택) baseline 디렉터리.
---

# id-validate

인자: `<host> <device> <profile> [baseline-dir]` (예: `testpc /dev/nvme0 default data/baselines/prodX`)

판정은 결정적 엔진이 한다. 이 skill은 판정을 **해석만 하고 바꾸지 않는다**. 판정이 틀렸다고 보이면 규칙을 고치는 것이 아니라 `id-rule-fix`로 넘긴다. 규칙/식 용어는 `docs/rule-authoring.md`를 참고한다.

## 절차

1. 덤프를 수집한다. device는 `^/dev/nvme\d+$`(컨트롤러 char device)여야 한다.

   ```
   uv run idharness collect --host <host> --device <device>
   ```

   stdout 마지막 줄이 run 폴더 경로다. 실패하면(반환 코드 2 또는 3) 출력된 stderr를 그대로 사용자에게 보여주고 중단한다. 재시도하거나 run 폴더를 직접 만들지 않는다.

2. 검증한다. baseline이 주어졌으면 `--baseline`을 붙인다.

   ```
   uv run idharness validate <run-dir> --profile <profile> [--baseline <baseline-dir>]
   ```

   종료 코드 2는 규칙 DB 오류, 잘못된 크기의 덤프 같은 거부다. 출력된 오류를 보여주고 중단한다. DB 오류면 `uv run idharness check-rules`로 전체 목록을 확인해 사용자에게 알린다.

3. 요약을 **FAIL, WARN, 검토 필요** 순으로 한국어로 설명한다. `<run-dir>/report.md`에서 근거를 읽는다.
   - FAIL(shall 위반)과 WARN(should 위반): 필드, 실제 값, 위반한 규칙 id, `ref`(Figure/섹션/페이지)를 짚는다.
   - 검토 필요: CONFLICT(출처끼리 엇갈림), UNCERTAIN(규칙 status가 uncertain), UNKNOWN(프로필에 키 없음: "프로필에 추가 필요: features.x" 목록을 그대로 전달), CHANGED(baseline 대비 변경, baseline 지정 시).
   - PASS(형식만)은 값이 아직 검증되지 않았다는 뜻임을 필요하면 설명한다.
   - 판정, 등급, 규칙 내용을 바꾸거나 재해석해 다르게 말하지 않는다. 해석은 "왜 이 판정이 나왔나"에 한정한다.

4. 리포트 경로(`<run-dir>/report.md`)를 알려준다. 사용자가 틀린 판정이라고 하면 `id-rule-fix`(입력: run 폴더, 규칙 id 또는 필드, 이유)로 이어간다고 안내한다.
