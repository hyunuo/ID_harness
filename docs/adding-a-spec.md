# 새 스펙 추가 절차

규칙/레이아웃 스키마는 `docs/rule-authoring.md`를 따른다. 이 문서는 출처를 하나 더 추가하는 순서만 다룬다.

1. **파일 배치:** `spec/`에 스펙 PDF와 md 변환본을 같은 이름으로 넣는다. 판단은 PDF로, 위치 탐색은 md로 한다.
2. **출처 등록:** `data/sources.yaml`에 `id`, `title`, `version`, `file`, `rank`를 추가한다. rank가 낮을수록 우선순위가 낮고, 더 높은 rank 규칙만 `overrides`로 낮은 rank 규칙을 덮을 수 있다(예: nvme-base-2.1=10, ocp-2.6=20).
3. **전문 에이전트 생성:** 기존 `.claude/agents/ocp-spec-expert.md`(NVMe 계열이면 `nvme-spec-expert.md`)를 복제해 `<spec>-expert.md`로 만들고 `name`, `description`, 담당 출처 id, 전제 스펙 설명만 바꾼다.
4. **프로필 등록:** `data/profiles/*.yaml`의 `specs`에 새 출처 id를 추가한다. 이 목록에 없는 출처의 규칙은 판정에서 빠진다.
5. **규칙 추출:** `id-rule-extract` skill을 `<source> <struct> <byte-range> <group-name>`으로 필요한 만큼 실행한다.

`uv run idharness check-rules`가 0이고 `coverage`로 범위를 확인한 뒤 커밋한다.

**policy 출처 예약:** 조직 정책은 `policy-<개정판>`(예: `policy-2026a`) 출처와 rank 30으로 예약되어 있다(설계 §9). 1차 구현에는 없으며, `policy-` 접두어 출처 id는 `sources.yaml` 등록 없이도 rank 30으로 해석된다. 정책이 스펙보다 우선하는 판정은 이후 단계에서 구현한다.
