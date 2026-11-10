# GPT-6 Luna 원본 PDF 전환과 실제 비교 결과

작성일: 2026-09-23. 판정: **`candidate_failed`**. 원본 PDF 연결과 검증 도구를 구현하고 같은 PDF의 12회 비교 및 대표 역할 5회를 실행했다. GPT-6 Luna는 비용과 생성 시간이 줄었지만 기존 6편 정확성 기준을 모두 통과하지 못했다. **운영 기본값은 GPT-5.6 Luna를 유지한다.**

**검증 범위 주의:** 최종 확인 중 r6 검증 이후의 추가 프런트엔드 편집을 발견했다. 아래 299개 테스트와 GUI 결과는 기록된 r6 소스/빌드에 대한 결과이며 현재 추가 편집본의 통과를 뜻하지 않는다. [후속 변경 기록](assets/gpt-6-luna/qa/post-validation-source-drift.json)에 당시 12개 소스 차이와 보존한 r6 빌드 위치를 기록했다. 백엔드/모델 입력 해시는 이 확인 시점에도 일치했다.

이 기록은 구현/형식 검사, 원문 정확성, 개발 Electron GUI, 패키지 검증을 구분한다. 17회 모두 완료/형식 검사를 통과한 사실이 과학적 정확성 통과를 뜻하지 않는다. GUI 기능/구조는 통과했고 엄격 CJK 검사는 REVISE로 남았다. 이를 과학적 판정과 별도로 기록한다.

## 결론과 측정 조건

같은 원본 PDF 바이트, `detail=high`, `effort=high`, `undergrad`, 동일한 neutral system/strict schema, 출력 상한 16,000, 새 대화, 도구 없음, `service_tier=default`로 비교했다. application cache는 격리했고 provider 사용량을 보존했다. 순서는 Bell B→C, DP C→B, 리뷰 B→C, bio1 C→B, bio2 B→C, UR5 C→B였다. B는 5.6 PDF, C는 6 PDF다.

| 관측 항목 | GPT-5.6 Luna PDF | GPT-6 Luna PDF | 해석 |
|---|---:|---:|---|
| 기존 원문 기준 전체 통과 | 1/6 | 0/6 | 필수 누락과 출처 결함까지 포함한 최종 엄격 판정 |
| 완료 및 strict 형식 통과 | 6/6 | 6/6 | 정확성 판정과 별개 |
| 실제 사용량 기반 비용 | US$0.13456375 | US$0.05859866 | 이번 6편에서 56.45% 감소 |
| 캐시 중립 비용 환산 | US$0.12208100 | US$0.05235730 | 캐시 읽기/쓰기를 제외하고 모든 입력을 일반 요율로 계산, 57.11% 감소 |
| 논문별 생성 시간 비율 C/B | 기준 | 중앙값 0.5272 | 47.28% 짧음. 비율 범위 0.3314~0.7205 |

시간은 전송 직전 예약 이후부터 공급자 응답/사용량 수신까지의 앱 측 구간이다. 논문별 최초 1회씩이며 일반적인 속도 우월성이나 통계적 유의성을 입증하지 않는다. 정확성 퇴보가 있어 사전의 비용/속도 개선 게이트는 충족하지 못했다. 가격과 빠른 응답만으로 모델을 승격하지 않았다.

요청별 입력/지시문/strict wire schema가 모델 ID를 제외하고 같은지는 [사전 비교 지문](assets/gpt-6-luna/qa/budget-preflight-decision.json)으로 확인한다. [전체 CSV](assets/gpt-6-luna/primary-16k/complete-comparison.csv)는 Q1~Q6, 오류, 원본/응답 링크와 모든 사용량을 함께 담는다. [측정 요약](assets/gpt-6-luna/primary-16k/measurement-summary.json)의 수치는 정확성 판정과 독립적인 관측값이다.

## 6편 전수 정확성 결과

