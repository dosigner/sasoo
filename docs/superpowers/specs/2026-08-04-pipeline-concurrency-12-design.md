# 파이프라인 동시성 기본값 8→12 상향 — 설계

날짜: 2026-08-04
상태: 사용자 승인 완료 (브레인스토밍 세션에서 "안전한 개선만" + "12로 고정" 선택)

## 배경 (실측 근거)

2026-08-03~04 실측 3건이 이 설계의 전부다.

1. **429 관측 (동시성 12, production lane 13편, 캐시 끔):** 실제 API 호출 254건,
   max_inflight 12 도달, 429·408·5xx **0건**. (`tools/extraction_audit/_out/measure_production_conc12.json`)
2. **8 vs 12 비교 (resolver 구간만):** 294.7초 vs 301.0초 — 차이 없음. resolver는
   대기열이 8을 거의 안 넘어 상한 상향이 무의미하다.
3. **점유율 실측 (논문 1편 전체 경로, 12페이지):** 총 116.5초 중 **페이지 비전 파싱이
   95.1초(81.6%)**, 호출당 평균 17초. 12페이지가 한꺼번에 대기열에 서므로 동시성 8이면
   8+4 두 웨이브다. (`conc12_probe.py`·`occupancy_probe.py`는 세션 스크래치에 있고,
   원장 JSON은 `_out/`에 남아 있다)

결론: 상한 상향은 resolver가 아니라 **페이지 비전 파싱 구간에만** 유효하며, 12까지는
rate limit 여유가 실측으로 확인됐다.

## 변경 내용

코드 기본값 2곳 + 근거 주석. 그 외 일절 무수정.

1. `sasoo/backend/services/concurrency.py` — `PIPELINE_LLM_CONCURRENCY` 기본값 8→12
2. `sasoo/backend/services/gemini_parser.py` — `PAGE_CONCURRENCY` 기본값 8→12

두 값을 함께 올린다. 실효 동시성 = min(PAGE_CONCURRENCY, PIPELINE_LLM_CONCURRENCY)이라
한쪽만 올리면 다른 쪽 세마포어에서 막힌다(gemini_parser.py 주석에 명시된 기존 사실).

각 상수의 기존 주석에 한 줄 추가: "8→12: 2026-08-04 실측 — 동시성 12·실호출 254건에서
429 0건, max_inflight 12 도달. 문제 시 env로 롤백."

## 자동으로 따라오는 것

`PIPELINE_EXECUTOR` 풀 크기 = `max(CPU, LLM동시성 + RENDER 3 + 여유 2)` → 바닥 13→17
스레드. 스레드 대부분이 HTTPS 대기로 잠들어 CPU를 먹지 않는다는 기존 설계 노트를 그대로
탄다. 4코어 Windows 실기는 기존에도 미검증이었고 이번 변경으로 성격이 달라지지 않는다.

## 건드리지 않는 것 (기존 계약)

- resolver 2단계 순차 계약 (그림 번호·크롭 파일명이 그룹 순서 의존)
- 루프별 세마포어 구조 (`pipeline_llm_sem`의 WeakKeyDictionary 레지스트리)
- env 오버라이드: `SASOO_PIPELINE_LLM_CONCURRENCY=8 SASOO_GEMINI_PARSER_PAGE_CONCURRENCY=8`
  로 코드 변경 없이 즉시 롤백 가능
- 페이지 비전 호출의 출력 구조·DPI·thinking·media_resolution (품질 영역 — 이번 범위 밖)

## 검증 계획

1. 기존 백엔드 테스트 스위트 통과
2. **occupancy probe 재실행(실제 API, 같은 논문):** 비전 파싱 95초 → 약 60초로 감소,
   429 0건 확인
3. deterministic lane(무료·비결정성 없음)으로 정확도 무회귀 확인 — 동시성은 정확도
   경로와 독립이지만(순차 계약 유지) 싸게 확인 가능하므로 돌린다

## 예상 효과

- 12페이지 논문: 비전 파싱 2웨이브→1웨이브, 약 35초 단축 (전체 116초 기준 ~30%)
- 30페이지급: 4웨이브→3웨이브 (~25% 단축, 미실측 추정)
- 위험: 실측 기준 429 0건. 발생 시 재시도 정책(백오프 중 세마포어 반납)이 이미 정비돼
  있고, env 롤백 경로가 있다.

## 범위 밖 (명시적 보류)

- 비전 호출 출력 재설계(마크다운 생략 등 호출당 17초의 구조적 절감) — "안전한 개선만"
  선택으로 제외. 착수하려면 12-lane 회귀 게이트 동반 필수.
- 동시성 16 이상 — 미실측. 필요해지면 429 관측 측정을 먼저 돌린다.
