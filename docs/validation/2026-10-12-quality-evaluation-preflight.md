# 유료 품질 비교 전 검증

2026-10-12. 우선순위 1–4의 코드 리뷰, 회귀 확대, 실제 항목과 원문 정답 기준 고정, 실행기 구현과 모의 실행을 완료했다. 새 공급자 호출은 0건, 추가 공급자 비용은 $0이다. 새 결과의 생성 품질, 설치 앱, 공급자 청구서는 미검증이다.

최종 계획은 `assets/quality-preflight-20261012/comparison-plan-ready.json`이다. 이전 제안이나 중간 manifest를 실행하지 않는다. `quality_compare.py`는 이 파일, 소스 아카이브의 모든 파일, 입력 복사본, 실행기 자신의 해시를 발행 전에 확인한다. 계획에는 승인이 없으며 `awaiting_explicit_paid_approval` 상태다.

## 최종 리뷰와 수정

| 발견 | 수정과 판정 | 근거 |
|---|---|---|
| 이어지는 표와 긴 식을 잃음 | 참조 구간을 먼저 선택하고 이어지는 표 행과 정의를 보존한다. 식이나 행을 문자 수로 자르지 않으며, 필요한 구간이 상한을 넘거나 찾지 못하면 명시적으로 미확인 상태를 반환한다. | `test_quality_preflight.py`, `document_context.py` |
| 다른 표의 행을 요청한 표의 근거로 인정 | 캡션과 그 표에 연결된 행을 함께 검사한다. 다른 표가 있는 페이지는 근거를 대신하지 못한다. | 표 1 누락/표 2 존재 반례 |
| 추출본을 원문으로 오인 | 페이지 레이블과 텍스트 전사의 정확성을 미검증으로 표시한다. 리뷰 PDF의 추출본은 식 (3)의 음수 부호와 적분을 잃었고, Flow Matching 추출본의 식 (21) 페이지 위치도 실제 PDF와 다르다. 독립 그림 설명과 HTML 요청은 기존 inline PDF 기능으로 원본을 함께 받는다. PDF 제공은 정확성 통과가 아니다. | 실제 PDF p.4/6/17, 리뷰 p.7, PDF payload 회귀 |
| recipe의 과도한 충돌 후보 | U-Net 정규화와 픽셀 전처리, sampling seed와 시간 분포를 구별한다. critical_notes의 미보고 주장도 검토한다. 긴 식뿐 아니라 원문 설명을 보존한다. `source_conflict_candidate`는 검토 후보이며, 검색 실패와 부재는 계속 미검증이다. | 기존 A/B 회귀와 추가 반례 |
| 정상 HTML에 잘못된 경고 | `output for=`를 결과에서 제외하지 않는다. canvas는 픽셀 변화를 검사한다. 상수 출력의 선언과 선택 기본값을 검사하며, 기본값과 다른 값을 사용하는 코드는 실패한다. | `html-regression.json` |
| text/vector/select가 검사에서 빠짐 | 빈 값, vector 빈 성분과 차원 불일치, select와 기본값을 점검한다. 한 숫자가 무효인 동안 다른 숫자를 바꿔도 기존 결과와 그래프가 복구되지 않게 한다. | 실제 Chromium과 export, 정상/실패 fixture 18개 |

원문 선택은 검색과 전달 기능이다. PDF 자체가 손상됐거나, 수식 해석이 틀렸거나, 그림 렌더가 숫자를 바꾼 경우까지 결정론적으로 증명하지 않는다. HTML의 자동 입력 검사는 숫자/range/text/textarea/select와 출력/SVG/canvas의 실행 범위다. 임의의 버튼 흐름, checkbox/radio, 선언한 상수 조건의 수학적 진실, 모든 수식의 동등성은 독립 원문 검토 대상이다.

## 논문별 고정 항목

각 버전은 논문당 이미지 5개, Mermaid 3개, HTML 1개를 생성한다. 모델이 만든 계획은 보존하되 실제 생성에는 아래 고정 목록을 사용한다. 동적인 계획의 차이가 작업량 차이를 만들지 않게 한다. 두 버전의 PDF, 기존 추출 자료, 행 데이터와 읽기 수준은 동일하다. 후보 버전의 새로운 근거 전달과 PDF 입력은 수정 효과이므로 입력 토큰 차이를 비용에 포함한다.

