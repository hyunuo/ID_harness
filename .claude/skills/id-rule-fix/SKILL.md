---
name: id-rule-fix
description: 사용자가 틀렸다고 지적한 판정의 규칙을 PDF로 재확인해 고치고 history를 남긴 뒤, 같은 run을 다시 검증해 전후 판정 차이를 보여준다. 입력은 run 폴더, 규칙 id 또는 필드, 사용자 이유.
---

# id-rule-fix

입력: `<run-dir> <규칙 id 또는 필드> <이유>` (예: `runs/20261020-1 NVME-CTRL-SQES-MINES "상한이 틀림"`)

스키마와 history 형식은 `docs/rule-authoring.md`(§3, §10)를 따른다. 이 skill은 서브에이전트를 부르므로 **메인 세션에서 실행**한다.

## 절차

1. 수정 전 판정을 기록한다. `<run-dir>/report.md`에서 해당 규칙/필드의 판정과 근거를 읽어 둔다(없으면 먼저 `uv run idharness validate <run-dir>`을 실행한다).
2. 재확인: 규칙 파일(`data/rules/<source>/...`)의 `source`로 담당 expert를 정한다. Agent 도구로 `nvme-spec-expert` 서브에이전트에 위임 (해당 서브에이전트 타입이 아직 등록되지 않은 세션이면 general-purpose 에이전트에게 `.claude/agents/nvme-spec-expert.md`를 읽고 그 지시를 따르라고 위임) (OCP 출처면 `ocp-spec-expert`). 사용자 이유와 규칙 id, 기존 `ref`를 주고 **PDF 해당 페이지로 규칙이 맞는지 다시 확인**하게 한다. 사용자 주장도 PDF로 확인한다. PDF가 사용자 주장과 다르면 고치지 말고 그 근거를 사용자에게 보고하고 멈춘다.
3. 수정: 규칙을 고치고 `status: corrected`로 바꾼다. `history`에 항목을 **추가**한다(기존 항목은 지우지 않는다).

   ```yaml
   history:
     - date: "<YYYY-MM-DD>"
       previous: {when: <수정 전 when>, expect: "<수정 전 expect>", level: <수정 전 level>}
       reason: "<사용자 이유와 PDF 근거>"
   ```

   `ref`가 바뀌면 함께 고친다. 자동 규칙(`AUTO-...`)은 파일이 없으므로 레이아웃(reserved, vendor_specific, ascii)을 고친다.
4. 정합성:

   ```
   uv run idharness check-rules
   ```

   종료 코드 0이어야 한다. 아니면 오류를 고친다.
5. 같은 run으로 다시 검증하고 전후를 비교해 보여준다.

   ```
   uv run idharness validate <run-dir>
   ```

   (baseline이나 profile을 처음에 지정했으면 같은 옵션을 쓴다.) 1단계의 판정과 새 판정을 필드별로 나란히 보여준다. 덤프는 그대로이므로 차이는 모두 규칙 수정에서 나온 것이다. 다른 필드의 판정이 바뀌었으면 함께 보고한다.
6. 커밋한다. 규칙/레이아웃 파일만 명시적으로 `git add`한다(`git add -A`, `git add .` 금지, `runs/`는 git에 넣지 않는다). 메시지에 규칙 id와 이유를 적는다.
