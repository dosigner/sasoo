# GPT-6 Luna effort sweep 실행과 기본 모델 변경

작성일: 2026-10-05. 판정: **comparison_incomplete**. 승인된 16개 생성 중 4개를 발행했고 3개가 완료됐다. 네 번째 요청의 응답과 사용량을 받지 못해 예산 원장이 후속 유료 호출을 중단했다. 완료 요청을 다시 발행하지 않았으며 나머지 12개도 발행하지 않았다. 현재 checkout의 OpenAI 기본 텍스트 모델은 GPT-6 Luna로 바꿨다. 패키지 릴리스는 만들지 않았다.

## 고정 조건과 실행 경계

[사전 계획](2026-10-04-gpt6-luna-effort-sweep.md)의 PDF 4편, 동일한 goal-candidate-v2 프롬프트, strict JSON, 16,000 출력 상한, 단독 deep_dive, 순서 회전, 재시도 0을 유지했다. 생성 16회, token-count 32회, 새 생성비 US$0.25의 이번 승인 범위를 사용했다. `--mode check`는 변경 전 frozen 해시와 실제 제품 요청 16개를 확인했고 API 호출은 없었다. 생성 전 count 16회가 산출한 전 요청 예약액은 **US$0.21235652**였다. 과거 누적 생성비 US$0.73535317과 합해도 US$1 한도 이내였으므로 실행기가 생성을 시작했다. [계산된 요청별 예약](assets/effort-sweep-20261004/counted-plan.json), [승인 시작 기록](assets/effort-sweep-20261004/paid-start.json).

