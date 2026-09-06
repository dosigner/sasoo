# 5. Conclusions

## 결론

1. 논문사수 Home 리디자인의 본질은 신규 기능이 아니라 **위계 재배치**다: 업로드를 히어로로, 최근 논문을 상태 배지 행 리스트로, 비용을 Stripe 문법의 작은 스탯 타일로.
2. 골격은 "시작 진입점 상단 고정 + 최근 항목 상시 병존"(Elicit·Dropbox Dash·Gamma·Humata에서 반복 검증, src_015, src_018, src_013, src_011)이 논문사수의 재방문 중심 가치에 가장 맞는다.
3. 업로드 히어로의 완성은 드롭존 스타일이 아니라 **드롭 후 3초** — 진행 연출(Humata, src_012)과 자동 요약·추천 액션(SciSpace·Adobe, src_010, src_020)까지가 한 세트다.
4. 시각 기조는 이미 갖춰진 관행(뉴트럴+단일 액센트, uppercase 마이크로 라벨)을 유지하되, 보더 축소·배경 레이어 위계·tabular-nums를 일관 적용(src_037, src_047).
5. 추천 실행 순서: **옵션 1(위계 재배치) → 옵션 2(AI 요약 라인 추가) → (장기) 옵션 3(프롬프트형)**.

## Confidence — 본문 단정에 사용한 검증 주장

`validate_ledger.py` 게이트 통과 verified 주장 17건만 본문 단정에 사용했다 (서명 `7ff11ede…`, state.json 기록). 대표:

| 주장 | 근거 도메인 수 |
|---|---|
| 대시보드 키트의 스탯 행→차트→테이블 수렴 (clm_001) | 4 (shadcn, GitHub, Tailwind, Tremor) |
| 시작 진입점 고정+최근 항목 병존 (clm_005) | 3 (Elicit, Dropbox, Gamma) |
| 업로드 직후 요약·추천 질문 (clm_004) | 2 (SciSpace, Adobe) |
| 드롭존 표준 3요소 (clm_006) | 3 (SIDP, uxpatterns, Filestack) |
| 2026 비주얼 기조 (clm_007) | 3 (SaaSFrame, UpDivision, 925studios) |

전체 목록: `outputs/verified_claims.json`.

## Refuted — 반증으로 폐기된 주장

없음 (0건).

## Unresolved — 미확정 (본문 단정 금지 처리)

1건. 벤토 그리드 사용률로 떠도는 % 수치(상위 제품의 3분의 2가량이라는 서술) — 마케팅성 아티클 2곳이 같은 값을 싣고 있으나 어디에도 방법론·원 자료 링크가 없고 플랫폼 공식 발표도 찾지 못했다. 미확정으로 분류해 본문 논지에 쓰지 않았다. 벤토 관련 본문 서술은 사용률이 아니라 "어디에 적합한가"에 대한 실무 가이드(clm_008)에만 근거한다. 상세: `outputs/unresolved_claims.json`.

## 남은 작업 제안

1. Mobbin/Nicelydone에서 SciSpace·Dropbox Dash·Gamma 실제 스크린 직접 열람 (텍스트 조사의 시각 공백 보완)
2. 옵션 1 와이어프레임 → Home.tsx 구현 계획 수립 (superpowers writing-plans)
3. 옵션 2용 "AI 요약 라인" 신호 정의 (진행중 분석·미분석 수·최근 작업)
