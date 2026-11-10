# GPT-6 Luna effort sweep 준비

작성일: 2026-10-04. 상태: **오프라인 준비, 새 API 실행 승인 대기**. 새 생성 0회, token-count 호출 0회. 모델 품질이나 최적 effort를 측정한 결과가 아니다.

## 현재 답할 수 있는 것

2026-09-23의 같은 PDF 6편, high 조건 비교에서 GPT-6 Luna는 5.6 Luna 대비 논문별 생성 시간 비율 중앙값이 0.5272였고, 보고 사용량 기반 생성비는 56.45% 낮았다. 논문별 최초 1회이고 앱 전체 소요시간이 아니다. 원문 정확성은 일관된 우위를 보이지 않았다. 기존 평가 기준의 한계도 있으므로 모델의 일반적 품질 순위로 해석하지 않는다. [원래 실측](2026-09-23-gpt-6-luna-comparison.md).

2026-10-03의 GPT-6 Luna 내 프롬프트 A/B에서는 필수 질문 25/36에서 27/36, 중대 오류 3개에서 4개였다. 새로운 goal-candidate-v2는 그 실험 이후 작성했으며 아직 생성 결과가 없다. [프롬프트 실측](2026-10-01-gpt6-luna-prompt-measurement-2.md).

확인한 현재 소스에서 OpenAI 기본 MODEL_LUNA는 gpt-5.6-luna, deep_dive effort는 high다. 새 모델/프롬프트를 앱 기본값으로 적용하지 않았다. 실행 중인 앱의 빌드나 사용자 DB를 이번에 바꾼 것은 아니다.

## 탐색 비교

같은 후보 프롬프트에서 effort만 바꾼다. baseline.txt는 제품 프롬프트 변경 감지용이며 이 sweep의 생성 조건은 모두 v1.txt에 보관한 goal-candidate-v2다. 이 파일명은 기존 실행기 호환용이며 이전 v1 후보와 다르다.

| 항목 | 고정값 |
|---|---|
| 모델 | gpt-6-luna |
| effort | low, medium, high, xhigh |
| 논문 | Bell, DESeq2, Diffusion Policy, Sim-to-Real: Learning Agile Locomotion For Quadruped Robots v1 |
| 범위 | 원본 PDF 기반 단독 deep_dive, 새 대화, 이전 분석 결과 없음 |
| 설명 수준 | undergrad, neutral system |
| 입력/형식 | 같은 PDF bytes, detail=high, 같은 strict JSON schema |
| 출력 상한 | 16,000 tokens, reasoning을 포함한 전체 출력 예산 |
| 호출 수 | 4편 × 4 effort × 1회 = 생성 16회, 사전/직전 count 32회 |
| 순서 | 논문마다 low→medium→high→xhigh 순서를 한 칸 회전, effort별 각 순서 위치 1회 |
| tier/retry | default, SDK/제품 자동 재시도 0 |
| 외부 자료 | 생성 중 외부 검색/도구 없음. 원문 기준 inventory는 생성 입력에 넣지 않음 |

이 4편은 서로 다른 수식/통계/제어/실물 이전 과업을 탐색하기 위한 표본이다. 리뷰/실험 바이오 등 8편 전체를 대표한다고 주장하지 않는다. 새 보행 논문은 이 프롬프트 설계 뒤 고정했다. 공급자 학습 데이터 미포함을 뜻하지 않는다.

