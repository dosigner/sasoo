# 양사 체인 실측: 토큰 소비, 수렴 조건, effort 사다리

- 날짜: 2026-08-29. 논문: paper 45 (Demonstration of 100 Gbps coherent FSO at LEO tracking rates, 실험 논문, optics).
- 모델: gemini-3.7-flash (Interactions API, previous_interaction_id 체인) vs gpt-5.6-luna (Responses API, previous_response_id 체인).
- 프롬프트, 스키마, 시스템 프롬프트(photon 페르소나 + 스테이지 오버레이 + undergrad 수준)는 프로덕션 `analysis_routes`에서 축자로 가져왔다. recipe 지시문은 소스에서 정규식 추출로 drift를 막았다.
- 총 지출 $0.3849 (호출 8건). 원장과 출력 전문: `RESEARCH/2026-08-29-chain-compare/`.
- **한계: 셀당 1회 실측이라 노이즈 바닥이 없다.** 하네스: `~/.claude/jobs/63a3bb36/tmp/chain_compare.py` (잡 삭제 시 소멸).

## 1. 체인 토큰·비용·지연

| 단계 | Gemini in→out (effort) | Luna in→out (effort) | 비용 g/l | 시간 g/l |
|---|---|---|---|---|
| visual (PDF 포함 첫 호출) | 7,678→877 (low) | 37,978→1,863 (low, reasoning 83) | $0.0090 / $0.0098 | 8.7s / 24.2s |
| recipe (체인, cap 24k) | 9,561→6,017 (medium) | 40,922→8,525 (medium, reasoning 303) | $0.0297 / $0.0184 | 17.3s / 66.1s |
| deep_dive (체인+digest) | 16,508→2,840 (high) | 50,316→8,734 (xhigh, reasoning 2,983) | $0.0230 / $0.0205 | 19.5s / 74.6s |
| **체인 합계** | **33,747→9,734** | **129,216→19,122** | **$0.0617 / $0.0487** | **45.5s / 164.9s** |

프로브 2건:

| 프로브 | in→out | 비용 | 시간 | 결과 |
|---|---|---|---|---|
| Gemini deep_dive **medium** | 16,508→**65,522** | **$0.2581** | 145.9s | **폭주, incomplete** |
| Luna deep_dive **high** | 50,316→5,267 (reasoning 780) | $0.0164 | 54.2s | 정상, xhigh와 필드 채움 동등 |

읽는 법 세 가지.

1. **같은 PDF가 Luna에서는 약 5배 비싼 입력이다** (37,978 vs 7,678 토큰). Responses API의 input_file 토큰화가 무겁고, 체인 각 턴이 전체 히스토리를 다시 과금한다(cached_tokens가 세 호출 모두 0으로 관측됨 — 프롬프트 캐시 미적중). 그런데도 입력 단가가 낮아($0.20/M) 체인 총비용은 Gemini와 비슷하거나 더 싸다.
2. **Gemini 체인의 입력 증가는 완만하다** (7.7k → 9.6k → 16.5k). 서버 상태 체인이 히스토리 재전송분을 압축해 준다.
3. **지연은 Gemini가 3.6배 빠르다** (45.5s vs 164.9s). UI 체감 지연이 중요하면 이 격차가 비용 차이보다 크다.

Gemini의 total_thought_tokens는 전 호출 0으로 보고됐다. thinking 사용량을 분리 관측할 수 없었고, 청구는 출력 합산이라 비용 수치는 유효하다.

## 2. 수렴 분석: 무엇이 일치하고 무엇이 발산하나

**일치(사실 층).** 두 모델이 같은 물리량을 뽑으면 값은 정확히 같다: wavelength 1550nm, beacon 532nm, actuation ±2mrad, 거리 500~700m, aperture 50mm, power 11.7dBm. visual의 개수도 완전 일치(그림 9, 표 3, 수식 0). 언어 규칙(한국어 본문, 원문 표기 유지)도 양쪽 다 준수했다. 즉 현행 시스템 프롬프트의 서비스 규칙 층은 이미 수렴을 만들고 있다.

**발산(구조·양 층).** 세 종류다.

