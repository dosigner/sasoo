# Diffusion Policy 3개 모델 단회 비교 실행

상태: 2026-10-07 실행과 감사 완료. GPT-6.1 Sol 응답 부재로 3개 모델의 품질 비교는 미완료.

## 결과

| 모델 | 생성 결과 | 원문 필수 내용 충족 | 확인된 중대 오류 | 생성 시간 | 확인 가능한 생성 비용 |
| --- | --- | ---: | ---: | ---: | ---: |
| GPT-5.6 Luna | 제품 스키마 통과 | 19/46 | 1 | 104.2초 | US$0.02771750 |
| GPT-6 Luna | 제품 스키마 통과 | 19/46 | 0 | 89.8초 | US$0.01283255 |
| GPT-6.1 Sol | `APIConnectionError`, 응답 없음 | 평가 불가 | 평가 불가 | 평가 불가 | 미정산 |

이 표는 같은 PDF에 대해 모델마다 `deep_dive`, `high` 생성 요청을 한 번씩 보낸 관측값이다. 각 요청의 사전 입력 토큰 수는 63,485개였다. GPT-6.1 Sol의 응답 부재는 클라이언트가 본 응답이 없다는 뜻이며, 서버 수신 여부나 청구액이 0이라는 뜻은 아니다. 오류까지 약 306.6초가 걸렸지만 완료된 생성 지연으로 비교하지 않았다. 재시도하지 않았다.

완료된 두 생성의 사용량 기반 비용 합계는 US$0.04055005다. 응답 없는 Sol 요청은 사전 계산한 US$0.31871250을 미정산 예약액으로 유지한다. 두 값의 합은 US$0.35926255로 이번 생성 요청 한도 US$0.40 이하다. 입력 토큰 계산 요청은 계획한 6회를 모두 완료했으나 별도 단가를 확인하지 못해 계산 요청 비용은 합계에 넣지 않았다. 앞선 실험의 누적 US$1 제한은 이번 시도에 적용하지 않았다.

## 조건과 평가 근거

원문은 제공된 19쪽짜리 *Diffusion Policy: Visuomotor Policy Learning via Action Diffusion* PDF다. SHA-256은 `b65c474b696a4802d8f1457d86b637ce2c5521412570d3aa928cd54563babc8f`다. 같은 제품 경로에서 모델 ID만 바뀐 요청을 오프라인으로 포착하고 입력, 출력 스키마, 추론 설정의 동일성을 확인한 뒤 실행했다. GPT-6.1 Sol의 모델 등록과 요율은 실험 프로세스에만 주입했다. 제품 기본 설정이나 소스의 모델 등록은 바꾸지 않았다.

답변 생성 전에 고정한 [46개 필수 내용 목록](assets/analysis-quality-20261004/inventories/robotics2.json)을 원문으로 다시 대조했다. 단위의 숫자, 조건, 비교 대상 중 결정적인 요소가 빠지면 부분 언급으로 기록하고 충족 분자에는 넣지 않았다. 결과는 [단위별 익명 평가](assets/model-compare-20261007/review-pack/blind-unit-review.json), [평가 정정](assets/model-compare-20261007/review-pack/review-amendment.json), [모델명 결합 결과](assets/model-compare-20261007/review-pack/quality-summary.json)에 남겼다. 익명 표기는 평가 순서를 고정하기 위한 것이며, 독립 검토자를 추가한 이중 맹검 평가는 아니다. 한 검토자의 판단이므로 근소한 차이는 확정적 우열로 해석하지 않는다.

질문별 충족률은 다음과 같다. `Q1`은 문제/목표, `Q2`는 방법/원리, `Q3`은 결과/해석, `Q4`는 한계/범위, `Q5`는 재현/환경 이전, `Q6`은 불확실성이다.

| 모델 | Q1 | Q2 | Q3 | Q4 | Q5 | Q6 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| GPT-5.6 Luna | 2/2 | 3/5 | 3/15 | 2/3 | 6/16 | 3/5 |
| GPT-6 Luna | 2/2 | 4/5 | 2/15 | 2/3 | 6/16 | 3/5 |