| 논문 | 이미지 5개 | Mermaid 3개 | HTML 1개와 독립 검산 |
|---|---|---|---|
| Flow Matching, 28쪽 | CNF/density/flow map, OT 학습 과정, CIFAR-10 Table 1, 고정 위치와 이동 위치 field, pixel/BPD 변환 | CFM 학습 sequence, gradient 동등성 조건, 재현 조건과 미확인 값 | OT 계산기. x0=[1,-2], x1=[3,4], t=0.5, sigma=0.1에서 psi=[2.05,0.9], 고정 field=[3.818181818,10.545454545], 이동 field=[2.1,5.8]. 상대 오차 한도 5e-7 |
| Uplink/LITEUP, 12쪽 | 측정 기하, lookback tomography, Table 1/2 설정, residual MSE의 의미, 입력 불확실성 | sensing/correction sequence, 가정과 실패 조건, simulation 비교 절차 | 프레임 이동 v/f와 비율 v/(fD). v=20 m/s, f=1000 Hz, D=0.7 m에서 0.02 m와 0.02857142857. v=700 m/s에서 비율 1, 상관 유지 조건을 만족하지 않음 |
| 광통신 리뷰, 41쪽 | link 과제, Figure 9 AO feedback, Table IV 투과율, 손실 기작, 완화 방법의 적용 범위 | AO sequence, 기작/완화 연결, 근거 유형과 recipe 적용 여부 | 균질 gamma를 별도로 가정한 T=exp(-gamma H/cos(theta)). gamma=0.1 km^-1, H=1 km, zenith theta=0에서 0.9048374180. theta=60도에서 0.8187307531, gamma=0 또는 H=0에서 1 |

HTML의 sigma=0.1 및 리뷰 계산기의 기본값은 설명용 입력이다. 저자의 실험값으로 제시하지 않는다. 단위, 범위와 적용 가정, 무효 입력에서 결과 숨김, 경계값, 선택 기본값과 의도된 상수 출력을 별도로 판정한다.

정답 기준은 manifest의 각 `criteria`에 실제 PDF 페이지로 연결했다. 주요 기준은 다음과 같다.

- Flow Matching p.8 Table 1: CIFAR-10 DDPM=3.12/7.48/274, Score Matching=3.16/19.94/242, ScoreFlow=3.09/20.78/428, FM Diffusion=3.10/8.06/183, FM OT=2.99/6.35/142. 열은 NLL(BPD)/FID/NFE다. p.3/4의 균등 시간 sampling, p.6의 field/flow/target, p.17의 x/128−1, log-density의 −7d log 2, BPD +7을 보존한다. p.4/14의 gradient 동등성 조건을 확인한다. 실험 sigma_min, training seed, GPU 제품과 software version은 임의 보충하지 않는다.
- Uplink p.4 Table 1: 1550 nm, 2층, r0=100/100 mm, 높이 2500/5000 m, net r0=66 mm, theta0=1.1 arcsec, aperture 700/350 mm, WFS 10×10, 1 kHz. 500 nm 대응값과 구별한다. p.5의 500 timesteps와 저자가 보고한 81 simulations를 유지하되, 표의 명목상 Cartesian product는 144이므로 선택 절차는 미확인으로 남긴다. “up to 8.6 times less”는 residual phase MSE의 simulation 결과다. 실장 지연의 실현 가능성은 p.4에서 미조사로 남는다.
- 리뷰 p.7 Table IV: Changchun=0.15/0.25/0.43, Kunming=0.63/0.70/0.73, 파장=800/1060/1550 nm. 5 km visual range에서 인용된 MODTRAN 결과이며 실제 측정이나 link availability로 바꾸지 않는다. p.17/18의 aperture averaging 적용 한계, 배경 잡음과 AO feedback을 확인한다. 저자의 단일 학습 실험이나 training recipe를 만들지 않는다.

## 실행과 비용 계약

모델/effort와 출력 상한은 양쪽 버전에 강제한다.

| 단계 | 모델과 effort | max_output_tokens |
|---|---|---:|
| screening/citation/visual | gpt-6-luna, low | 32000 |
| recipe | gpt-6-luna, medium | 24000 |
| deep_dive | gpt-6-luna, xhigh | 16000 |
| synthesis/viz_planning | gpt-6-luna, medium | 32000 |
| 이미지 설명/HTML | gpt-6-luna, medium | 8000 |
| Mermaid | gpt-6-luna, high | 8000 |
| 이미지 렌더 | gpt-image-2.5-flare | 1536×1024 PNG. structure/additional은 medium, process/comparison은 high |

발행 순서는 Flow baseline→candidate, Uplink candidate→baseline, 리뷰 baseline→candidate다. 기존 병렬 순서를 유지한다. 이는 초기/수정 품질 비교이며 순차/병렬 인과 효과의 실험이 아니다. 공급자 캐시는 강제로 cold 상태로 만들 수 없으므로 보고된 cache usage를 보존한다.

원장은 `reserved → issued → settled/unsettled`를 fsync와 함께 append한다. 부모 캠페인 잠금과 별도 worker 잠금으로 동시 실행기를 차단하고, worker 안의 thread 잠금으로 병렬 예약을 직렬화한다. 같은 단계/항목의 두 번째 요청은 payload가 달라도 차단한다. 새 run ID, request ID, 요청/응답 파일을 사용하고 기존 파일을 덮어쓰지 않는다. SDK 재시도는 0이다.

발행 전 텍스트 $0.30, 이미지 $0.60을 예약한다. 실행당 요청 상한 21건, 예약/정산 한도 $9, 전체 상한 126건/$54다. 먼저 Flow 한 편의 두 버전만 승인하는 범위는 최대 42건/$18이다. 그 pair의 전부를 예약했을 때 $15.60이며 $18은 추가 발행 한도다. 현재 공급자 견적이나 청구서 금액으로 표현하지 않는다. 실제 공급자 요율을 확인한 뒤 이 manifest에 대응하는 명시적 승인 기록을 만들어야 한다.