| 발산 | 실측 | 원인 |
|---|---|---|
| 목록 개수 | findings 5 vs 15, 파라미터 35 vs 63, steps 9 vs 20, 약점 4 vs 13 | 개수 대역 지시가 없다. Luna는 망라형, Gemini는 선별형이 기본 성향 |
| 파라미터 이름 | 이름 교집합 8/90. `aperture` vs `aperture_diameter`(같은 값 50mm) | 명명 규약 미지정. Luna는 domain_hint 목록 표기를 따르고 Gemini는 축약 |
| 선택 필드 생략 | Gemini는 required 아닌 3필드(suggested_improvements 등)를 0개로 생략, equipment 0개. Luna는 전부 채움 | 스키마 required만이 강제력을 가진다 |

**프롬프트 지시와 스키마 계약의 준수율 차이가 핵심 관찰이다.** 스키마가 강제한 것은 양쪽 다 지켰다(required 필드 채움 100%, evidence_quote 첨부 g 35/35, l 62/63). 프롬프트 문구로만 지시한 것은 Gemini가 자주 무시했다: "강점·약점에 논문 위치를 적어"는 Luna만 준수, "to_be 1~2문장"은 Gemini가 1,651자로 위반. 수렴은 시스템 프롬프트 문구를 늘려서가 아니라 스키마를 조여서 온다.

## 3. 시스템 프롬프트(와 계약) 처방

우선순위 순서다. 1~2가 효과 대부분을 만든다.

1. **수렴시키려는 필드는 required로 승격하라.** 프롬프트 지시는 provider별 준수율이 갈리지만 required는 양쪽 다 지켰다. 예: 근거 위치가 필요하면 "위치를 적어" 대신 strengths 항목을 `{text, location}` 객체로 만들거나, 최소한 required에 넣는다.
2. **목록형 필드에 개수 대역을 지시문에 명시하라.** "key_findings 5~10개", "strengths·weaknesses 각 3~6개", "steps 8~15단계". 개수 대역이 없으면 Luna는 15개, Gemini는 5개를 내는 것이 실측된 기본 성향이다.
3. **recipe 파라미터 명명 규약을 한 줄 추가하라.** "name은 DOMAIN-SPECIFIC 목록에 있는 표기를 그대로 쓰고, 목록에 없으면 축약 없는 snake_case 전체 명칭을 써." 이름 교집합 8/90은 이 한 줄의 부재가 만든 결과다. 이름이 갈리면 provider를 바꿀 때 비교·회귀 측정이 전부 깨진다.
4. **분량 지시는 문장 수보다 자수 상한으로.** "1~2문장"을 Gemini가 1,651자로 위반했다. "최대 400자"가 더 기계적이다(이 항목은 실측 근거가 아직 없는 제안이다).
5. **공용 시스템 프롬프트는 지금 형태를 유지하라.** 언어·근거·주입 방지 규칙은 양쪽에서 작동이 실증됐다. provider별 시스템 프롬프트 분기는 만들지 말 것 — 발산은 시스템 프롬프트 층이 아니라 스테이지 지시문과 스키마 층에서 났다.

## 4. effort 사다리 권고

| 단계 | Gemini thinking | Luna reasoning | 근거 |
|---|---|---|---|
| visual | low 유지 | low 유지 | 양쪽 안정, 개수 완전 일치, reasoning 83토큰이면 충분 |
| recipe | medium 유지 (cap 24k 유지) | medium 유지 (cap 24k 유지) | 정상 출력 6.0k/8.5k로 cap 여유 3배. Luna reasoning 303토큰 |
| deep_dive | **high 고정, 내리지 말 것** | **xhigh 대신 high** | 아래 두 발견 |

- **Gemini deep_dive를 medium으로 내리면 폭주한다(1/1 재현).** 모델이 `to_be` 문자열 값 안에 갇혀 필러를 65,522토큰까지 반복했고 $0.258이 나갔다. high에서는 2,840토큰으로 정상. DEC-014의 "마지막 속성 자유서술 금지"는 필요 조건이지 충분 조건이 아니라는 증거다 — 이번 폭주는 마지막 속성이 아니라 중간 필드에서 났고, effort가 낮을 때 종료 토큰 실패 확률이 올라가는 것으로 보인다(표본 1이므로 단정은 아니다).
- **Luna xhigh는 high 대비 이득이 없다.** 필드 채움 동등(강점 8 vs 7, 약점 13 vs 13), 비용 +25%, 시간 +38%. 2026-08-01 실측 결론("xhigh는 지연 5.4배 대비 이득 없음")이 체인 경로에서 재확인됐다. provider-neutral 브랜치 레지스트리의 deep_dive=high가 옳고, `tools/provider_compare.py`의 xhigh 매핑이 낡은 값이다.

