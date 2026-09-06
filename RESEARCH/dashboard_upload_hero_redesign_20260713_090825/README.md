# 논문사수 Home 리디자인 레퍼런스 리서치

- **주제**: 요즘 스타일의 SaaS/AI 대시보드 겸 업로드 메인(hero) 페이지 redesign 사례 — 논문사수 Home 재설계용
- **조사일**: 2026-07-13 · **상태**: 완료 (7/7 phase, 검증 게이트 PASS)

## 읽는 순서

1. `outputs/00_executive_summary.md` — 결론과 추천안 요약
2. `outputs/01_full_report/02_current_landscape.md` — **사례 컬렉션 25+ 제품 (본체)**
3. `outputs/01_full_report/03_challenges.md` — 패턴 3개 + 안티패턴 6개 + 현재 Home 갭
4. `outputs/01_full_report/04_future_outlook.md` — 적용안 3옵션 (와이어프레임 포함)
5. `outputs/01_full_report/05_conclusions.md` — 결론 + Confidence/Unresolved/Refuted
6. `outputs/02_appendices/bibliography.md` — 소스 54건 A~E 등급

## 검증

- claim ledger 18건 → verified 17 / unresolved 1 / refuted 0 (`validate_ledger.py` 서명 기록)
- eval: PASS — 인용 해소 100%, 미검증 누출 0%, 고아 소스 0%, verified 커버리지 100%

## 원자료

- `artifacts/agent_results/01~05_*.md` — 5개 축 병렬 조사 원본
- `sources/sources.jsonl` — 소스 레지스트리 · `artifacts/claim_ledger.jsonl` — 주장 원장
