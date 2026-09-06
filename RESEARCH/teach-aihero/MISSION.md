# Mission: AI Hero 스킬 팩을 SASOO 개발 워크플로에 적용하기

## Why
SASOO 개발은 지금 superpowers 사이클(brainstorming, writing-plans, subagent 실행)로 돌아간다.
새로 설치한 AI Hero(Matt Pocock) 팩이 어디에 더 나은지 판단하고, 맞는 스킬을 실전 투입해서
개발 속도와 산출물 품질을 올리는 것이 목표다. 팩 감상이 아니라 실제 워크플로 개선이 목적이다.

## Success looks like
- 새 작업이 생겼을 때 superpowers와 AI Hero 중 어느 플로우로 갈지 근거를 들어 즉시 고를 수 있다
- AI Hero 독립 스킬 중 최소 2개(예: domain-modeling, diagnosing-bugs)를 SASOO 실작업에 투입해 본다
- ask-matt 없이도 메인 플로우 5단계와 각 스킬의 역할을 기억에서 꺼낼 수 있다
- 부분 설치 상태(누락 6개)를 인지하고 보충 여부를 스스로 결정한다

## Constraints
- 학습 시간은 세션 사이 짬짬이. 레슨 하나는 10분 안에 끝나야 한다
- SASOO 저장소를 학습 실험으로 어지럽히지 않는다 (실전 투입은 별도 승인 후)
- 답변 문체 규칙 준수: Em dash 금지, 중간점 대신 쉼표와 "와/과", 해요체와 습니다체 혼용

## Out of scope
- 스킬 제작법 (writing-for-agents 심화) — 나중에 별도 미션으로
- superpowers를 버리고 전면 전환하는 결정 — 비교 판단력이 생긴 뒤에만 검토