**후속 조치 권고(이번 실측이 만든 것):** `_STAGE_MAX_OUTPUT_TOKENS`에 deep_dive 상한을 신설할 것. 정상 최대치가 8.7k(Luna xhigh)이므로 16,000이면 여유 1.8배 이상이고, 폭주 1회 손해가 $0.258에서 $0.063으로 준다. 현재 deep_dive에는 상한이 없어 폭주가 모델 상한(65,536)까지 달린다.

## 5. 2차 실측: VLA 고인용 논문 6편 (같은 날 후속)

인용 500회 이상 VLA 논문 6편으로 같은 체인을 반복했다: RT-2(4,003회), OpenVLA(3,139), PaLM-E(3,061), RT-1(2,733), π0(2,490), Octo(1,720). 인용수는 Semantic Scholar API로 검증했고, PDF는 arXiv 원본(17~37쪽)이다. 도메인은 ai_ml(neural 페르소나), effort는 1차 실측의 권고 사다리(양사 visual low, recipe medium, deep_dive high)를 썼고, deep_dive에 권고안이던 출력 상한 16,000을 하네스에 걸었다. 라이브러리 밖 논문이라 figure_desc와 digest는 비웠다. 호출 36건, 오류 0건, 총 $0.9825. 증거: `2026-08-29-chain-compare/vla/`.

### 논문별 체인 합계

| 논문 | 쪽 | Gemini in→out, 비용, 시간 | Luna in→out, 비용, 시간 |
|---|---|---|---|
| RT-2 | 26 | 52.6k→12.1k, $0.085, 57s | 169.6k→14.5k, $0.051, 147s |
| RT-1 | 31 | 58.9k→18.6k, $0.114, 61s | 228.8k→14.9k, $0.064, 153s |
| PaLM-E | 18 | 38.4k→20.1k, $0.104, 53s (폭주 1) | 148.7k→16.0k, $0.049, 154s |
| OpenVLA | 37 | 70.1k→22.1k, $0.135, 80s (폭주 1) | 227.0k→17.2k, $0.066, 149s |
| Octo | 17 | 38.9k→22.2k, $0.113, 58s (폭주 1) | 132.9k→16.9k, $0.047, 148s |
| π0 | 17 | 36.8k→20.1k, $0.103, 62s (폭주 1) | 172.6k→14.2k, $0.052, 138s |
| **합계** | | **$0.654, 평균 62s** | **$0.329, 평균 148s** |

### 발견 1: Gemini deep_dive는 high에서도 폭주한다 (4/6)

PaLM-E, OpenVLA, Octo, π0에서 deep_dive가 16k 상한까지 달려 incomplete로 잘렸다. RT-1도 completed지만 14,503토큰으로 상한 직전이었다. 필러 패턴이 1차 실측(medium 폭주)과 같은 종류다: "(논문 자체 비교 범위 기준)", "(논문 제시 범위 기준 도달 목표임)" 같은 한정 문구의 무한 반복. 이 문구는 deep_dive 지시문의 "novelty_assessment와 comparison_to_prior_work는 논문이 스스로 제시한 비교 범위 안의 평가임을 명시해" 요구가 시킨 것이다. 즉 폭주의 씨앗은 effort 수준만이 아니라 **자유서술 필드 안에 반복 가능한 정형 문구를 요구하는 프롬프트 지시**다. 1차 실측에서 optics 논문 1편이 high에서 무사했던 것은 표본 운이었다.

- 상한 16k가 없었다면 4건 × 최대 $0.26이 나갔다. 상한 덕에 폭주당 약 $0.06으로 막혔다. **deep_dive 상한 신설 권고가 실증으로 승격됐다.**
- 프로덕션이라면 `salvage_truncated_json`이 앞부분 필드를 살리므로 파괴는 아니지만, 뒤쪽 필드(리스트류)가 조용히 사라진다.
- 프롬프트 쪽 근본 수정 후보: "명시해" 지시를 없애고 그 의미를 스키마로 옮긴다(예: `comparison_scope` enum 필드 `"in_paper_only"`). 3장의 "수렴은 스키마로" 원칙과 같은 처방이 폭주 방지 처방이기도 하다.

### 발견 2: Luna는 24건(1차 포함) 전부 정상 완료