| 논문 | 5.6 PDF | 6 PDF |
|---|---|---|
| Bell | PASS | FAIL: 단위벡터 성립 조건 누락 |
| Diffusion Policy | FAIL: 시뮬레이션 범위, Transformer 결과 귀속, 회전 정규화 예외, Q6 누락 | FAIL: Q6의 T블록 질량/마찰계수 미확인 누락. 앞의 사실 오류 2개와 정규화 문제는 해소 |
| 의료영상 리뷰 | FAIL: 유방의 데이터 부족 진술을 복부에도 귀속 | FAIL: 정확한 308편 수치의 근거 위치 누락. 수치 자체는 정확 |
| Jinek 인간 세포 편집 | FAIL: sgRNA-only 대조를 Figure 1E에 잘못 귀속 | FAIL: 원실험의 Sanger/clone 확인 누락. 기전은 정확 |
| DESeq2 | FAIL: Table S3/외부 재현 환경의 미확인 누락 | FAIL: 같은 Q6 누락 |
| 실물 UR5 | FAIL: 관절별 한계 수치/payload 미확인 누락 | FAIL: 같은 Q6 누락과 return 정의 누락 |

FAIL에는 큰 허위 사실뿐 아니라 필수 조건/검증 방법 누락과 낮은 심각도의 근거 위치 결함이 포함된다. 모든 실패를 같은 심각도의 환각으로 합산하지 않았다. 여섯 질문의 내용이 충족되어도 다른 생성 필드의 잘못된 사실이나 출처는 별도 실패다.

최종 판정은 [final-verdicts.json](assets/gpt-6-luna/primary-16k/reviews/final-verdicts.json), [바이오/리뷰 전수 대조](assets/gpt-6-luna/primary-16k/reviews/bio-review.md), [로보틱스/이론 전수 대조](assets/gpt-6-luna/primary-16k/reviews/robotics-theory-review.md)를 따른다. 원문 기준은 [기존 6편 근거표](2026-09-22-v1.0.1-paper-evidence.md)를 그대로 사용했다.

## 개선과 퇴보를 확인할 실제 사례

### Diffusion Policy: 6에서 해소된 사실/귀속 오류

5.6의 `key_results`는 “시뮬레이션에서는 4개 benchmark의 15개 작업”이라고 쓰고, 실물 Push-T의 95%/IoU 0.80을 end-to-end Transformer에 귀속했다. 6은 전체 평가와 시뮬레이션 표의 46.9% 상대 개선을 분리하고, 95%/0.80을 end-to-end 시각 인코더 결과로 기술한다. 원문 Table 6의 Transformer T-E2E는 65%/0.53이며 CNN E2E가 95%/0.80이다. 회전 성분은 그대로 두는 정규화 예외도 5.6의 일반화된 진술과 구분했다.

근거: [5.6 원응답](assets/gpt-6-luna/primary-16k/robotics2-gpt-5.6-luna-deep_dive-r0.result.json), [6 원응답](assets/gpt-6-luna/primary-16k/robotics2-gpt-6-luna-deep_dive-r0.result.json), [원본 PDF 9쪽 이미지](assets/gpt-6-luna/qa/gui/reference-dp-page-9.png), 원문 §5.3/Appendix B.2와 A.1. **이 개선에도 두 응답 모두 필수 Q6의 실물 T블록 질량/접촉 마찰계수 미확인을 빠뜨려 논문 전체 PASS는 아니다.**

### Bell과 UR5: 6에 새로 남은 설명 누락

Bell의 5.6은 상관식의 측정 방향이 단위벡터임을 명시한다. 6은 올바른 상관식과 부등식을 쓰면서 이 성립 조건을 누락했다. 수식 자체의 부호/수치 오류로 과장하지 않았다. 독립 검산에서는 단위벡터 a,c를 직교하게, b=(a+c)/√2로 두면 식 (15)의 좌변 0.292893218813453, 우변 0.707106781186547이 되어 요구되는 부등식이 위반된다. 8개 국소 결정론 ±1 배정은 모두 해당 부등식을 만족한다. 이는 수학 검산이며 실험 측정값이 아니다.

근거: [5.6 Bell](assets/gpt-6-luna/primary-16k/theory-gpt-5.6-luna-deep_dive-r0.result.json), [6 Bell](assets/gpt-6-luna/primary-16k/theory-gpt-6-luna-deep_dive-r0.result.json), [원본 식](assets/gpt-6-luna/qa/gui/reference-bell-page-2.png), R2 보고서의 재현 명령.

UR5의 6은 단계 보상과 return을 구분하지 않은 채 Figure 5를 평균 보상이라고 반복 설명했다. 5.6은 average return을 명시한다. 원문 II는 단계 보상 R_t와 할인 누적 return G_t를 구분하고 V/Figure 5의 지표는 Average Returns다. 이 결함은 지표 정의 누락이며, 모델이 실제로 다른 집계 계산을 수행하거나 숫자를 발명했다는 증거는 아니다. 두 응답 모두 관절별 한계 수치와 payload의 미확인은 빠뜨렸다.