timeout, usage 부재, 반환 모델 불일치, 이전 owner의 미정산, 소스/입력/모델/effort 불일치, 요청 수/예산 초과, 중복 발행과 고정 작업량 실패는 이후 발행을 막는다. 이미 발행된 요청은 환불이나 공급자 취소로 간주하지 않는다. 늦게 완료한 형제 요청의 사용량은 보존하지만, 중단 상태를 자동으로 해제하지 않는다. 중단된 실행을 자동 재생하는 기능은 없다.

Flow 결과에는 임의 레이블의 blind bundle과 검토 template을 만든다. 생성 성공, 브라우저 실행과 원문 정확성을 각각 판정하고, 원본 이미지/HTML도 검토한다. 시간/비용/모델/버전 metadata와 private mapping은 검토자에게 주지 않는다. 후보의 모든 중요 기준과 독립 실행 검토가 통과해야 후속 논문을 허용한다. 모의 실행의 검토 template은 실제 승인/품질 통과에 사용할 수 없다.

## 검증 증거와 재현

- 백엔드 전체: 1201개와 하위 검사 268개 통과. 기존 의존성과 datetime deprecation 경고 44개가 있었다.
- 새 실행기 단위 검사: 최종 20개 통과. 예산 경쟁, count cap, 중단 후 재시작, 비용 불명, 늦은 정산, 중복, 해시, 잠금, 모의/유료 원장 혼합과 blind metadata를 검사한다.
- 프런트엔드: 44개 파일/365개 테스트, TypeScript, lint, build 통과.
- 실제 Chromium/공유 export: 정상 numeric/output-for, 상수, 기본값, canvas, vector, select와 두 숫자 입력의 복구가 통과했다. 잘못된 기본값과 반응 없는 계산은 의도대로 failed였다. console/runtime 오류와 외부 요청은 0이다. HTML 검사 자체가 원문 정확성을 검증한 것은 아니다.
- 전체 모의 실행: 6회, Flow/Uplink 각각 버전당 21건, 리뷰 버전당 20건, 총 124건. 리뷰의 citation은 로컬 처리로 끝난다. 모든 요청은 `mode=simulation`이며 새 공급자 호출이 아니다. 옛 결과와 일부 공통 schema fixture를 반환하는 모의 공급자로, 특히 리뷰/정량 논문의 deep_dive는 Flow의 schema fixture를 사용한다. 내용 품질 판정에는 사용할 수 없다.
- 실제 요청 경계 fault: timeout과 usage 부재, 반환 모델 불일치는 모의 요청 1건 후 unsettled로 중단한다. 요청 모델 불일치는 발행 0건으로 중단한다. 별도 프로세스 재시작이 추가 발행을 만들지 않음을 확인했다.
- 기존 유료/오프라인 증거 216개 파일의 해시는 그대로다. 중간 모의 실행 실패와 manifest/아카이브도 남겼다. 현재 개발 환경은 Python 3.14이며 Python 3.12 패키지를 검증했다는 뜻이 아니다.

`contract-review.json`은 baseline/candidate AST에서 `run_full_analysis`, `_run_parallel`, `_render_image`, `_viz_cost_totals`와 공급자 client/가격 파일이 같음을 기록한다. 취소/병렬과 사용량 관련 전체 회귀가 통과했다. 시각화 캐시는 근거 선택 버전과 원본 PDF 해시에 한정해 바뀌었으며 전역 chain 버전을 올리지 않았다. 저장된 결과, raw recipe와 과거 원장은 수정하지 않았다.

```bash
./sasoo/backend/.venv/bin/python sasoo/backend/tools/quality_compare.py preflight docs/validation/assets/quality-preflight-20261012/comparison-plan-ready.json
./sasoo/backend/.venv/bin/python sasoo/backend/tools/quality_compare.py dry-run docs/validation/assets/quality-preflight-20261012/comparison-plan-ready.json --campaign /absolute/path/to/a/new/offline-campaign
```

`execute`는 정확한 manifest hash, 대상 논문, 호출 상한과 예산에 대한 명시적 승인 파일이 있어야 한다. 이번 작업은 이 승인을 만들거나 실행하지 않았다. 단계 5/6의 새 공급자 생성과 원문 대조, 단계 7의 Python 3.12 설치 앱 검증, 단계 8의 품질/시간/비용 정리 및 커밋/릴리스는 이후 작업으로 남는다.

학습 메모: 발행을 기다리는 상태와 이미 발행한 상태를 구별해야 timeout 뒤에도 돈과 결과의 소유권을 추적할 수 있다. 검증도 입력 전달, 생성, 실행, 원문 정확성을 별도로 판정해야 한다. 모의 실행과 fault 원장을 재현해 차단을 확인하고, 실제 품질은 동일 항목의 새 결과를 PDF와 대조한다. 테스트 통과나 토큰 정산을 과학적 정확성의 증거로 바꾸는 것이 가장 큰 함정이다.