VLA 6편 × 3단계 18건 모두 completed, reasoning 200~700토큰, 폭주 0회. 비용도 Gemini의 절반이다($0.329 vs $0.654 — Gemini 합계는 폭주 비용이 부풀렸다). 다만 지연은 Luna가 논문당 평균 148초로 Gemini(62초)의 2.4배다.

### 발견 3: 수렴 패턴은 도메인 불문 재현

- **visual 개수는 6편 전부 완전 일치**(그림 10/10, 13/13, 8/8, 11/11, 7/7, 14/14, 표도 동일). 개수형 사실은 이미 수렴한다.
- **recipe 파라미터 이름 교집합은 1~8개/47~88개.** optics(8/90)에 이어 ai_ml에서도 명명 규약 부재가 provider 간 비교를 불가능하게 만든다. 개수도 Gemini 11~36 vs Luna 24~60으로 Luna가 일관되게 많다.
- **deep_dive 목록 개수 발산 재현**: 약점 Gemini 5개 내외 vs Luna 12~17개.

## 6. 3차 실측: DEC-018 수정의 재실행 검증 (폭주 4편, $0.46)

처방 적용 후 폭주 4편을 같은 Gemini 체인으로 재실행했다. 증거: `2026-08-29-chain-compare/vla-fixed/`.

| 논문 | 이전 deep_dive | 수정 후 deep_dive | 판정 |
|---|---|---|---|
| PaLM-E | 15,986 폭주 | 4,149 완료 | 해소 |
| Octo | 15,986 폭주 | 7,546 완료 | 해소 |
| π0 | 15,986 폭주 | 15,986 폭주(필러가 근거 위치 표기 반복으로 변경) | 잔존 |
| OpenVLA | 15,986 폭주 | 15,986 폭주(점 반복) + recipe도 새로 폭주(23,986, 어미 반복) | 잔존·확산 |

해석. enum 이전은 표적했던 씨앗을 정확히 제거했다(옛 필러 문구는 4편 전부에서 소멸, 성공 2편은 comparison_scope="in_paper_only"를 정상 출력). 그러나 폭주 자체는 확률적 실패 모드라 다음으로 흔한 반복 가능 패턴으로 옮겨갔다: π0의 필러는 "강점·약점에 근거 위치(섹션/그림/표)를 함께 적어" 지시가 만든 위치 표기 문구다. OpenVLA recipe의 신규 폭주(직전 실행에서는 정상)는 같은 조건에서도 폭주가 났다 안 났다 하는 확률성의 직접 증거다.

교훈 세 가지. (1) 프롬프트의 정형 문구 제거는 발생률을 낮추는 완화제다(deep_dive 4/4 → 2/4). (2) 상한은 매번 작동한 유일한 방어다 — 이번 3건 폭주 전부 유한 손해($0.07~0.11)로 끝났다. (3) 남은 씨앗도 같은 원리로 구조 이전이 가능하다: strengths/weaknesses 항목을 {text, location} 객체로 분해하면 위치 표기가 자유서술 밖으로 나간다. 근본 대안은 deep_dive의 프로바이더 선택이다 — Luna는 누적 42/42 무폭주다.

## 7. 4차 실측: 혼합 체인 검증 (DEC-019, 폭주 2편, $0.116)

3차에서 폭주가 잔존한 2편(π0, OpenVLA)을 **Gemini visual·recipe → Luna deep_dive** 조합으로 돌렸다. deep_dive는 provider가 갈리므로 서버측 체인을 잇지 못하고, PDF 대신 논문 본문 텍스트(`doc_text`)를 주입해 새 체인으로 시작하며 앞선 두 단계 결과는 `restart_context`로 복원한다. 프로덕션 `_run_full_analysis`의 갈림 경로를 그대로 재현했다. 증거: `2026-08-29-chain-compare/mixed/`.

| 지표 | Gemini deep_dive (3차) | Luna deep_dive (혼합, 4차) |
|---|---|---|
| 종료 상태 | incomplete 2/2 (상한 도달) | **completed 2/2** |
| 출력 토큰 | 15,986 / 15,986 | 9,382 / 8,878 (상한의 56~59%) |
| 채워진 필드 | 8/14 (구제 후) | **14/14, 빈 필드 0** |
| 반복 오염 | 있음(위치 표기·점 반복) | `_has_degenerate_repetition` False |
| 근거 위치 표기 | 해당 없음 | 18/19, 19/21 |
| deep_dive 비용 | 약 $0.06(폭주분) | $0.0165 / $0.0187 |
| deep_dive 지연 | 약 20초 | 94.0초 / 85.6초 |