근거: [5.6 UR5](assets/gpt-6-luna/primary-16k/robotics1-gpt-5.6-luna-deep_dive-r0.result.json), [6 UR5](assets/gpt-6-luna/primary-16k/robotics1-gpt-6-luna-deep_dive-r0.result.json), 원문 PDF 2쪽 II와 5쪽 V/Figure 5.

### 바이오와 리뷰: 맞는 핵심 수치만으로 통과시키지 않음

bio1의 두 응답은 6–8% NHEJ 변이율과 형질도입 효율을 구분했다. 그러나 5.6은 sgRNA-only 대조를 잘못된 Figure 1E에 연결하고, 6은 원실험의 Sanger/clone 검증을 빠뜨렸다. 새 적용 대상에서 서열 확인을 권하는 문장을 이미 수행한 검증의 설명으로 세지 않았다.

DESeq2의 두 응답은 top-100 순위 겹침 21→81을 정확도 81%로 바꾸지 않았다. 둘 다 비교 도구의 버전이 외부 Table S3에 있고 DESeq2paper 재현 패키지가 제공되지 않아 완전한 실행환경을 확인하지 못했다는 기존 Q6를 누락했다.

리뷰의 두 응답은 후반 Discussion/Appendix의 내용과 308/242/2017-02-01 범위를 실질적으로 반영했다. 6은 본문과 부록의 PubMed 검색 범위 불일치를 더 정확히 설명했지만, 정확한 308편 수치를 지지하는 §5 Overview 대신 §1/Appendix/Figure 1만 연결한 낮은 수준의 위치 결함이 남았다. 5.6은 유방의 데이터 부족 진술을 복부에도 저자 진술로 확장했다.

## 모든 최초 실행의 사용량

입력은 원본 PDF 전체이며 아래 모든 응답은 `completed`, strict 형식 유효, Standard tier, 비용 상태 `reported_usage`다. 출력에는 reasoning이 이미 포함되어 있으므로 다시 더하지 않았다. 반복 실행은 0회다.

| 논문 | 모델 | 입력 | 캐시 읽기 | 캐시 쓰기 | 출력 | reasoning | USD | 초 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Bell | gpt-5.6-luna | 21,176 | 0 | 21,173 | 9,074 | 3,311 | 0.01618265 | 121.554 |
| Bell | gpt-6-luna | 21,176 | 0 | 21,173 | 6,917 | 2,105 | 0.00610542 | 66.322 |
| Diffusion Policy | gpt-5.6-luna | 63,485 | 0 | 63,482 | 10,287 | 2,201 | 0.02821550 | 139.157 |
| Diffusion Policy | gpt-6-luna | 63,485 | 0 | 63,482 | 10,586 | 2,864 | 0.01322855 | 100.262 |
| 의료영상 리뷰 | gpt-5.6-luna | 68,260 | 0 | 68,257 | 10,662 | 2,897 | 0.02985925 | 142.714 |
| 의료영상 리뷰 | gpt-6-luna | 68,260 | 0 | 68,257 | 9,489 | 2,889 | 0.01327692 | 55.818 |
| Jinek 인간 세포 편집 | gpt-5.6-luna | 22,977 | 0 | 22,974 | 10,706 | 3,210 | 0.01859130 | 139.519 |
| Jinek 인간 세포 편집 | gpt-6-luna | 22,977 | 0 | 22,974 | 7,840 | 2,574 | 0.00679205 | 46.233 |
| DESeq2 | gpt-5.6-luna | 50,012 | 0 | 50,009 | 9,475 | 2,422 | 0.02387285 | 119.587 |
| DESeq2 | gpt-6-luna | 50,012 | 0 | 50,009 | 10,646 | 3,457 | 0.01157442 | 65.984 |
| 실물 UR5 | gpt-5.6-luna | 23,763 | 0 | 23,760 | 9,918 | 2,070 | 0.01784220 | 124.989 |
| 실물 UR5 | gpt-6-luna | 23,763 | 0 | 23,760 | 9,302 | 1,778 | 0.00762130 | 63.593 |

## 예산과 대표 역할의 실제 검증