두 답변 모두 문제와 기본 확산 정책은 설명했지만, 실험과 재현 세부를 많이 빠뜨렸다. 예를 들어 시뮬레이션의 4500/3000 epoch 설정, 실물 Push-T의 성공 IoU 문턱과 평가 시연 수, 소스 과제의 시연 수 불일치, Kitchen p4 개선율의 본문/표 차이를 충분히 다루지 않았다. 따라서 19/46은 구조화된 답변이 생성된 사실과 별개의 원문 충실도 측정이다. 두 모델의 재현 단위 충족은 모두 4/13, 이전 조건 단위는 모두 2/3이었다.

GPT-5.6 Luna의 `key_results`는 실물 Push-T의 95% 성공률과 평균 IoU 0.80을 end-to-end **Transformer** 기반 정책에 배정한다. 원문 PDF p.9 Table 6에서 이 값은 end-to-end **CNN** 정책의 결과다. Transformer end-to-end 행은 성공률 65%, IoU 0.53이다. 이는 숫자 자체를 맞혔어도 모델 변형에 잘못 연결한 중대 비교 오류다. GPT-6 Luna 답변에는 이번 검토 범위에서 같은 종류의 중대 오류가 확인되지 않았다. 이 판단은 전체 사실 주장의 완전한 정확률이나 모든 출처 표기의 정확률을 측정했다는 뜻은 아니다.

이번 한 건에서는 GPT-6 Luna가 GPT-5.6 Luna보다 확인 가능한 생성 비용이 약 54% 낮고 완료까지 약 14% 빨랐다. 내용 충족은 같았고, GPT-5.6 Luna에는 위의 중대 오류 한 건이 있었다. 단일 논문, 단일 응답으로 평균적인 속도나 품질 우위를 확정할 수 없고 Sol 품질 결과도 없으므로 제품 기본 모델을 바꿀 근거는 아직 부족하다.

## 감사와 재현

- [실행 계획](assets/model-compare-20261007/offline-plan.json), [계산 후 예산](assets/model-compare-20261007/counted-plan.json), [요청 원장](assets/model-compare-20261007/ledger.jsonl), [독립 실행 감사](assets/model-compare-20261007/execution-audit.json)를 보존했다. 각 모델의 원문 응답 또는 실패 기록은 같은 폴더의 `*.provider.json`, `*.provider-failure.json`, `*.result.json`에 있다.
- `sasoo/backend/.venv/bin/python docs/validation/assets/model-compare-20261007/audit_compare.py --check`는 토큰 계산, 제공자 응답, 비용, 원장 상태가 저장된 감사와 일치함을 확인했다.
- `sasoo/backend/.venv/bin/python docs/validation/assets/model-compare-20261007/review-pack/finalize_review.py --check`는 익명 평가, 정정 기록, 모델 결합, 실행 감사를 다시 대조했다.
- `sasoo/backend/.venv/bin/python docs/validation/assets/model-compare-20261007/run_compare.py --mode check`는 동결된 제품 요청과 소스 해시가 일치함을 확인했으며 API 호출은 0회였다. 실행 모드는 재사용하지 않는다.

비용 계산 요율은 공식 모델 문서의 [GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna), [GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna), [GPT-6.1 Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol)을 사용했다. 비용은 기록된 사용량에 요율을 곱한 실험 측 계산이며 최종 청구서와 같다고 인증하지 않는다.

## 배운 점

제품 스키마 통과는 JSON 구조의 검증이고, 원문 비교의 정확성은 별도 검증이다. Table 6처럼 값과 모델 변형을 함께 확인해야 숫자가 맞더라도 잘못된 결론을 잡아낼 수 있다. 같은 PDF와 동결된 질문을 재사용할 때는 응답의 출처 위치까지 단위별로 대조하고, 응답 없는 요청의 비용을 0으로 쓰지 않는다.