읽는 법 네 가지.

1. **폭주가 사라지고 손실 필드가 복구됐다.** 3차에서 조용히 사라지던 부가 필드 6개(to_be, novelty_assessment, comparison_to_prior_work, suggested_improvements, follow_up_questions, practical_applications)가 전부 채워졌다. `comparison_scope`도 양쪽 다 `"in_paper_only"`로 정상 출력됐다.
2. **체인을 끊어도 맥락이 죽지 않는다.** `restart_context`는 5,958자와 6,133자가 실렸고, deep_dive는 논문 전문(87,479자·135,720자)을 함께 받는다. method_summary가 π0의 "3B PaliGemma + 300M action expert", OpenVLA의 "SigLIP+DINOv2 → Llama 2 7B"를 정확히 서술해 원문 파악에 손실이 없음을 확인했다.
3. **비용이 오히려 싸다.** 폭주한 Gemini deep_dive가 편당 약 $0.06였고 Luna는 $0.017이다. 다만 이는 폭주 대비 비교이고, 폭주하지 않은 Gemini deep_dive는 더 싸다.
4. **대가는 지연 하나다.** deep_dive가 약 20초에서 약 90초로 늘어, 논문 한 편 체인이 약 70초 길어진다. 목록 개수도 Luna 성향대로 늘었다(약점 12~13개, 3차 Gemini는 5개 내외).

미검증으로 남은 것: 이 실측은 갈림 경로의 **의미**를 재현한 것이지 `_run_full_analysis` 자체를 태운 것이 아니다. 배선(체인 격리, interaction_id 누출 방지)은 단위 테스트 `test_deep_dive_provider_split_isolates_chain`이 잠근다.

## 8. 5차 실측: Gemini 쪽 대응 — penalty는 실패, required 승격은 성공 ($0.72)

DEC-019는 주 경로를 Luna로 옮겼을 뿐이고, OpenAI 키가 없는 사용자는 폴백으로 여전히 Gemini deep_dive를 탄다. 그 경로를 Gemini 안에서 고칠 수 있는지 확인했다. 증거: `2026-08-29-chain-compare/penalty/`, `.../required/`.

### 배경: 이것은 3.7 Flash의 알려진 회귀다

