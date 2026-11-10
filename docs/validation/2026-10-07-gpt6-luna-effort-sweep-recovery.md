# GPT-6 Luna effort sweep 복구와 원문 평가

작성일: 2026-10-07. 판정: **승인된 실행 범위는 완료, 공통 최적 effort는 미확정**. 생성 16/16건과 `responses.input_tokens.count` 32/32회를 발행했다. 생성 14건은 응답과 usage를 받았고 2건은 응답과 usage가 없어 비용이 미정산이다. 동일 요청의 재시도나 대체 생성은 없었다. 이 보고서는 [이전 실행 보고](2026-10-05-gpt6-luna-effort-sweep-execution.md)에 새 증거를 덧붙이며 이전 파일과 원응답을 바꾸지 않는다.

## 왜 멈췄고 어떻게 이어갔는가

첫 실행은 Bell xhigh에서 `APIConnectionError`를 받았다. SDK 응답 ID와 usage가 없어 전역 `BudgetJournal.spent()`가 미정산 요청을 발견하고 후속 유료 호출을 차단했다. 이 실패는 공급자 처리 또는 청구가 0원이라는 뜻이 아니다. 복구 중 DESeq2 xhigh도 약 601초의 SDK 대기 뒤 `APITimeoutError`로 끝났고 같은 방식으로 기록했다. 두 실패의 벽시계 시각과 monotonic 측정이 맞지 않아 이를 effort 성능 시간으로 쓰지 않았다.

기존 `--mode run`은 `paid-start.json` 재생 방지 조건 때문에 호출하지 않았다. 새 [복구 실행기](../../sasoo/backend/tools/resume_effort_sweep.py)는 발행되지 않은 연속 구간만 선택한다. 각 요청 전에 고정된 제품 요청 해시, PDF SHA-256, 사전 count, 직전 count, 출력 16,000 토큰 상한, standard endpoint, 단일 시도, 전역 원장과 승인 범위를 확인한다. `settled`는 사용량 기반 금액으로, `unsettled`는 예약액으로 보수적으로 계산하되 원장의 미정산 상태는 바꾸지 않는다. 완료와 실패 요청의 실행 ID가 있으면 재발행을 막는다. 각 복구 구간의 시작 기록, count, 요청, 원응답 또는 실패, 검증, 원장 전이는 새 파일 또는 append-only 행으로 남겼다.

생성 당시의 소스와 현재 제품 소스는 `models.py`, `model_registry.py` 두 파일에서 달랐다. [변경 전 bytes](assets/effort-sweep-20261004/pre-promotion-source/)로 격리 실행 환경의 두 파일만 복원했다. 다른 frozen 파일은 현재 bytes가 일치했고, 격리 환경의 `prompt_compare.py --mode check`는 저장된 제품 wire 요청 16개와 정확히 일치했다. 이 검사에서 생성과 count API 호출은 0회였다. 원래 `/tmp/sasoo-v101-papers`의 PDF 세 개가 임시 정리로 사라졌을 때에는 저장소의 [보존 PDF](assets/v1.0.1-summary-reading/model-gui/runtime/library/)에서 원래 SHA-256과 같은 파일을 찾아 경로를 복원했다. 현재 checkout의 미커밋 제품 변경은 되돌리거나 stash하지 않았다.

첫 복구 구간은 DESeq2 medium/high를 완료하고 xhigh timeout에서 멈췄다. 두 번째 구간은 다시 7개 발행 상태와 비용 경계를 확인한 뒤 나머지 9건만 진행했다. [복구 실행 감사](assets/effort-sweep-20261004/execution-audit-resume-20261007.json), [최종 파일 해시 목록](assets/effort-sweep-20261004/SHA256SUMS-resume-20261007), [원장](assets/effort-sweep-20261004/ledger.jsonl), [복구 구간 시작 기록](assets/effort-sweep-20261004/resume-start.json), [두 번째 구간 기록](assets/effort-sweep-20261004/resume-start-2.json)을 보존했다.

## 범위와 비용