none과 max는 1차 탐색에 포함하지 않는다. 낮은 노력의 경계와 high보다 높은 노력의 이득을 4단계로 먼저 확인한다. API가 지원한다고 앱 기본값을 바로 올리지 않는다. 공식 문서는 medium/high를 복잡한 추론의 비교 대상으로, xhigh/max를 추가 지연 대비 품질 이득을 실측할 대상으로 설명한다. [OpenAI reasoning 가이드](https://developers.openai.com/api/docs/guides/reasoning), [effort 지침](https://developers.openai.com/api/docs/guides/deployment-checklist#set-up-reasoningeffort).

## 질문별/절별 판단

[원문 기준과 측정 계약](assets/analysis-quality-20261004/review-protocol.md)을 사용한다. 별도 문맥의 검토자가 모델 출력과 프롬프트를 보지 않고 PDF에서 작성한 고유 내용 단위로 분모를 고정한다. 5.6 답변을 정답으로 사용하지 않는다.

- 질문별/절별 핵심 충족률, 고유 주장 정확률, 출처 충족률을 각각 산출한다.
- 근거, 도출 이유, 판단상 의미가 연결된 유효 통찰 수와 유효율을 함께 센다. 같은 말을 늘려 쓴 것은 중복으로 센다.
- 재현 핵심 충족과 실행 차단 사유를 분리한다. 정확한 설명을 실제 코드/장비 재현 성공으로 표시하지 않는다.
- 실물 이전에서는 원문 조건, 달라지는 조건, 영향 경로, 확인 방법을 평가한다. 실물 직접 학습/별도 실험을 sim-to-real 성공으로 바꾸면 오류다.
- 중대 수치/정의/방향/인과/검증 범위 오류와 잘못된 미보고 판단을 별도로 기록한다.
- 한국어 STE 80 프로필은 전체 및 절별 설명 문장에서 명료성 조건을 만족한 비율이다. ASD-STE100 공식 적합률이 아니다. 정확한 내용/조건 삭제는 문체 통과로 처리하지 않는다.

형식 성공, 긴 답변, 낮은 비용만으로 우승을 정하지 않는다. 모든 effort에 중대 오류가 있으면 최적 설정이 검증됐다고 발표하지 않는다. 여러 품질 지표가 서로 엇갈리면 속도와 함께 공개하고 임의 가중합으로 감추지 않는다.

속도는 SDK 생성 시간과 count/전체 벽시계 시간을 나누고, 논문별 high 대비 시간 비율과 중앙값/범위를 제시한다. 4편 단회 자료로 p95나 통계적 동등성을 주장하지 않는다. provider cache read/write와 reasoning/visible output을 함께 기록한다. 순서 회전만으로 cache/server 상태 영향을 제거했다고 보지 않는다.

다음 확인 비교는 탐색에서 남은 후보를 8편 전체에서 반복하는 별도 조건이다. 이 계획에는 그 생성이나 비용 승인이 포함되지 않는다. 1차 탐색은 최적값 확정이나 제품 적용의 완료 조건이 아니다.

## 비용과 실행 경계

[비용 제안](assets/effort-sweep-20261004/budget-proposal.json): 생성 16회 추정 US$0.24191852, 새 생성비 상한 제안 US$0.25. 과거 누적 생성비 US$0.73535317, 기존 US$1 한도의 잔액 US$0.26464683, 미정산 생성 예약 0건을 현재 원장으로 확인했다.

입력은 같은 PDF의 과거 count와 신규 PDF의 페이지당 입력 추정에 20% 여유를 더했다. 출력은 각 16,000 상한, 입력 전체는 cache-write 요율로 예약했다. 추정치는 보장된 상한이 아니다. 승인 후 동일한 요청을 count하여 전체 비용을 다시 계산하고, 새 상한이나 누적 한도를 넘으면 생성을 시작하지 않는다.

확인 단가: 100만 token당 일반 입력 $0.10, cache read $0.01, cache write $0.125, 출력 $0.50. 272k 초과 입력의 배율도 계산기에 유지한다. standard endpoint만 허용한다. [공식 모델 단가](https://developers.openai.com/api/docs/models/gpt-6-luna).

count API 32회의 단가는 검토한 공식 문서에서 확정하지 못했다. 위 상한/추정은 생성비이며 count를 포함한 청구 총액 상한이 아니다. count 비용은 null로 남기고 무료로 가정하지 않는다.

새 실행은 [기존 사용자 실행 지시문 4절](../../RESEARCH/2026-10-01-gpt6-luna-measurement-metaprompt.md)의 “현재 세션에서 이 비교 cohort에 적용되는 명시적 새 지출 상한과 호출 범위를 확인한다”에 따라 이 sweep 범위의 승인이 필요하다. 이전 승인된 12회 A/B는 이미 소진됐으며 이번 effort sweep에 재사용하지 않는다.

오프라인 확인:

```bash
cd sasoo/backend
./.venv/bin/python tools/prompt_compare.py --mode check \
  --campaign ../../docs/validation/assets/effort-sweep-20261004
```

승인 후 실행할 준비된 명령(이 문서는 승인 자체가 아님):

```bash
./.venv/bin/python tools/prompt_compare.py --mode run \
  --campaign ../../docs/validation/assets/effort-sweep-20261004 \
  --approve-new-generation-usd 0.25 --approve-count-requests 32
```

실행기는 발행 전 예약, 원응답/SDK 시간 보존, 사용량 정산, 불명 비용 중단, replay 방지를 재사용한다. 현재 오프라인 검사에서 16개 실제 제품 요청의 차이는 effort뿐이며 API/network 시도는 0이다. 합성 provider로 low/medium/high/xhigh 전달 및 호출/예산 경계를 검증했고 관련 테스트 59개가 통과했다. 실제 모델 정확성/통찰/문체 결과는 미측정이다.