구글 개발자 포럼에 같은 증상이 보고돼 있다([스레드](https://discuss.ai.google.dev/t/gemini-3-7-flash-schema-constrained-json-output-degenerates-into-repeated-0-until-maxoutputtokens-regression-vs-gemini-3-flash-preview/178681), 2026-08-17, 공식 응답 없음). 구조화 JSON 출력에서 반복 루프에 빠져 `maxOutputTokens`까지 달리고, 3.7 Flash에서만 나며 이전 버전(3-flash-preview)에서는 0건이다. 보고자의 발생률은 합성 33%, 실제 페이로드 최대 100%(우리 VLA 실측은 6편 중 4편). **temperature 0도 듣지 않는다** — 보고자 표현으로 "일부 입력에 대한 결정론적 어트랙터"다. 우리가 재시도를 건너뛰도록 만든 근거(같은 자리에서 또 잘린다)와 같은 관찰이다.

또한 `maxLength`는 쓸 수 없다. Gemini 구조화 출력은 JSON Schema의 부분집합만 지원하고 문자열 길이 제약은 그 목록에 없어, 무시되거나 400을 받는다.

### 실패: frequency_penalty (2편 × 3조건, $0.475)

| 조건 | π0 | OpenVLA |
|---|---|---|
| 대조(없음) | 3,844 completed | 3,411 completed |
| 0.3 | 15,986 **폭주**, 파싱 실패 | 15,985 **폭주**, 파싱 실패 |
| 0.8 | 1,715 completed (본문 2,730자) | 5,132 completed |

0.3이 2/2로 폭주를 **유발**했다. 원리로 설명된다: JSON은 구조 토큰(따옴표, 중괄호, 필드명)이 본질적으로 반복적인데 `frequency_penalty`는 이미 나온 토큰의 확률을 낮추므로 문자열을 닫는 토큰까지 페널티를 받아 종료가 막힌다. 0.8은 폭주는 없으나 π0 본문이 대조군의 절반으로 줄었다. 어느 값도 쓸 수 없다.

이 회차에서 대조군이 폭주하지 않아 "penalty가 폭주를 막는가"는 검증할 수 없었다. 다만 "안전하지 않다"는 것은 확인됐다. π0의 recipe가 23,986토큰(상한 24,000 근접)으로 폭주 근접해 비용이 예상을 넘었다 — recipe도 여전히 위험하다는 별도 신호다.

### 성공: required 승격 (2편 × 2조건, $0.243)

이 회차의 진짜 발견은 penalty가 아니라 **폭주와 무관한 필드 생략**이었다. 위 penalty 실측에서 정상 완료한 4회가 전부 9/14 필드였고, 빠진 5개가 정확히 같았다: `novelty_assessment`, `comparison_to_prior_work`, `suggested_improvements`, `follow_up_questions`, `practical_applications`. 전부 required가 아닌 필드다. Luna는 같은 조건에서 14/14였다(7장).

즉 **폭주는 문제의 일부였을 뿐이고, 폭주를 완전히 막아도 Gemini는 Luna에 도달하지 못한다.** 3장 1번 처방("수렴시키려는 필드는 required로 승격하라")을 그대로 적용해 검증했다. 같은 부모 체인에서 스키마 required 목록만 바꿔 분기했다.

| 논문 | required 7개(대조) | required 12개(승격) |
|---|---|---|
| π0 | 9/14, 5필드 누락 | **14/14 전부 채움** |
| OpenVLA | 15,986 **폭주**, 파싱 실패 | **14/14**, 4,574토큰 정상 |

읽는 법 세 가지.

1. **required는 실제로 강제된다.** 2/2로 14/14이고 빈 값도 없다. 프롬프트 요청은 provider별 준수율이 갈리지만 스키마는 문법이 강제한다는 원칙이 다시 확인됐다.
2. **출력이 길어질 것이라는 우려는 빗나갔다.** 필드가 5개 늘었는데 본문 총량은 오히려 줄었다(π0 6,832자 → 5,975자). 각 필드가 간결해진 것이다.
3. **폭주가 줄어들 가능성이 있다.** OpenVLA는 대조군이 폭주했는데 승격 조건에서 4,574토큰으로 정상 완료했다. 채울 칸이 많으면 한 필드에 갇힐 여유가 줄고 문법이 다음 필드로 밀어내기 때문으로 보이나, **표본 1건이라 단정할 수 없다.**

채운 내용에 지어내기 흔적은 없다. π0는 OpenVLA·Octo·Diffusion Policy·ACT 대비를, OpenVLA는 SigLIP+DINOv2 융합과 Octo의 stitching 방식 대비를 짚는데 전부 논문에 실재하는 비교 대상이다. `as_is`/`to_be`만 required에서 남겼다 — 그 구도가 아예 없는 논문이 있어 강제하면 지어낸다.

## 9. 요약 (2차 실측 반영)

- 토큰: Luna는 입력이 3~5배지만(같은 PDF의 토큰화가 무겁고 체인 캐시 미적중) 단가로 상쇄돼 비용은 Gemini의 절반 수준이고(VLA 6편 $0.329 vs $0.654), 지연은 Gemini가 2.4~3.6배 빠르다.
- 수렴: 개수형 사실(그림·표 수)과 값, 언어는 7편 전부 수렴한다. 발산은 목록 개수, recipe 파라미터 명명 규약(교집합 1~8/50~90), 선택 필드 생략이며, 해법은 시스템 프롬프트 증설이 아니라 (1) required 승격, (2) 개수 대역 명시, (3) 명명 규약 한 줄이다.
- effort: visual low, recipe medium(cap 24k)은 양사 공통으로 안정. **deep_dive는 effort로 해결되지 않는다** — Gemini는 high에서도 VLA 4/6 폭주했다. 필요한 것은 (a) `_STAGE_MAX_OUTPUT_TOKENS`에 deep_dive 16k 신설(실증됨: 폭주당 $0.26 → $0.06), (b) "비교 범위 평가임을 명시해" 지시를 스키마 enum으로 대체(폭주 필러가 정확히 그 문구다), (c) Luna deep_dive는 high(xhigh 이득 없음, 24/24 무폭주).
- provider 선택 관점: 품질 발산을 스키마로 잡는다는 전제에서, 안정성과 비용은 Luna가, 지연은 Gemini가 우위다.