| 항목 | 실행 수 | USD |
|---|---:|---:|
| 기존 검증 누적 | 22 | 0.35688680 |
| 새 PDF 비교 | 12 | 0.19316241 |
| 실제 core-chain | 3 | 0.03528540 |
| 그림 설명/채팅 | 2 | 0.00394672 |
| 누적 | 39 | **0.58928133** |
| US$1 중 잔액 | — | **0.41071867** |

[독립 집계 감사](assets/gpt-6-luna/qa/report-audit.md)는 원응답 사용량으로 비용/시간을 재계산하고 12개 CSV 행, 실패 판정과 모든 고유 실행을 대조해 통과했다.

미정산 요청은 0건이다. 생성은 root 한 담당자가 직렬로 실행했고 SDK/어댑터/형식 복구의 자동 재시도를 끈 단일 시도였다. 원장은 요청 직전 예약 후 사용량으로 정산하며 기존 비용을 초기화하지 않았다. [최종 예산](assets/gpt-6-luna/qa/budget-final.json), [primary 원장](assets/gpt-6-luna/primary-16k/ledger.jsonl), [core 원장](assets/gpt-6-luna/qa/core-chain/ledger.jsonl), [role 원장](assets/gpt-6-luna/qa/role-smoke/ledger.jsonl)을 보존했다.

