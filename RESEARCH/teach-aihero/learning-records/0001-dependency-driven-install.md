# 스킬 보충은 문서 설명이 아니라 참조 실측으로 판정한다

누락 스킬 6개 중 무엇을 채울지, 라우터 문서의 소개 문구가 아니라 "설치된 스킬이 그 이름을
실제로 참조하는가"를 grep으로 실측해 결정했다. 결과로 하드 의존성인 grilling과 tdd,
그리고 prototype만 보충하고 triage, wizard, codebase-design은 필요 상황이 올 때까지
미뤘다. 향후 세션은 이 세 개가 미설치라는 전제로 가르치면 된다.

**Evidence**: 사용자가 우선순위 표를 보고 1, 2, 4번(grilling, tdd, prototype)만 골라
수동 설치를 지시함. 근거 기반 선별 설치라는 접근을 그대로 채택한 것.

**Implications**: grill 계열과 implement의 내부 의존성이 해소돼 메인 플로우 실습 레슨이
가능해졌다. 다음 레슨에서 improve-codebase-architecture를 다룰 때는 codebase-design
미설치를 먼저 언급해야 한다.
