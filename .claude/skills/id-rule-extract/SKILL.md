---
name: id-rule-extract
description: 스펙의 한 구조/바이트 범위에서 레이아웃과 규칙을 추출한다. expert 에이전트가 쓰고, rule-verifier가 PDF로 교차검증하고, 커버리지와 회귀 테스트를 만든 뒤 커밋한다. 인자는 <source> <struct> <byte-range> <group-name>.
---

# id-rule-extract

인자: `<source> <struct> <byte-range> <group-name>` (예: `nvme-base-2.1 id-ctrl 0:71 identity`)

- `<source>`: `data/sources.yaml`의 id. 담당 expert는 `nvme-base-2.1`, `nvm-cs-1.1`이면 `nvme-spec-expert`, `ocp-2.6`이면 `ocp-spec-expert`.
- `<byte-range>`: `a:b` (포함 오프셋, `coverage --range` 형식과 같다).
- 스키마, 문법, 함정은 `docs/rule-authoring.md`가 유일한 참조다. 에이전트에게 스키마를 다시 풀어 쓰지 말고 이 문서를 읽으라고 지시한다.

이 skill은 서브에이전트를 부르므로 **메인 세션에서 실행**한다(서브에이전트는 다른 에이전트를 부를 수 없다).

## 절차

1. 작성: Agent 도구로 `nvme-spec-expert` 서브에이전트에 위임 (해당 서브에이전트 타입이 아직 등록되지 않은 세션이면 general-purpose 에이전트에게 `.claude/agents/nvme-spec-expert.md`를 읽고 그 지시를 따르라고 위임) (OCP면 `ocp-spec-expert`). `data/rules/<source>/<struct>/<group>.yaml`을 쓰게 하고, 레이아웃이 없거나 범위를 못 덮으면 `data/layouts/nvme-2.1/<struct>.yaml`도 쓰게 한다. 담당 범위(struct, byte-range, group)를 명시한다.
2. 교차검증: Agent 도구로 `rule-verifier` 서브에이전트에 위임 (해당 서브에이전트 타입이 아직 등록되지 않은 세션이면 general-purpose 에이전트에게 `.claude/agents/rule-verifier.md`를 읽고 그 지시를 따르라고 위임). 방금 쓴 파일 경로를 알려준다. verifier는 PDF로 독립 대조해 `status`를 `cross-checked`/`uncertain`으로 바꾸고 수정 제안 목록을 돌려준다(규칙 내용은 직접 고치지 않는다).
3. 반영: 수정 제안이 있으면 expert에 되돌려 반영시킨다. **왕복은 최대 1회**다. 반영 후에도 남는 불일치는 해당 규칙을 `status: uncertain`과 `note`로 표시해 둔다(재검증하지 않는다).
4. 정합성:

   ```
   uv run idharness check-rules
   ```

   종료 코드가 0이어야 한다. 오류가 있으면 expert에 오류 목록을 주고 고치게 한 뒤 다시 실행한다.
5. 커버리지를 출력해 사용자에게 보여준다.

   ```
   uv run idharness coverage --struct <struct> --range <byte-range>
   ```

   범위의 unit 중 `uncovered`가 남으면 그룹 YAML 상단 주석에 이유를 적는다. 전체 숫자는 `uv run idharness coverage --struct <struct>`의 값 검증 비트/전체 비트이며 커밋 메시지에 남긴다.
6. 회귀 테스트: `tests/rules/test_<group>.py`를 쓴다. 그룹의 **대표 규칙 3개 이상**에 대해
   - 위반하는 덤프(필드 값을 바꾼 bytes)를 검증하면 해당 필드 판정이 FAIL(또는 WARN)이고 그 규칙 id가 근거에 있고,
   - 준수하는 덤프는 PASS인 것을 확인한다.
   `tests/test_engine.py`, `tests/test_cli.py`의 헬퍼와 `idharness.layout.encode`로 덤프를 만든다. 기본 덤프는 reserved와 ascii 자동 규칙을 위반하지 않게(0, 공백 채움) 만든다. 테스트가 통과하는지 `uv run pytest tests/rules/test_<group>.py`로 확인한다.
7. 커밋한다. 명시한 경로만 `git add`한다(`git add -A`, `git add .` 금지). 커밋 메시지에 커버리지 숫자를 넣는다. 예: `feat: id-ctrl identity 규칙 (value_bits 120/512)`.
