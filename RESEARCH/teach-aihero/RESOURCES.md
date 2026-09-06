# Resources

학습의 근거가 되는 자료 목록. 신뢰도 순.

## 1차 소스 (설치된 스킬 원문 — 최우선)

- `~/.claude/skills/ask-matt/SKILL.md` — 팩 전체의 라우터이자 공식 지도. 메인 플로우, 온램프, 독립 스킬, phase boundary 5선택지가 전부 여기 정의돼 있다. **가장 신뢰할 소스.**
- `~/.claude/skills/ask-matt/PHASE-BOUNDARIES.md` — 컨텍스트 경계에서의 5가지 선택(Continue, /clear, /handoff, 서브에이전트, /compact) 결정 트리.
- `~/.claude/skills/setup-matt-pocock-skills/SKILL.md` — 저장소별 초기 설정(이슈 트래커, triage 라벨, CONTEXT.md와 ADR 레이아웃) 절차.
- 각 스킬 폴더의 SKILL.md (grill-with-docs, to-spec, to-tickets, implement, code-review, diagnosing-bugs, domain-modeling, research, wayfinder 등)

## 공식 출처 (2026-08-06 확인)

- https://github.com/mattpocock/skills — 팩 원본 저장소(MIT). 21개 스킬 전체.
- https://claude.com/plugins/mattpocock-skills — Claude Code 공식 마켓플레이스 플러그인. 설치 시 전체 스킬과 자동 업데이트 제공.
- https://www.aihero.dev/skills — 공식 소개 페이지.

## 외부 소스

- https://www.aihero.dev/ai-coding-dictionary/smart-zone — 라우터가 인용하는 "smart zone"(모델이 또렷하게 추론하는 약 150k 토큰 윈도우) 정의. aihero.dev의 AI 코딩 사전.
- https://www.aihero.dev — Matt Pocock의 AI Hero 본진. 팩의 철학과 배경 글.

## 이 환경의 맥락 소스

- `~/.claude/CLAUDE.md` — 현재 운영 헌법. superpowers 사이클이 기본으로 지정돼 있어 AI Hero 도입 시 충돌 지점.
- superpowers 플러그인 스킬들(brainstorming, writing-plans, subagent-driven-development, requesting-code-review 등) — 비교 대상.

## 설치 현황 (2026-08-06 실측, 같은 날 3개 보충)

설치됨(22): ask-matt, grill-with-docs, grill-me, grilling, handoff, to-spec, to-tickets,
implement, tdd, prototype, code-review, diagnosing-bugs, wayfinder,
improve-codebase-architecture, domain-modeling, research, to-questionnaire,
resolving-merge-conflicts, wait-what, teach, writing-for-agents, setup-matt-pocock-skills

누락(3): triage(외부 이슈 온램프), wizard(사람 전용 절차 스크립트), codebase-design(모듈 설계 어휘)
보충 이력: grilling, tdd, prototype을 github.com/mattpocock/skills(main, 2026-08-06)에서
수동 복사. 저장소 구조는 skills/engineering/과 skills/productivity/ 카테고리 하위.
이로써 grill 계열과 implement의 내부 의존성이 해소됨. 세션 반영은 /reload-skills 필요.