현재 [OpenAI Docs의 GPT-6 Luna 모델 페이지](https://developers.openai.com/api/docs/models/gpt-6-luna)는 standard 100만 토큰당 입력 US$0.10, cache read US$0.01, cache write US$0.125, 출력 US$0.50을 제시한다. 세 완료 응답은 모두 `gpt-6-luna`, `default` tier였고 각 응답의 사용량을 이 요율로 별도 재계산해 원장과 일치했다. 출력 토큰에는 reasoning이 포함돼 별도로 더하지 않았다.

| 발행 상태 | 생성 | count |
|---|---:|---:|
| 완료 | 3 | 20 |
| 미정산 오류 | 1 | 0 |
| 미발행 | 12 | 12 |

Bell xhigh 요청에서 `APIConnectionError`가 발생했다. SDK가 응답과 usage를 반환하지 않았으므로 공급자 측 처리 여부와 실제 청구액은 모른다. 이 요청의 사전 예약액 **US$0.01077250**은 실제 비용이 아니다. 이미 확인된 세 생성의 비용 합계는 **US$0.01769976**이며, 과거 누적액을 합친 확인 비용은 **US$0.75305293**이다. 미정산 예약액까지 회계상 잡으면 **US$0.76382543**이지만 이를 확정 청구액으로 쓰지 않는다. count 단가는 확인되지 않아 총 청구액도 알 수 없다. [실행 감사와 요청별 상태](assets/effort-sweep-20261004/execution-audit-20261005.json), [원장](assets/effort-sweep-20261004/ledger.jsonl). 실패 요청의 UTC 시각 차이와 monotonic 측정의 차이가 커서 그 요청의 대기 시간을 effort 성능값으로 사용하지 않았다.

[OpenAI의 조직 사용량 API](https://developers.openai.com/api/reference/resources/admin/subresources/organization/subresources/usage/methods/completions)와 [비용 API](https://developers.openai.com/api/reference/resources/admin/subresources/organization/subresources/usage/methods/costs)는 관리자 키를 쓰는 집계 조회다. 이번 실패 기록에는 응답 ID나 클라이언트 요청 ID가 없어 그 집계에서 요청 한 건의 청구액을 확정할 수 없다. 확인되지 않은 비용을 0원 또는 원장의 정산 완료로 바꾸지 않았다.

## 익명 원문 검토와 effort 선택

별도 AI 검토자는 조건, 프롬프트, 비용, 시간, 과거 판정을 보지 않고 Bell 원본 PDF와 사전 고정한 18개 필수 의미 단위로 익명 답변을 검토했다. 판정을 SHA-256으로 봉인한 뒤 조건을 연결했다. JSON 봉인 해시는 `fbd3c61dea56e1a8e252c8796199da66ac8fb65b649515e80be8b938931f6de6`이다. [질문별/절별 판정과 원문 위치](assets/effort-sweep-20261004/blind-review-theory/review.json), [조건 연결](assets/effort-sweep-20261004/condition-join-20261005.json).

| effort | 필수 내용 | 재현 단위 | 일반 이전 단위 | SDK 생성 초 | 확인 생성비 USD |
|---|---:|---:|---:|---:|---:|
| low | 13/18 | 0/3 | 0/2 | 48.895 | 0.00535792 |
| medium | 13/18 | 0/3 | 0/2 | 46.725 | 0.00556642 |
| high | 15/18 | 1/3 | 1/2 | 70.784 | 0.00677542 |
| xhigh | 답변 없음, 내용 0/18 | N/A | N/A | 비교 불가 | 미확인 |

low와 medium의 질문별 충족은 Q1부터 Q6까지 `1/1, 5/5, 4/4, 1/1, 0/5, 2/2`로 같았다. high는 Q5가 `2/5`로 늘고 나머지는 같았다. high만 세 방향 대입에서 부등식의 양변을 `1/√2`와 `1−1/√2`로 계산하고, V절 일반화의 Hermitian 관측량 가정과 부분공간 밖 0을 연결했다. 원본 PDF의 식(15), 식(22), V절과 대조했다. 세 완료 응답 모두 한 입자 각도 변환, 식(15)의 중간 대수, 비행 중 설정 변경의 시간/거리 확인 연결을 빠뜨렸다. 검토 범위에서 중대 오류는 발견되지 않았다.

high의 시간은 low보다 44.8%, medium보다 51.5% 길었고 확인 생성비는 각각 26.5%, 21.7% 높았다. 이것은 Bell 한 편의 한 번씩 생성한 자료다. 다른 세 논문의 응답이 없어 전체 과업의 우수 effort나 재현 안정성을 고를 근거는 부족하다. 인계 시 사용자에게 알린 가정대로 deep_dive의 기존 `high`를 유지했다. 검토자의 주장 정확도 분모는 모든 사실 문장의 전수가 아니라 선별한 중요 고유 주장이다. 문체 판정과 오류 0도 독립 전문가 인증이나 실제 재현 성공이 아니다. 답변 없는 나머지 논문은 필수 내용 충족 0으로 기록하되 사실 정확률과 통찰률은 N/A다.

이 sweep은 5.6 대 6 모델 비교가 아니다. [과거 동일 PDF 6편의 high 비교](2026-09-23-gpt-6-luna-comparison.md)에서는 GPT-6 Luna의 논문별 생성 시간 비율 중앙값이 0.5272였고 보고 사용량 기반 생성비가 56.45% 낮았다. 엄격 원문 통과는 GPT-6 Luna 0/6, GPT-5.6 Luna 1/6이었으므로 정확성 우위를 입증하지 않았다. 이 과거 기준은 지금의 질문별 단위 채점과 다르다.

## 제품 변경과 확인

`services/models.py`의 `MODEL_LUNA`가 GPT-6 Luna를 가리키도록 변경했다. OpenAI 텍스트 역할은 이 상수를 공유하므로 deep_dive 이외의 역할도 GPT-6 Luna를 사용한다. 각 역할의 effort는 유지했고, deep_dive는 `high`다. `services/pricing.py`에는 이미 GPT-6 Luna 공식 standard 요율이 있다. 미등록 `gpt-*` ID에 쓰는 5.6 Luna 가격 fallback은 보수적인 비용 추정용이며 활성 모델 선택이 아니다. 설정 화면의 OpenAI 표기도 GPT-6 Luna로 맞췄다. [모델, registry, 가격, wire effort 확인](assets/effort-sweep-20261004/post-promotion-check-20261005.json).

새 goal-candidate-v2 프롬프트는 한 논문에서만 평가됐고 이번 sweep에는 기존 제품 프롬프트와 동시점 비교가 없다. 따라서 제품 프롬프트는 변경하지 않고 [실험 프롬프트](assets/effort-sweep-20261004/prompts/v1.txt)를 보존했다. `analysis_execution.py`의 기존 프롬프트 해시는 frozen 기록과 같다. 변경 전 모델과 registry bytes는 [스냅샷](assets/effort-sweep-20261004/pre-promotion-source/)에 보존했다.

기본 모델 변경 후 현재 checkout으로 같은 campaign의 `--mode check`를 다시 실행하면 frozen 소스 해시 차이로 실패하는 것이 정상이다. 생성 당시 소스와 요청의 해시, 원응답, 봉인한 평가를 보존했으며 이 campaign의 paid runner를 재실행하지 않는다.

검증: backend `pytest services api models` **1,065 passed**, `py_compile main.py` 통과. Frontend `tsc --noEmit`, `build`, `lint` 통과. 개발용 Electron에서 1400×865와 1024×768 창의 설정 화면에 GPT-6 Luna가 표시됐고 좁은 창에서 카드가 잘리지 않았다. 콘솔을 비우고 설정 화면을 다시 로드한 뒤 새 오류는 없었다. 비우기 전의 404 두 건은 존재하지 않는 `analysis/999004/experiment-plan` 요청이었으며 이번 설정 경로의 오류로 보지 않는다. [민감 정보가 없는 GUI 확인 요약](assets/effort-sweep-20261004/gui-check-20261005.json). 개발 서버는 종료했다. 이 확인은 소스와 개발 GUI에 한정된다. 새 모델의 전체 `visual→recipe→deep_dive` 체인, 설치 앱, 패키지, 실제 사용자 분석 결과는 검증하지 않았다. 추가 유료 호출은 발행하지 않았다.

**학습 메모:** 응답 형식 통과와 원문 내용 충족은 다른 지표다. Bell에서는 세 성공 응답 모두 형식이 유효했지만 핵심 유도 단위를 놓쳤다. 식(14)의 ±1 대수로 식(15)를 유도하고 세 방향의 내적을 대입하면 누락을 재검산할 수 있다. 연결 오류처럼 usage가 없는 시도를 0원으로 처리하거나 같은 요청을 다시 발행하면 비용 상한과 비교 조건을 동시에 훼손한다.
