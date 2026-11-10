# Flow Matching 새 유료 비교 결과

Flow Matching의 초기 버전과 수정 버전을 새로 실행하고 독립 원문 검토를 마쳤다. 결과는 **실패 및 일부 미완성**이다. 두 버전의 일부 핵심 설명은 원문과 맞지만 전체 통과 기준을 만족하지 않는다. 나머지 두 논문의 유료 평가는 시작하지 않았다.

실행일은 2026-10-14이며 후속 로컬 검증은 2026-10-15까지 진행했다. 기준 manifest와 발행한 원본 요청, 응답, 데이터베이스는 보존했다. 유료 실행 이후의 로컬 수정은 이번 공급자 품질 결과에 포함하지 않는다.

## 실행과 비용

승인 범위는 Flow Matching 1편의 초기/수정 버전 각 1회, 총 최대 42건, $18이다. 두 버전의 모델, effort, 분석 항목, 시각화 목록과 출력 상한은 고정했다. 시각화는 이미지 5개, Mermaid 3개, HTML 1개다.

| 항목 | 초기 버전 | 수정 버전 |
|---|---:|---:|
| 실제 공급자 요청 수 | 21 | 14 |
| 사용량 기준 계산 비용 | $0.19563418 | $0.09094878 |
| 완성된 이미지 | 5/5 | 1/5 |
| 생성된 Mermaid | 3/3 | 3/3 |
| 완성된 HTML | 1/1 | 0/1 |

