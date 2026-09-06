# Gemini 3.7 Flash vs 3.8 Flash: 같은 프롬프트로 토큰·비용·결함 A/B (2026-09-05)

결정 기록: docs/product-decisions.md DEC-021. 원자료: `2026-09-05-gemini-3-8-flash-ab/`
(회차별 summary JSON 6개, 실행 로그, 실행 스크립트 `ab_flash.py`).

## 왜 측정했나

Google Cloud의 3.8 Flash 개발자 가이드가 "3.7 대비 정확도와 신뢰성이 오르지만 토큰 소비가
더 많다. 연산 효율이 최우선이면 3.7을 고려하라"고 명시한다. 이 앱에서 그 증가폭이 얼마인지
모른 채 올릴 수는 없었다.

## 방법

- 도구: `tools/provider_compare.py`를 그대로 쓰고, 레지스트리(`model_registry._REGISTRY["gemini"]`)의
  FLASH_HQ 항목만 대상 모델로 바꿔 끼웠다(effort는 프로덕션 값 그대로).
- 입력: paper 43(Saliency Optimization, 2014), Gemini Files API PDF + 프로덕션 프롬프트·스키마.
  stateless(store=False), 체인 없음. 프로덕션 체인(previous_interaction_id, 페르소나 지시문)은 재현하지 않는다.
- 회차: 모델당 3회. 3.7은 citation·visual·recipe, 3.8은 여기에 deep_dive(high)를 더했다.
- 측정값: tokens_in, tokens_out(thinking 포함, 과금 기준), reasoning 토큰, 지연, 비용, 결함(`_stage_result_defect`)과 재시도.
- **품질은 보지 않았다.** 출력 본문은 마지막 회차(3.8 rep 3)만 `outputs/provider_compare/`에 남는다.

## 결과 (중앙값, n=3)

| stage | effort | 모델 | in | out | reasoning | 지연 s | 비용/회 | 결함 |
|---|---|---|---|---|---|---|---|---|
| citation | low | 3.7 | 2,664 | 1,296 | 0 | 5.8 | $0.0066 | 0/3 |
| citation | low | 3.8 | 2,664 | 1,274 | 0 | 6.1 | $0.0068 | 0/3 |
| visual | low | 3.7 | 5,788 | 966 | 0 | 7.2 | $0.0079 | 0/3 |
| visual | low | 3.8 | 5,788 | 1,089 | 0 | 7.3 | $0.0083 | 0/3 |
| recipe | medium | 3.7 | 4,759 | 2,547 | 703 | 9.2 | $0.0140 | 0/3 |
| recipe | medium | 3.8 | 4,759 | 3,097 | 769 | 11.6 | $0.0158 | 0/3 |
| deep_dive | high | 3.8 | 4,950 | 6,317 | 3,475 | 26.9 | $0.0283 | 0/3 |

회차별 out/reasoning: recipe 3.7 = 2,411/530, 2,547/703, 3,393/1,118. recipe 3.8 = 4,045/2,136, 2,628/769, 3,097/599.
deep_dive 3.8 = 6,317/3,475, 8,485/5,620, 4,855/2,134. 재시도 0, 결함 0. 총 지출 $0.263.

## 읽는 법

- 출력 토큰 증가: citation −2%, visual +13%, recipe +22%(중앙값). 비용 +2~13%. recipe는 회차 범위가 겹친다.
  논문 한 편의 텍스트 체인 기준 증가폭은 $0.005 안쪽이다.
- 3.8 deep_dive high는 3/3 무폭주, 출력 4,855~8,485로 3.7의 정상 범위(2,840~6,946, RESEARCH/2026-08-29) 안팎이다.
  단 3.7이 폭주한 표본은 VLA 논문 6편(4/6)이고 이 논문은 CV 도메인이라, DEC-019 재검토 근거로는 부족하다.
- 마지막 3.8 출력 점검: deep_dive 14/14 필드 채움(빈 필드 0), recipe 파라미터 10개(evidence_quote·page 포함),
  visual 9그림·2표·10수식·발견 11건, citation ref_analyses 7건.

## 한계

표본 논문 1편, 회차 3회, 품질 미측정, 체인 미재현. 페이지 비전 파싱(visual_parse)은 측정하지 않았다.