조건은 PDF 4편, 동일한 goal-candidate-v2 프롬프트, `gpt-6-luna`, low/medium/high/xhigh, 논문별 순서 회전, 단독 deep_dive, 학부생 설명 수준, strict JSON, 출력 16,000 토큰, 단일 시도였다. 생성 입력의 최대 count는 64,489 토큰으로 공식 장문 입력 경계 272,000 토큰 아래였다. [OpenAI Docs 모델 페이지](https://developers.openai.com/api/docs/models/gpt-6-luna)의 standard 요율인 100만 토큰당 일반 입력 US$0.10, cache read US$0.01, cache write US$0.125, 출력 US$0.50으로 14개 공급자 usage를 독립 계산했다. 출력 usage에는 비가시 추론 토큰이 포함되며 별도 중복 과금하지 않았다. [token count 문서](https://developers.openai.com/api/docs/guides/token-counting)는 count API의 반환값과 동작을 설명하지만 이 실행의 count 요금을 확정할 단가를 제공하지 않아 count 비용은 계속 `null`이다.

| 생성비 항목 | USD | 의미 |
|---|---:|---|
| 이전 확정 사용량 기반 누적 | 0.73535317 | 이번 sweep 시작 전 원장 |
| 이번 완료 14건의 확인 계산액 | 0.13836190 | 공급자 usage와 요율의 재계산, 청구서 금액 아님 |
| 이번 실패 2건의 예약액 | 0.02514950 | 실제 청구액 미확인, 0원 처리하지 않음 |
| 이번 확인액과 실패 예약액 | 0.16351140 | 새 생성비 승인 US$0.25 안 |
| 과거 누적과 이번 확인액 | 0.87371507 | 확정 사용량 기반 누적 |
| 과거 누적과 이번 확인액, 실패 예약액 | 0.89886457 | 기존 US$1 경계의 보수적 검사값 |

원장에는 16개 실행 ID가 정확히 한 번씩 나타나며 최종 상태는 `settled` 14, `unsettled` 2, 중단된 `reserved` 0이다. 전역 registry의 다른 campaign 비용은 sweep 시작 때의 US$0.73535317에서 달라지지 않았다. 공식 [조직 비용 API](https://developers.openai.com/api/reference/resources/admin/subresources/organization/subresources/usage/methods/costs)는 현재 일 단위 집계 조회다. 실패 두 건에는 응답 ID나 요청 ID가 없어 이 API만으로 개별 청구액을 식별할 수 없다. 따라서 전체 청구액은 아직 미확인이다.

## 익명 원문 평가

원문 PDF로 먼저 고정한 [평가 기준](assets/analysis-quality-20261004/review-protocol.md)과 네 논문의 inventory를 사용했다. Bell의 기존 [봉인 판정](assets/effort-sweep-20261004/blind-review-theory/review.json)에 이어 DESeq2, Diffusion Policy, Agile Locomotion은 서로 별도의 검토자가 effort, 비용, 시간, 조건 매핑을 보지 않고 익명 출력의 필수 의미 단위를 원문과 대조했다. 세 [익명 판정 파일](assets/effort-sweep-20261004/blind-review-resume/)의 최종 SHA-256을 확인한 뒤 [조건 연결](assets/effort-sweep-20261004/condition-join-resume-20261007.json)을 만들었다. 각 필수 단위의 응답 위치, 원문 위치, 판정 이유와 절별 분자/분모는 판정 JSON에 있다.

아래 Q1~Q6은 순서대로 문제와 목표, 방법과 원리, 결과와 해석, 한계와 범위, 재현과 이전, 불확실성이다. `재현`과 `이전`은 질문 Q5의 부분집합과 별도 kind 분모를 사용하므로 Q5 합계와 같지 않다. `0/n`은 응답이 없어 필수 내용을 충족하지 못한 경우도 포함한다. 응답 없는 두 xhigh의 오류율, 정확률, 시간과 비용은 N/A다. 시간은 성공한 SDK 생성 초이며 전체 앱 시간이나 실패 대기 시간이 아니다.

| 논문 | effort | 필수 내용 | Q1~Q6 충족 | 재현 | 이전 | 중대 오류 | 생성 초 | 생성비 USD |
|---|---|---:|---|---:|---:|---:|---:|---:|
| Bell | low | 13/18 | 1/1, 5/5, 4/4, 1/1, 0/5, 2/2 | 0/3 | 0/2 | 0 | 48.9 | 0.00535792 |
| Bell | medium | 13/18 | 1/1, 5/5, 4/4, 1/1, 0/5, 2/2 | 0/3 | 0/2 | 0 | 46.7 | 0.00556642 |
| Bell | high | 15/18 | 1/1, 5/5, 4/4, 1/1, 2/5, 2/2 | 1/3 | 1/2 | 0 | 70.8 | 0.00677542 |
| Bell | xhigh | 0/18 | 0/1, 0/5, 0/4, 0/1, 0/5, 0/2 | 0/3 | 0/2 | N/A | N/A | 미확인 |
| DESeq2 | low | 20/46 | 1/1, 7/12, 3/9, 2/2, 4/17, 3/5 | 2/15 | 2/2 | 1 | 64.6 | 0.01030642 |
| DESeq2 | medium | 21/46 | 1/1, 10/12, 2/9, 1/2, 4/17, 3/5 | 3/15 | 1/2 | 0 | 64.4 | 0.01051392 |
| DESeq2 | high | 23/46 | 1/1, 9/12, 4/9, 1/2, 5/17, 3/5 | 3/15 | 2/2 | 0 | 57.5 | 0.01208142 |
| DESeq2 | xhigh | 0/46 | 0/1, 0/12, 0/9, 0/2, 0/17, 0/5 | 0/15 | 0/2 | N/A | N/A | 미확인 |
| Diffusion Policy | low | 18/46 | 2/2, 3/5, 3/15, 2/3, 5/16, 3/5 | 2/13 | 3/3 | 0 | 55.7 | 0.01144055 |
| Diffusion Policy | medium | 20/46 | 2/2, 4/5, 4/15, 2/3, 5/16, 3/5 | 2/13 | 3/3 | 1 | 75.1 | 0.01276705 |
| Diffusion Policy | high | 18/46 | 2/2, 4/5, 4/15, 2/3, 3/16, 3/5 | 1/13 | 2/3 | 1 | 108.6 | 0.01347755 |
| Diffusion Policy | xhigh | 20/46 | 2/2, 3/5, 3/15, 3/3, 6/16, 3/5 | 4/13 | 2/3 | 2 | 134.0 | 0.01535955 |
| Agile Locomotion | low | 22/40 | 2/2, 3/5, 6/8, 2/2, 8/19, 1/4 | 5/14 | 6/8 | 0 | 60.1 | 0.00738442 |
| Agile Locomotion | medium | 18/40 | 2/2, 2/5, 7/8, 2/2, 4/19, 1/4 | 2/14 | 5/8 | 1 | 56.8 | 0.00745442 |
| Agile Locomotion | high | 21/40 | 2/2, 3/5, 7/8, 2/2, 5/19, 2/4 | 3/14 | 5/8 | 1 | 112.8 | 0.00991242 |
| Agile Locomotion | xhigh | 24/40 | 2/2, 3/5, 8/8, 2/2, 8/19, 1/4 | 6/14 | 5/8 | 0 | 103.7 | 0.00996442 |

[Bell 검토](assets/effort-sweep-20261004/blind-review-theory/review.md)에서는 high만 식(15)의 세 방향 대입 양변과 V절 일반화의 핵심 조건을 연결해 low/medium보다 필수 단위 2개를 더 충족했다. 이때 high는 low보다 생성 시간이 44.8%, 확인 생성비가 26.5% 더 들었다. [DESeq2 검토](assets/effort-sweep-20261004/blind-review-resume/bio2/review.md)에서도 high가 필수 내용 23/46으로 가장 많았으나 재현 단위는 3/15에 그쳤다. low는 원문의 fold change 2, 3, 4를 log2 fold change 값 2, 3, 4로 바꿔 적은 중대 척도 오류가 있었다. 원문 Figure 3과 모의 설정 문장을 직접 다시 대조했다.

[Diffusion Policy 검토](assets/effort-sweep-20261004/blind-review-resume/robotics2/review.md)의 필수 내용은 effort에 따라 18~20/46으로 좁게 움직였고, high에는 Table 5의 500 epoch를 50 epoch로 쓴 중대 오류가 있었다. medium과 xhigh에는 Figure 10의 붓기 IoU 0.74를 coverage로 바꾼 오류가 있었으며 xhigh에는 15개 과제의 시뮬레이션과 실물 범위를 바꾼 오류도 있었다. 실물 재현 단위는 네 응답 모두 1~4/13이었다. [Agile Locomotion 검토](assets/effort-sweep-20261004/blind-review-resume/transfer_locomotion/review.md)에서는 xhigh가 24/40으로 가장 많이 충족했지만 재현은 6/14였다. medium은 관측 자체를 학습 중 무작위화했다고 원문 밖으로 넓혔고, high는 실물 성능 변동 감소를 측정된 결과처럼 표현했다. 세 검토자의 주장과 출처 감사 분모는 서로 다르며 완전한 사실 문장 전수 조사가 아니다. 한국어 STE 80 문장 적합률도 새 세 논문에서 전수 평가하지 않았다.

## 제품 설정과 검증 경계

이 sweep은 GPT-5.6 Luna와 GPT-6 Luna의 동시점 비교가 아니며, 실험의 goal-candidate-v2 프롬프트도 현재 제품 프롬프트와 동시점 비교하지 않았다. [과거 6편 모델 비교](2026-09-23-gpt-6-luna-comparison.md)에서는 GPT-6 Luna의 논문별 생성 시간 비율 중앙값이 GPT-5.6 Luna의 0.5272였고 사용량 기반 생성비는 56.45% 낮았으나, 엄격 원문 정확성 통과는 GPT-6 Luna 0/6, GPT-5.6 Luna 1/6이었다. 따라서 이번 결과로 모델 정확성 우위나 제품 전체 분석 품질의 개선을 주장할 수 없다.

현재 제품의 deep_dive effort `high`는 유지했다. 이 세션에서 기존 제품 소스의 미커밋 내용을 수정하지 않았다. Bell과 DESeq2에서는 내용 충족이 가장 높았지만 Diffusion Policy와 Agile Locomotion에서는 다른 effort가 더 많은 단위를 충족했고 high에도 중대 오류가 있었다. xhigh는 4편 중 2편에서 답변이 없었다. 논문당 각 조건 한 번, 별도 AI 원문 검토, 과제별 다른 분모로는 공통 최적 effort나 재현 안정성을 확정할 수 없다. 어느 조건에서도 완전한 재현 설명을 얻지 못했다. 전체 `visual→recipe→deep_dive` 체인, 설치 앱과 실제 연구자 사용 결과도 이번에 평가하지 않았다.

검증한 계층은 다음과 같다. 격리된 생성 소스/제품 wire 요청 해시 16개 일치, 공급자 원응답/usage/원장 독립 감사 16개 일치, 익명 원문 판정의 조건 연결과 16개 입력 해시 일치, 복구 비용 규칙 테스트를 포함한 model registry/pins 관련 pytest 38개 통과, 복구 및 감사 스크립트 `py_compile` 통과. 이 세션에서 제품 모델 선택 값과 GUI 동작을 바꾸지 않았으며 GUI, 패키지, 설치 앱을 재검증하지 않았다. 이전 [개발 GUI와 소스 검증 범위](2026-10-05-gpt6-luna-effort-sweep-execution.md)는 그대로 이전 세션의 증거다.

**학습 메모:** 응답이 없는 요청은 품질 충족 0으로 기록하되 정확률과 실제 청구액은 N/A다. 연결 오류를 0원으로 정산하면 전역 예산을 과소 계산하고, 같은 요청을 재발행하면 단회 비교를 깨뜨린다. 재현할 때는 [감사 스크립트](assets/effort-sweep-20261004/audit_resume.py)의 `--check`, [조건 연결 스크립트](assets/effort-sweep-20261004/join_resume_reviews.py)의 `--check`로 원장과 봉인 판정의 일치를 확인한다. 가장 큰 함정은 JSON 형식 통과, 출처 문자열 존재, 긴 답변을 원문 정확성과 재현 가능성으로 받아들이는 것이다.
