# GPT-6 Luna xhigh 재검토

작성일: 2026-10-07. 범위: 기존 effort sweep의 저장된 응답, 원장, 봉인된 원문 평가를 다시 읽은 오프라인 분석. 새 생성이나 token count 호출은 0회다. [전체 복구 보고서](2026-10-07-gpt6-luna-effort-sweep-recovery.md)의 단회 자료만 사용한다.

## 네 요청의 상태

| 논문 | xhigh 결과 | 원문 품질 판정 | 비용 상태 |
|---|---|---|---|
| Bell | `APIConnectionError`, 응답 ID와 usage 없음 | 답변 없음, 필수 내용 0/18, 주장 정확률 N/A | 예약 US$0.01077250, 실제 청구 불명 |
| DESeq2 | `APITimeoutError`, 응답 ID와 usage 없음 | 답변 없음, 필수 내용 0/46, 주장 정확률 N/A | 예약 US$0.01437700, 실제 청구 불명 |
| Diffusion Policy | 완료, 제품 형식 통과 | 필수 내용 20/46, 중대 오류 2건 | usage 기반 US$0.01535955 |
| Agile Locomotion | 완료, 제품 형식 통과 | 필수 내용 24/40, 중대 오류 0건 | usage 기반 US$0.00996442 |

실패 두 건은 모델이 내용을 틀리게 썼다는 증거가 아니다. 공급자 측 처리 여부와 실제 청구액도 확인할 수 없다. 비용 비교와 생성 시간 비교에는 완료된 두 건만 넣는다. [공식 GPT-6 Luna 모델 페이지](https://developers.openai.com/api/docs/models/gpt-6-luna)는 xhigh 지원과 standard 단가를 제시하지만, 위 금액은 청구서가 아니라 공급자 usage를 해당 요율로 재계산한 값이다.

## 완료된 두 논문의 high 대비 차이

| 논문 | 필수 내용 high → xhigh | Q5 high → xhigh | 재현 high → xhigh | 중대 오류 high → xhigh | 생성 초 high → xhigh | 생성비 USD high → xhigh |
|---|---:|---:|---:|---:|---:|---:|
| Diffusion Policy | 18/46 → 20/46 | 3/16 → 6/16 | 1/13 → 4/13 | 1 → 2 | 108.59 → 134.03 | 0.01347755 → 0.01535955 |
| Agile Locomotion | 21/40 → 24/40 | 5/19 → 8/19 | 3/14 → 6/14 | 1 → 0 | 112.80 → 103.68 | 0.00991242 → 0.00996442 |

Diffusion Policy의 xhigh는 high보다 생성 시간이 약 23.4%, 확인 생성비가 약 14.0% 늘었다. 원문 단위에서 xhigh만 완전히 다룬 항목은 사전학습 없는 ResNet-18 인코더와 정규화 변경, iDDPM 학습과 DDIM 실물 추론, 회전 표현, UR5의 10 Hz 정책과 125 Hz 위치 명령 사이의 이전 조건, 선형계 sanity check였다. 반대로 high만 충족한 항목도 있다. CNN과 Transformer의 관측 결합 차이, 실물 Push-T 성공률과 IoU 비교, Franka로 옮길 때의 별도 제어기와 충돌 제약이다. xhigh는 Figure 10의 붓기 **IoU 0.74를 coverage로 잘못 부르고**, 시뮬레이션과 실물을 합친 15개 과제를 시뮬레이션 과제 15개로 바꿔 적었다. high도 Table 5의 500 epoch 학습을 50 epoch로 적은 오류가 있다. 항목별 근거는 [Diffusion Policy 블라인드 평가](assets/effort-sweep-20261004/blind-review-resume/robotics2/review.json)에 남아 있다.

Agile Locomotion의 xhigh는 high보다 생성 시간이 약 8.1% 짧았고 확인 생성비는 약 0.5% 높았다. xhigh만 완전히 다룬 항목은 Minitaur, STM32, UART, Jetson TX2 제어 경로, 에피소드별 물리 파라미터 표본화, 힘 교란의 크기와 길이, 12D 관측의 시뮬레이션과 실물 결과 차이, 그 원인을 저자 가설로 한정한 설명이다. high만 다룬 항목은 사인 명령에 대한 구동기 모델 비교의 검증 범위와 그림별 표준오차/표준편차 구분이다. high는 시뮬레이션 테스트 환경의 변동 감소를 실물에서 측정된 감소처럼 확대한 중대 오류가 있었고 xhigh에는 검토 범위에서 중대 오류를 찾지 못했다. 그래도 xhigh의 재현 단위는 **6/14**다. 항목별 근거는 [보행 논문 블라인드 평가](assets/effort-sweep-20261004/blind-review-resume/transfer_locomotion/review.json)에 있다.

Diffusion Policy의 xhigh 출력 usage는 14,597/16,000 토큰으로 상한까지 1,403토큰이 남았다. 추론 토큰은 high 3,035개에서 xhigh 6,658개로 늘었지만, 원응답 본문 길이는 17,137자에서 17,687자로 조금만 늘었다. 이는 늘어난 출력 예산의 상당 부분이 추론에 쓰였다는 관측이다. 이 사실만으로 오류의 원인이나 다른 입력에서의 truncation을 증명하지 않는다. [공식 token counting 설명](https://developers.openai.com/api/docs/guides/token-counting)에 따르면 출력 상한에는 눈에 보이지 않는 토큰도 포함된다.

## 판단

xhigh는 두 완료 논문에서 재현 관련 필수 단위를 더 많이 충족했다. 그러나 Diffusion Policy에서는 중대 오류가 늘었고 지연과 비용도 늘었으며, Bell과 DESeq2에는 답변 자체가 없다. 보행 논문에서의 빠른 완료도 조건당 한 번의 서버 측정이라 일반적인 속도 우위로 볼 수 없다. 따라서 이번 자료는 xhigh를 공통 기본값으로 올릴 근거가 되지 않는다. 현재 deep_dive 기본 `high` 역시 최적값으로 입증된 것은 아니며, 제품 전체 체인과 반복 원문 검증은 별개 과제다.

새 API 요청으로 Bell과 DESeq2를 다시 생성하면 최초의 단회 sweep과 다른 **재시도 코호트**가 된다. 기존 응답과 미정산 원장을 보존하고 새 요청 ID, 승인 호출 수, count 범위, 생성비 상한을 별도로 정해야 한다. 같은 16,000 출력 상한과 저장된 입력 count를 적용했을 때 두 요청의 사전 예약액 합은 US$0.02514950이지만 이는 새 청구액이나 전체 count 비용의 보장이 아니다.

**검산 방법:** [조건 연결](assets/effort-sweep-20261004/condition-join-resume-20261007.json)에서 두 완료 논문의 high/xhigh Q5와 재현 분자를 비교하고, [실행 감사](assets/effort-sweep-20261004/execution-audit-resume-20261007.json)의 원응답 usage와 생성 시간을 확인한다. 점수 차이만 보고 승격하면 세부 단위의 손실, 중대 오류, 응답 실패를 놓치기 쉽다.