합계 35건, $0.28658296다. 공급자가 보고한 사용량을 [공식 가격표](https://developers.openai.com/api/docs/pricing)에 대입한 값이며 청구서 대조는 하지 않았다. 발행한 35건은 모두 원장에서 정산됐다. 중단 이후 새 발행은 0건, 중복 발행도 0건이다.

수정 버전의 HTML 요청은 `max_output_tokens=8000`에 도달해 `incomplete`로 끝났다. 텍스트는 JavaScript 함수 중간에서 잘렸고 문법 검사에 실패했다. 실행기가 중단을 기록했으며 이후 이미지 2–5의 발행을 차단했다. 재시도하지 않았다. 초기 버전은 전체 441.10초에 완료했으나 수정 버전은 작업량을 완수하지 않았으므로 속도와 비용 개선율을 계산하지 않는다.

- manifest SHA256: `2015f8015d992e514a2d1571b79d0b0ec54ad1bbb17449dd898c05b3180874c5`
- 초기 run ID: `campaign-flow-baseline-7f85c10799fa490a993992390a9ded5c`
- 수정 run ID: `campaign-flow-candidate-74abf3caa6314c60abb98bf0d9fed188`
- 잘린 HTML response ID: `resp_0aedec6fb1ec03b7016acee277e44c87d0ba03615dbbe7ac8f`

실행 증거: [사용량 및 중단 요약](assets/quality-live-20261014-flow/paid-run-summary.json), [append-only 원장](assets/quality-live-20261014-flow/campaign/ledger.jsonl), [승인 기록](assets/quality-live-20261014-flow/user-approval.json).

비용 기록의 한계: 평가 실행기의 중단 예외 때문에 수정 버전의 앱 DB에는 비용 불명 요청 기록 5개가 남았다. 이 중 4개는 공급자 발행 전에 차단된 이미지 시도이며 1개는 원장에서 비용이 확인된 미완성 HTML이다. 이는 실제 공급자 비용 불명 5건을 뜻하지 않는다. 앱 DB를 수정하지 않았고 이번 계산은 공급자 응답과 평가 원장을 사용했다. 다음 실행기에서는 이미 정산한 미완성 응답을 앱에 전달하면서 추가 발행을 차단하고, 발행 전 차단과 비용 불명을 구별해야 한다.

## 독립 원문 검토

검토자에게 실행 방식, 모델, 비용, 시간과 버전 매핑을 가리고 원본 PDF, 기준과 익명 결과만 제공했다. 검토 후 매핑은 `sample-53a5323724=초기`, `sample-05fd56e110=수정`이다. [독립 보고서](assets/quality-live-20261014-flow/review-materials/independent-review.md)에는 모든 발견 위치와 JSON 경로가 있다.

| 확인 대상 | 실제 결과 | 원문 기준과 판정 |
|---|---|---|
| Table 1 수치 전달 | 초기 이미지의 CIFAR-10 15개 값이 대시로 바뀜. 수정 이미지는 미생성 | PDF 8쪽의 숫자를 보존하지 못함. 수정 효과 미확인 |
| density/flow map/field 구별 | 두 synthesis의 선택된 식과 gradient Mermaid는 구별함 | 확인한 범위 통과. 이미지 전체 품질 통과를 뜻하지 않음 |
| 시간 sampling | 두 recipe의 `t ~ U[0,1]`와 OT target는 맞음 | 해당 조건 통과 |
| 픽셀 좌표 변환과 BPD | 수정 recipe에 `2^-7 x - 1`과 `-7d ln2`가 있으나 BPD `+7`이 없음 | PDF 17쪽의 필수 재현 조건 일부 누락. 실패 |
| Table 4 해석 | 수정 visual 분석은 FM OT 우세가 모든 항목에서 일관되지 않다고 서술 | PDF 21쪽의 같은 데이터셋/같은 K인 9개 열 모두 FM OT의 NLL이 최저. 중요 오류 |
| 참고문헌 | 두 결과가 부록 문장까지 포함해 총 246개로 분석 | PDF 10–13쪽의 실제 서지 항목은 52개. 중요 오류 |
| HTML 생성 | 초기 완성, 수정 8,000 토큰 상한에서 잘림 | 수정 생성 실패. 보이는 일부 식이 맞아도 실행 성공으로 세지 않음 |

두 결과의 자기 인용 0도 공동저자 중복을 세는 정의와 맞는지 별도 확인이 필요하다. 이번 보고서는 그 값을 확정된 정답으로 취급하지 않는다.

원문 위치 정정: Eq.21은 실제 PDF 5쪽이다. 고정 기준의 페이지 목록에서 5쪽이 빠진 오류는 [별도 정정 기록](assets/quality-live-20261014-flow/criterion-page-erratum.json)에 남겼다. 발행한 manifest와 기대 식/숫자는 바꾸지 않았다.

## 유료 중단 후 로컬 수정과 검증

유료 실행에 사용한 소스와 현재 수정 소스를 구분했다. [후속 수정 patch](assets/quality-live-20261014-flow/offline-fixes.patch)는 승인 당시 수정 버전 archive와 비교한 변경만 담고, [파일 해시](assets/quality-live-20261014-flow/offline-fix-hashes.json)를 별도로 기록했다.

- `section_splitter.py`: 실제 참고문헌 제목부터 범위를 잡고 부록과 페이지 표식을 제외한다. 보존된 Flow Matching 추출 원문에서 실제 서지 항목 52개가 파싱되는 회귀 검사를 추가했다. 번호가 붙은 참고문헌이 앞 섹션과 이어지는 기존 사례도 통과한다.
- `document_context.py`: 기존 sidecar를 재사용해도 참고문헌 입력만 다시 분리한다. 공급자 호출이나 기존 결과 수정 없이 새 citation 입력 해시가 수정된 내용을 반영한다. 인용 횟수와 LLM 의존도 분석 전체의 개선은 아직 새 결과로 확인하지 않았다.
- `HtmlVisualization.tsx`: min만 있는 숫자 입력도 현재값과 다른 유효값을 검사한다. 종전에는 sigma에서 invalid 값 0만 시험해 정상 코드에 무반응 경고를 냈다. 모바일 grid의 최소 너비도 조정했다.
- `analysis_execution.py`: 같은 8,000 토큰 상한에서 HTML을 간결하게 작성하도록 지시하고 HTML 시각화 캐시의 prompt 버전을 바꿨다. recipe에는 좌표와 변환 방향, 보정식의 부호, 차원과 상수항까지 적도록 지시했다. 이 두 프롬프트의 실제 개선 효과는 미검증이다.

완성된 초기 HTML은 생성된 코드를 바꾸지 않고 raw/app/export 세 경로로 실제 Chromium에서 실행했다. 원문 Eq.21/22/23으로 독립 계산한 기본값, `t=0/1`, 1차원/3차원 벡터 총 15개 수치 사례가 통과했다. 최대 절대 오차는 약 `4.55e-9`로 허용치 `5e-7` 이하다. 빈 값, 공백, 차원 불일치, 빈 벡터 성분, 무한대 성분과 음수 sigma 등 33개 invalid 조작에서 계산 결과를 지우고 그래프를 숨겼다. 1024px/390px에서 가로 넘침, runtime error, 외부 요청이 없었다. [실행 기록](assets/quality-live-20261014-flow/html-execution-regression-v2.json), [390px 화면](assets/quality-live-20261014-flow/completed-html-v2-app-390.png).

독립 검토자는 추가 공백/음수 sigma 사례를 넣기 전의 15개 수치/27개 invalid 기록을 대조했다. 원본 코드 실행 성공과 로컬 검사기 수정 후 app/export 검사 성공을 구분했다. 수정 버전 partial HTML은 계속 실패로 남겼다.

정상 상수 출력, 선택 입력 기본값, canvas, vector, select와 잘못된 기본값/무반응 경고를 포함한 fixture 10개를 app/export 20경로로 확인했다. 정상 사례는 통과하고 의도된 실패 사례 2종은 오류로 잡았다. [fixture 기록](assets/quality-live-20261014-flow/fixture-html-regression.json).

검증 결과:

- Backend 전체 및 실행기: 1,214 tests, 268 subtests 통과. 이후 recipe 지시 보강과 참고문헌 fallback 정리 후 관련 61 tests, 18 subtests 추가 통과.
- Frontend: 369 tests(45 files), TypeScript, lint, build 통과.
- 실제 잘린 HTML 응답을 모의 공급자 응답으로 사용해 미완성 코드가 거부되고 알려진 비용이 유지되는지 확인했다. 추가 유료 호출은 없었다.
- 기존 증거 216개 파일과 두 승인 소스 archive의 해시가 모두 유지됐다. [보존 검사](assets/quality-live-20261014-flow/preservation-verification-final.json).

브라우저 검사는 실제 생성 HTML의 sandbox와 export 실행을 확인한다. 설치된 Electron 앱이나 새 번들 backend 검증은 이번 범위에서 실행하지 않았다. 커밋, push, 릴리스도 하지 않았다.

## 다음 재평가 범위

다른 논문으로 확장하기 전에 수정한 후보의 중요 실패 항목에 집중한다. [다음 범위 초안](assets/quality-live-20261014-flow/focused-reevaluation-scope.json)은 recipe 1건, Table 4 visual 분석 1건, HTML 1건, Table 1 이미지 설명/렌더 2건으로 최대 5건, 예산 $2, 발행 전 예약 합계 $1.80을 정했다. 이 범위는 정확성 확인용이며 같은 전체 작업량의 시간/비용 비교가 아니다.

이 초안은 아직 실행 가능한 manifest나 새 호출 승인이 아니다. 다음 실행 전에 수정 소스와 standalone 입력을 새로 고정하고, 집중 실행기와 모의 검사를 끝낸 뒤 그 정확한 범위의 승인을 받아야 한다. 기존 35건의 재발행과 자동 재시도는 허용하지 않는다.

학습 메모: 생성 완료, 실제 실행, 원문 정확성을 별도로 판정해야 한다. 밀도를 평가하는 좌표가 달라지면 Jacobian 보정이 필요하며 이 논문에서는 BPD가 7만큼 달라질 수 있다. PDF 17쪽의 입력 변환과 BPD 식을 recipe에 각각 대조하는 것이 재현 가능한 확인 방법이다. 이미지 다른 곳에 맞는 식이 있어도 recipe 자체의 누락을 해결한 것으로 세면 안 된다.