금액은 보고된 사용량과 앱 단가의 추정치이며 공급자 청구서 검증값은 아니다. [공식 가격](https://developers.openai.com/api/docs/models/gpt-6-luna)을 재확인했고 지역 가산 없는 기본 엔드포인트를 사용했다. Token-count API 17개 dry-run 요청과 생성 직전 재계산을 사용했으며 공개 문서에서 별도 count 요금 항목을 찾지 못했다. 별도 청구 여부를 공급자 청구서와 대조한 것은 아니다.

실제 `visual → recipe → deep_dive` 3단계의 응답 ID 연결, 그림 설명, 채팅 스트리밍은 모두 완료되고 사용량이 보존됐다. 단, **대표 역할의 내용도 깨끗하지 않았다.** Figure 1 설명은 관측/행동 흐름 방향, Energy 도식의 o/a 축, ∇E(a) 표기를 잘못 읽었다. 채팅은 방법/한계를 대체로 설명하지만 46.9%의 정확한 시뮬레이션 집계 범위를 생략했다. [실제 역할 검토](assets/gpt-6-luna/qa/role-content-review.md)에 원문과 문구를 연결했다.

core-chain은 원본 PDF를 직접 사용했다. role-smoke는 기존 제품 handler의 입력을 그대로 따랐으므로 그림에는 원본 페이지 PNG와 텍스트, 채팅에는 축약 텍스트가 들어갔다. 그림/표 미리보기는 캡션으로 원본 PDF 전체 페이지를 연결한 QA 자료이며 실제 추출 파이프라인의 crop 품질 검증이 아니다. QA 복제 DB에서 준비된 캐시를 사용하고 표 markdown preview를 제거했으므로 표 미리보기 생성/추출 성공도 검증 범위에 포함하지 않는다. chat의 기존 분석 snippets는 격리되어 비어 있다. role 기록의 PDF 해시는 원문 출처이며 PDF 직접 첨부의 증거가 아니다.

## 구현과 자동 검증

- Task 0에서 현재 dirty 코드/기존 증거 파일 802개와 diff를 임시 백업에 보존하고 원본 PDF 6개 해시를 재검사했다. 이후 소유권 확장 파일 2개를 추가 백업했다. A~D는 배타적 파일 소유권으로 작업했고 root가 통합과 유료 실행을 관리했다.
- OpenAI 첫 요청/캐시 재시작/공급사 분리 경로에 원본 PDF를 연결했다. 파일 크기/형식/공급사 URI를 거절하고 PDF 해시, 입력 방식과 출력 상한으로 캐시를 구분한다.
- 후보 모델과 캐시 읽기/쓰기, 장문 요율, 시도별 비용을 추가했다. reasoning 이중 합산을 막고 사용량 불명은 0원 성공으로 바꾸지 않는다.
- 불완전/실패 응답을 정상 파싱하거나 그림 설명 캐시에 저장하는 경로를 실패 회귀검사로 고쳤다. 상위 parser 비용이 있으면 보존하고, 키가 없을 때의 기존 계산과 명시적 NULL을 구분한다.
- 부분 입력/원본 PDF 제공/과거 결과/잘못된 입력 메타데이터를 구분하며 내보내기에도 범위를 표시한다. 원본 제공은 판독 정확성의 보증이 아니다.
- 최종 백엔드: **1,063 tests + 223 subtests**, `py_compile` 통과. [검증 기록](assets/gpt-6-luna/qa/backend/validation-final-summary.json). 초기 전체 검사의 1실패/1,055통과와 미완료 응답의 red 회귀 기록을 그대로 보존했다. US$0.006/0.123 기대값을 낮추지 않고 누락된 상위 비용/권위 있는 상위 비용의 서로 다른 계약으로 분리했다.
- 최종 r6 조판 수정 후 프런트엔드: **299 tests**, 타입/린트/빌드 통과. [최종 검사 기록](assets/gpt-6-luna/qa/frontend/typography-r6/results.json)에 검사 전후 소스와 빌드 해시를 연결했다. `basedpyright` LSP는 사용할 수 없어 통과로 보고하지 않는다.

## GUI와 과학 검증의 경계

실제 Electron 개발 앱을 격리된 OS 임시 DB로 실행했다. 1400×900과 1024×680에서 실제 DP/Bell 생성 응답을 주입해 표시했다. 이 응답을 GUI에서 새로 생성한 것으로 표시하지 않는다. partial/unknown/error 상태 일부는 명시적 합성 자료이며 원논문 결과가 아니다. 실제 malformed 생성 실패는 이번 17회에서 발생하지 않았다. GUI 비용표의 US$0.04는 격리 DB의 실제/과거 사용량 합계이며 전체 비교 원장이 아니다. 표시된 phase 7건에는 비용/사용량 0인 합성 상태도 포함되므로 실제 생성 횟수로 해석하지 않는다.

최종 r6 기술 캡처: 32개 상태, 91개 검사 통과, 조회/탭 이동의 생성 요청 0회, 예기치 않은 콘솔/페이지 오류 0건. 저장하지 않은 종합 결과의 예상된 404 console 16건은 별도 기록한다. 캡처 준비 판정이 너무 빨라 PDF/그림 로딩 화면을 찍은 실패와 이후 실제 잉크/이미지/스크롤 안정화 검사도 남겼다.

**검증된 r6 GUI 판정: 기능/구조 PASS, 엄격 CJK REVISE. 현재 후속 편집본은 미재검증.** [최종 r6 manifest](assets/gpt-6-luna/qa/gui/final-capture-manifest.json)는 정확한 실제 콘텐츠 크기와 PNG 32장을 고정한다. 첫 r5의 창 높이 865px 불일치는 실패 기록으로 보존하고, 1400×900/1024×680을 만족한 새 실행으로 대체했다.

최종 r6는 잠금이 해제된 macOS에서 실제 Electron 창을 OS-native 방식으로 캡처했다. 제목 표시줄과 설정 사이드바까지 현재 빌드로 확인했고 PNG/DOM/스타일 보정은 하지 않았다. 이전 r5의 잠금 화면/renderer 제한, 잘못된 첫 창 크기, CJK 수정 요구도 역사적 기록으로 보존한다. r6는 과학적 문구를 바꾸지 않고 보조 표현과 구두점을 같은 줄바꿈 그룹에 넣었으며, 사전 20개 변형에서 동일 textContent와 넘침 없음을 확인했다. 최종 판정은 변경된 페이지와 상호작용 범위이며 앱 전체/패키지/추출 파이프라인 검증은 아니다.

[독립 구조 검토](assets/gpt-6-luna/qa/gui/visual-integrity-r6.md)는 차단 사항 없이 PASS다. [독립 CJK 검토](assets/gpt-6-luna/qa/gui/visual-cjk-r6.md)는 32장 중 27장 PASS, 5장 REVISE다. 1400 폭의 기본/부분/미확인 요약 4장에서 `맞춰야 / 한다.`, 과거 결과 1장에서 `해결하려 / 한다.`가 분리된다. 글자 손실이나 의미 변경은 없지만 적용한 엄격한 보조 표현 줄바꿈 기준에는 미달한다. 이전 r5에도 같은 분리가 있어 r6 회귀라는 증거는 없다. 요청한 남은 실패로 보존하며 전체 시각 통과로 바꾸지 않았다. [최종 시각 판정](assets/gpt-6-luna/qa/gui/final-visual-verdict.json)에 좌표/프레임/해시/검증 한계를 연결했다.

원래 [비교 시점 소스 316개](assets/gpt-6-luna/qa/candidate-source-hashes.json)를 보존했다. [최종 소스 기록](assets/gpt-6-luna/qa/final-source-hashes-r6.json)과 대조한 r6 검증 시점의 변경은 조판 관련 프런트엔드 6개 파일뿐이었다. 이후 별도 프런트엔드 편집이 발생했으며, 이 후속 편집본에는 이전 GUI/프런트엔드 통과 판정을 적용하지 않는다. backend/model input은 후속 확인에서도 고정됐다. GUI는 별도 최신 소스/빌드 manifest로 묶는다. 기록된 비교 시점 해시를 최종 GUI 해시로 고쳐 쓰지 않는다.

## 판정 과정의 정정과 한계

R1/R2는 모델/비용을 숨긴 응답을 원문과 대조했고 Bell 표현 문제와 낮은 심각도의 출처/용어 문제를 교차 검토했다. Bell에서 이론적 범위를 설명한 문장을 `weaknesses` 필드에 있다는 이유만으로 과학적 오류로 세지 않았으며 실제 단위벡터 누락은 유지했다. [공개 전 조정](assets/gpt-6-luna/primary-16k/reviews/adjudication.md)과 최초 판정을 보존한다.

초기 공개 집계는 5.6 2/6, 6 1/6이었다. 이후 root가 DESeq2와 로보틱스의 Q6 누락 판정이 일관되지 않음을 발견했다. 모델명을 계속 보지 않은 두 검토자가 지정된 미확인 항목을 다른 unknown으로 대체할 수 없다고 재확인하여 **최종 1/6, 0/6**으로 정정했다. 이는 기존 기준을 바꾼 것이 아니라 일부 분야에서 빠진 기준을 되돌린 감사이며, root의 모델 공개 후 요청되었다는 시점을 숨기지 않는다. [최종 판정 파일](assets/gpt-6-luna/primary-16k/reviews/final-verdicts.json)은 최초 공개 파일을 대체하되 삭제하지 않는다.

기존 A(5.6 텍스트)는 재실행하지 않았다. [이전 기록](2026-09-22-v1.0.1-summary-reading.md)은 Bio1/Bio2 통과, Bell 수식 입력 손실, 리뷰 후반 절단, DP 오류를 기록했다. 새 PDF 입력은 수식과 후반 범위를 실제로 제공했지만 바이오의 새 응답에는 별도 누락/출처 문제가 생겼다. A→C 차이는 입력과 모델이 함께 바뀌므로 모델만의 개선으로 계산하지 않는다.

16,000 상한에서 출력 불완전은 없었다. 남은 문제는 내용/범위/출처의 누락과 오독이므로 24k/32k 확대나 반복 prompt 수정을 하지 않았다. 속도만으로 승격을 주장하지 않아 역순 반복도 수행하지 않았다. 단회 6편 표본을 전체 모델 품질의 순위로 일반화하지 않는다.

정확성 게이트가 실패했으므로 MODEL_LUNA와 사용자 공급사 설정을 유지하고 1.0.1 버전 동기화/macOS 패키지를 진행하지 않았다. Windows, 공개 릴리스, 커밋/태그/push는 실행하지 않았다. 실제 full-run의 추가 그림 생성 등은 실행하지 않았으며 full-run/provider/cache 배선은 자동 통합 검사, 실제 생성은 core-chain/대표 역할 범위다.

## 재현 경로

모델 재호출 없이 전체 CSV, 원장, raw 응답, 검토 보고서와 원본 해시를 대조할 수 있다. `sasoo/backend`에서 `./.venv/bin/python tools/luna_compare.py --mode report --campaign ../../docs/validation/assets/gpt-6-luna/primary-16k`는 저장 자료를 새 timestamp 보고서로 내보낸다. 유료 재실행은 동일한 누적 원장과 source/request fingerprint 검사를 통과해야 하며 완료/미정산 요청을 자동 재발행하지 않는다.

핵심 교훈은 원문이 들어간 사실, JSON이 완성된 사실, 내용이 정확한 사실을 서로 다른 증거로 확인하는 것이다. 비용/속도 비교는 같은 입력과 조건으로 고정하고, 모든 기준을 같은 방식으로 적용해야 한다. 이번에는 예산 예약, 원응답 보존, 원문 교차 검토가 빠른 모델의 실제 이점과 남은 실패를 함께 드러냈다.
