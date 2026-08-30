# OpenAI 페이지 비전 파싱 정확도 기록 (2026-08-21)

정답셋: docs/table_gold.json, 12편(표 라벨 26개). 도구: `tools.extraction_audit.measure --lane production --reparse {gemini,openai} --no-cache`
측정 대상: 페이지 비전 파싱 + 그림·표 후보 생성 + 리졸버(프로덕션과 같은 인자로 매니페스트를 처음부터 재생성).

## 실행 명령 전문

```bash
cd "/Users/dongj/dev/논문_사수_개발중/.claude/worktrees/provider-neutral-llm/sasoo/backend"
"/Users/dongj/dev/논문_사수_개발중/sasoo/backend/.venv/bin/python" -m tools.extraction_audit.measure \
    --lane production --reparse gemini --no-cache --tag reparse-gemini

"/Users/dongj/dev/논문_사수_개발중/sasoo/backend/.venv/bin/python" -m tools.extraction_audit.measure \
    --lane production --reparse openai --no-cache --tag reparse-openai
```

`--repeat`는 붙이지 않았다(비용 절감). **각 조건 1회씩만 측정했으므로 VLM 비결정성에 의한
노이즈 바닥은 이 기록만으로는 구분할 수 없다.**

원장(raw JSON):
- Gemini: `sasoo/backend/tools/extraction_audit/_out/measure_productionreparse-gemini.json`
- OpenAI: `sasoo/backend/tools/extraction_audit/_out/measure_productionreparse-openai.json`

## 측정 도구에 가한 최소 수정

`measure.py`는 정확도만 재고 토큰/비용을 어디로도 내보내지 않았다(리포트 템플릿이 요구하는
"논문당 평균 비용"을 낼 방법이 없었다). `run_convert_gemini`가 이미 지원하는 `usage_out`
out-param을 `_reparse_manifest` → `run_lane`까지 그대로 연결해 논문별 tokens/cost_usd와
소요 시간을 결과 JSON에 추가했을 뿐이고, 파이프라인 로직(캡션 인정, 후보 생성, 리졸버, 지표
계산)은 한 줄도 바꾸지 않았다. `git diff`로 확인 가능.

## 결과

| 지표 | Gemini (이번 재파싱 기준선) | OpenAI | 비고 |
|---|---|---|---|
| 그림 정확일치 | 12/12 | 12/12 | 부모 그림 번호 집합 기준(서브피겨 제외) |
| 표 정확일치 | 10/12 | 9/12 | 아래 "표 정확일치 실패 상세" 참조 |
| 표 라벨 재현율 | 24/26 (92.3%) | 23/26 (88.5%) | 정답 26개 기준, `fn` 합산 |
| 논문당 페이지 비전 파싱 비용(격자 복원 VLM 제외) | $0.270482 | $0.036959 | Gemini 실효 모델 `gemini-3.6-flash`(pdf_parse effort=minimal), OpenAI 실효 모델 `gpt-5.6-luna`(effort=low, minimal 미지원). 표 격자 복원(`table_resolver._repair_with_vlm`) 호출 비용은 포함하지 않음 — 아래 "비용 측정 범위" 참조 |
| 총 페이지 비전 파싱 비용(12편, 격자 복원 VLM 제외) | $3.245781 | $0.443513 | |
| 논문당 평균 소요 | 144.3초 | 52.0초 | OpenAI가 약 2.8배 빠름 |
| VLM 호출 수 | 84 | 89 | 표 격자 복원(`table_resolver._repair_with_vlm`) 호출 |
| 격자 복원 성공 | 39/84 | 43/89 | |
| 요소 과분할 관찰 | 있음(양쪽 공통) | 있음(양쪽 공통) | 아래 참조 |

## 비교 기준에 대한 중요한 단서 — 두 기준선을 구분할 것

메모리에 기록된 기존 "그림·표 모두 12/12"는 **저장된 `.odl_manifest.json`으로 리졸버 단계만
격리해 잰 값**이다(페이지 비전 파싱을 거치지 않음). 이번 실행은 `--reparse`로 페이지 비전
파싱부터 다시 돌려 매니페스트를 새로 만들었으므로, 측정 기반이 다르다. 따라서 이 기록의
OpenAI 결과는 **기존 12/12가 아니라 이번 Gemini 재파싱 기준선(그림 12/12, 표 10/12)과
비교해야 한다.**

### Gemini 표 10/12에 대한 판정 (조정자 지시에 따른 기록)

표가 10/12로 나온 것은 아래 근거로 "코드 회귀"가 아니라 "측정 기반 차이 + VLM 비결정성"으로
본다. **이것은 추론이며 증명이 아니다** — `--repeat`를 붙이지 않아 노이즈 바닥을 재지 않았기
때문에, 표 10/12가 재현되는 저하인지 1회성 노이즈인지 이 실행만으로는 구분할 수 없다.

1. 측정 기반이 다르다(위 항목). 기존 12/12는 페이지 파싱을 거치지 않은 값이라 직접 비교 대상이
   아니다.
2. 그림이 12/12로 정확히 일치한다. Task 1~3이 Gemini 동작을 깼다면 그림도 함께 나빠질
   가능성이 높은데 그렇지 않다.
3. Task 1~3은 Gemini의 모델·effort를 바꾸지 않았다 — `resolve("pdf_parse", "gemini")`는
   `gemini-3.6-flash` + `minimal`로 현행과 동일하다(`services/model_registry.py`).
4. 놓친 2건 모두 FN(위양성 없음)이고, 로그에 페이지 파싱 중 일시적 JSON 파싱 실패가 찍혀
   있다: `Gemini parser page 10 attempt 1 failed: Invalid \uXXXX escape`,
   `page 5 attempt 1 failed: Unterminated string starting at`,
   `table resolver: 격자 복원 실패 ... JSONDecodeError`. 비전 모델의 비결정적 JSON 출력
   오류로 보인다. 누락 논문은 `2025_TurboQuant_general`(gold 2, 획득 1)과
   `OptFor_RefractiveMCAO_optics`(gold 5, 획득 4)다.

### 표 정확일치 실패 상세

| 논문 | Gemini | OpenAI |
|---|---|---|
| 2017_COMST_OpticalComm_optical_communications | 8/8 정확 | 7/8 (FN 1) |
| 2022_ApplOpt_PredictionNet_optics | 1/1 정확 | 0/1 (FN 1, 완전 누락) |
| 2025_TurboQuant_general | 1/2 (FN 1) | 2/2 정확 |
| OptFor_RefractiveMCAO_optics | 4/5 (FN 1) | 4/5 (FN 1) — **두 공급사가 동일하게 놓쳤다** |

OptFor_RefractiveMCAO_optics는 두 공급사에서 공통으로 표 1개를 놓쳤다. 공급사 무관 원인(예:
해당 표의 캡션 패턴이나 페이지 레이아웃)일 가능성이 있으나, 이번 기록의 범위에서는 어느 표
번호가 빠졌는지까지 추적하지 않았다(스크래치 디렉터리가 실행 종료 시 삭제됨) — **원인
미확인**.

### 비용 격차의 원인 — 조사 결과

논문당 평균 비용이 Gemini가 OpenAI보다 약 7.3배 높다(0.270482 / 0.036959 = 7.32). 이는
버그나 이상 동작이 아니라 **기본 토큰 단가 차이로 전부 설명된다** (`services/pricing.py`):

- `gemini-3.6-flash`: input $1.50/M, output $7.50/M
- `gpt-5.6-luna`: input $0.20/M, output $1.20/M

input 단가 비율 7.5배, output 단가 비율 6.25배로, 실측 비용 비율 7.32배와 같은 범위다. 이번
비교는 브리프 §60의 "Terra 승격(Luna 입력 단가의 10배)" 논의와는 무관하다 — 현재
`model_registry`의 OpenAI `pdf_parse` 실효 모델은 Luna(effort=low, minimal 미지원)이고 Terra가
아니다.

### 비용 측정 범위 — 격자 복원은 양쪽 실행 모두 Gemini로 돌았다

`measure.py`의 `resolve_table_candidates(manifest, paper_dir=scratch, resolver_version="audit")`
호출은 `provider=`를 넘기지 않으므로 `table_resolver._repair_with_vlm`의 기본값
`provider: str = "gemini"`가 그대로 적용된다. 반면 프로덕션(`services/odl_parser.py`
약 1154행)은 `provider = await active_provider()`로 결정한 provider를 그림·표
리졸버 양쪽에 명시적으로 넘긴다. 즉 이번 `--reparse openai` 실행은 **"OpenAI 페이지
파싱 + Gemini 표 격자 복원"의 혼합**이었고, `--reparse gemini` 실행은 양쪽 모두
Gemini였다. 위 결과 표의 비용 두 행은 `usage_out`이 담는 페이지 비전 파싱 비용만이며
격자 복원 VLM 호출(Gemini 84건, OpenAI 89건, 위 "VLM 호출 수" 행)의 비용을 포함하지
않는다.

함의:
1. 표 정확일치 차이(10/12 대 9/12)는 격자 복원이 양쪽 모두 Gemini로 고정된 상태에서
   나온 값이므로, **차이가 페이지 파싱 단계에 깨끗하게 귀속된다.** 이것은 오히려 좋은
   격리다.
2. "OpenAI가 7.3배 싸다"를 **파이프라인 총비용**으로 인용하면 틀리다. 그 수치는 페이지
   비전 파싱 비용만을 가리키며, 격자 복원 VLM 호출 비용이 빠져 있다. 또한 OpenAI 단독
   키 사용자가 실제로 쓰게 될 "표 격자 복원까지 Luna로 도는" 경로의 비용은 이번
   측정에 전혀 포함되지 않았다 — **미측정.**

### 요소 과분할 관찰

스파이크(1편 7페이지)에서 본 p4/p5/p6류의 과분할이 12편에서도 후보 생성 단계에서 보인다 —
예를 들어 2014_Saliency_Optimization은 그림 후보 18개 중 무캡션 15개, 2026_SR_AgileMultiskill
은 무캡션 후보 17~19개가 나왔다. 다만 **최종 리졸버 출력에서는 두 공급사 모두 그림 12/12,
캡션 인정률·후보 연결률 100%로 수렴**했으므로, 후보 단계의 과분할이 최종 정확도에 드러나는
차이로 이어지지는 않았다. 두 공급사 간에 이 패턴의 눈에 띄는 차이는 없다(둘 다 비슷한 규모의
무캡션 후보를 낸다).

### 그림 정답 출처에 대한 방법론적 단서

정답셋 12편 중 8편은 `*.odl-reference.md`가 없어 **직전 파싱 산출물**(일반 `.md`)을 그림
정답으로 쓴다(`FIGURE_MENTION.findall`이 그 텍스트에서 정답 그림 번호를 뽑는다). 이 8편의
정답은 과거 Gemini 파싱에서 유래했으므로 이론상 Gemini에 유리할 수 있다. 나머지 4편
(`2019_FourierSpaceDNN_optics`, `2025_OptExpress_UplinkPrecomp_optics`,
`2026_SR_AgileMultiskill_ai_ml`, `TurPy_OpticTurb_optics`)은 파서와 독립적인
`odl-reference.md`를 쓰므로 더 공정한 비교다.

| 그룹 | 논문 | Gemini 그림 정확일치 | OpenAI 그림 그림 정확일치 |
|---|---|---|---|
| odl-reference(4편, 공정) | FourierSpaceDNN, OptExpress_UplinkPrecomp, SR_AgileMultiskill, TurPy_OpticTurb | 4/4 | 4/4 |
| 일반 md(8편, Gemini 유리 가능) | 나머지 8편 | 8/8 | 8/8 |

이번 실행에서는 두 그룹 모두, 두 공급사 모두 그림이 완전히 일치해 **이 단서가 결과에 실제
영향을 준 흔적은 관찰되지 않았다.** 표 정답(`table_gold.json`)은 파서 출력과 무관한 별도
정답셋이라 이 단서의 영향을 받지 않는다.

## 스파이크(1편 7페이지) 대비

스파이크에서 본 box_2d IoU 0.98 수준의 정성적 관찰은 이번 12편 기록에서 IoU를 직접 재지
않아 재확인하지 못했다(측정 항목에 없음, **미측정**). 비용 우위는 방향은 스파이크와 다르다 —
스파이크는 Gemini를 effort low로 돌려 프로덕션(minimal)보다 비싸게 측정했다고 기록되어
있으나, 이 기록의 비용 배율(Gemini가 OpenAI보다 7.3배 비쌈)은 위에서 확인했듯 순수
토큰 단가 차이이며 프로덕션 effort(Gemini minimal, OpenAI low)로 측정한 값이다.

## 판정

- [x] OpenAI 경로를 기본으로 노출할 수 있는가 — 그림은 두 공급사가 동일(12/12), 표는 OpenAI가
      Gemini보다 약간 낮다(9/12 vs 10/12, 재현율 88.5% vs 92.3%). 1회 측정이라 이 차이가
      노이즈 범위인지 실제 격차인지 판단할 근거가 부족하다. 비용은 OpenAI가 약 7.3배 싸고
      속도는 약 2.8배 빠르다 — 단, 이 비용 비교는 **페이지 비전 파싱에 한정**되며, 표 격자
      복원은 이번 실행에서 양쪽 모두 Gemini로 돌아 OpenAI 단독 키 경로의 격자 복원 비용은
      미측정이다(위 "비용 측정 범위" 참조). **정확도 동등성을 더 신뢰하려면 `--repeat`로
      노이즈 바닥을 재는 후속 측정이 필요하다.**
- [x] Terra 승격을 검토해야 하는가 (Luna 입력 단가의 10배) — 이번 측정 범위 밖이다. 측정된
      OpenAI 경로는 Luna(effort=low)이고 Terra가 아니므로, 이 기록만으로는 Terra 승격 여부를
      판단할 근거가 없다. **미측정.**
- [ ] 남은 위험
  - Gemini/OpenAI 모두 표 리졸버 단계에서 JSONDecodeError(격자 복원 실패)가 다수 관찰됨 —
    VLM이 표를 grid JSON으로 되돌릴 때 이스케이프·구분자 오류를 일으키는 비율이 두 공급사
    모두에서 낮지 않다(Gemini 39/84 성공, OpenAI 43/89 성공, 즉 실패율 각각 약 54%, 52%).
    표 정확일치 지표(캡션 단위)에는 즉시 드러나지 않지만 표 내용 품질(격자 셀)에는 영향을
    줄 수 있다 — 이번 기록의 지표는 그 부분을 재지 않는다.
  - OptFor_RefractiveMCAO_optics의 표 1개 누락이 공급사 무관하게 재현됨 — 원인 미확인.
  - 1회 측정이라 VLM 비결정성에 의한 흔들림과 실제 저하를 구분할 수 없다.

---

# 통합 후 재측정 (2026-08-26)

`origin/main` 병합(3.7 Flash, 도입가 단가) 이후 같은 정답셋 12편을 다시 쟀다. 위의
2026-08-21 수치는 **지우지 않고 그대로 둔다** — 기준이 바뀐 두 측정이므로 아래 대조표의
"기준" 열을 보지 않고 비교하면 틀린다.

실행 명령:

```bash
cd sasoo/backend
.venv/bin/python -m tools.extraction_audit.measure --lane production --reparse gemini --no-cache --tag reparse-gemini-postmerge
.venv/bin/python -m tools.extraction_audit.measure --lane production --reparse openai --no-cache --tag reparse-openai-postmerge
```

원장: `tools/extraction_audit/_out/measure_production{reparse-gemini,reparse-openai}-postmerge.json`

## 두 측정의 기준 차이

| 항목 | 2026-08-21 | 2026-08-26 |
|---|---|---|
| Gemini 모델 | `gemini-3.6-flash` | `gemini-3.7-flash` |
| Gemini `pdf_parse` effort | `minimal` | `low` (커밋 `6a44f33`) |
| flash 단가 | 표준가 $1.50 / $7.50 | 도입가 $0.75 / $3.75 (2026-12-31까지) |
| OpenAI 모델·effort·단가 | `gpt-5.6-luna`, low | 동일 |

## 결과 대조

| 지표 | Gemini 08-21 | Gemini 08-26 | OpenAI 08-21 | OpenAI 08-26 |
|---|---|---|---|---|
| 그림 정확일치 | 12/12 | 12/12 | 12/12 | 12/12 |
| **표 정확일치** | 10/12 | **11/12** | 9/12 | **12/12** |
| 총 페이지 파싱 비용 | $3.245781 | **$1.086635** | $0.443513 | **$0.439446** |
| 논문당 비용 | $0.270482 | $0.090553 | $0.036959 | $0.036621 |
| 입력 토큰(12편 합) | 99,104 | 97,012 | 541,176 | 541,176 |
| 출력 토큰(12편 합) | 412,950 | **270,367** | 279,398 | 276,009 |
| thinking 토큰 | 0 | **0** | 34,402 | 31,236 |
| VLM 호출(격자 복원) | 84 | 90 | 89 | 93 |
| 격자 복원 성공 | 39/84 (46%) | 34/90 (38%) | 43/89 (48%) | 37/93 (40%) |

소요 시간은 대조표에서 뺐다 — 이번 측정이 시스템 슬립에 오염됐다(아래 참조).

## 표 정확일치의 방향이 뒤집혔다

2026-08-21에는 Gemini 10/12 대 OpenAI 9/12였고, 그 1편 차이를 수용하기로 결정했다
(결정 4). **이번 측정에서는 OpenAI 12/12, Gemini 11/12로 방향이 반대다.**

Gemini가 놓친 1건은 `OptFor_RefractiveMCAO_optics`의 **Table 3**이다. 이 논문은
2026-08-21에 양쪽 공급사가 공통으로 1건을 놓쳤고 "원인 미확인, 어느 표인지 기록되지
않아 진단이 막혀 있다"고 적힌 항목이었다. 이번에 `table_metrics`가 `missing` 키를
남기게 되면서(커밋 `8696c7e`) 처음으로 표 번호가 드러났다. OpenAI는 이번에 이 표를
잡았으므로, 원인은 공급사 공통이 아니라 Gemini 경로 쪽에 있다.

`--repeat`를 쓰지 않았으므로 **노이즈 바닥이 없다.** 1편 차이가 실차인지 노이즈인지는
이 측정만으로 판정할 수 없다. 다만 두 측정에서 방향이 반대로 나온 것 자체가, 이 차이를
공급사 우열의 근거로 쓰면 안 된다는 신호다.

## 비용은 예상 하한보다 더 내려갔다

사전 산출은 "Gemini 하한 $1.622891, 상한 미확정"이었다. 하한의 근거는 "토큰량이 이전과
같다면 도입가 절반이 적용되어 $3.245781 × 0.5"였고, effort 상승분만큼 상한이 열려
있다고 보았다.

실제는 $1.086635로 하한보다 33% 낮다. 이유는 **출력 토큰이 412,950에서 270,367로
34.5% 줄었기** 때문이다(입력은 99,104 → 97,012로 거의 같다). 검산:
`97,012/1M × 0.75 + 270,367/1M × 3.75 = 1.0867`. 사전 산출의 산술 자체는 맞았고,
전제("토큰량이 같다면")가 실제와 달랐다.

출력 감소의 주된 원인은 모델 교체로 보인다. 필터 차단으로 PyMuPDF 폴백을 탄 페이지가
5개 있으나(약 190페이지 중 2.6%) 34.5% 감소를 설명하지 못한다.

**Gemini의 thinking 토큰은 effort를 `low`로 올린 뒤에도 0으로 보고된다.** 2026-08-21
측정(effort `minimal`)에서도 0이었다. OpenAI 쪽은 31,236으로 정상 집계되므로 도구의
집계 누락이 아니라 Gemini SDK가 이 모델에서 `total_thought_tokens`를 0으로 주는 것이다.
그래서 effort 상승이 비용을 올리지 않았다.

## 소요 시간은 측정하지 못했다 (시스템 슬립 오염)

원장의 `elapsed_sec`에 `2017_COMST_OpticalComm` 한 편이 102,437.2초(28.5시간)로
찍혔다. **이 수치는 API 지연이 아니라 측정 아티팩트다.**

`measure.py:521,542`가 `time.time()`(벽시계)로 재기 때문에 프로세스가 진행하지 않는
시간도 그대로 포함된다. `pmset -g log`로 측정 구간(2026-08-25 17:39 ~ 08-26 22:18)을
확인한 결과 **총 68,445초(19.0시간)가 Sleep/DarkWake였다.** 25일 19시부터 26일
08시 30분까지 15~17분 슬립과 짧은 DarkWake가 1,485회 반복된, 방치된 노트북 패턴이다.

그래서 이 측정으로는 소요 시간을 판정할 수 없다.

- 논문별 `elapsed_sec`은 그 논문이 처리되던 구간에 시스템이 얼마나 잤는지를 반영할
  뿐이다. `2017_COMST`가 유독 큰 이유는 그 논문 차례에 사용자가 자리를 비웠기
  때문이고, 나머지 11편이 27~97초인 것은 깨어 있는 동안 처리됐기 때문이다.
- 위 결과 대조표에서 **소요 시간 행을 빼둔 것은 이 때문이다.** 2026-08-21 측정의
  "논문당 평균 144.3초 대 52.0초"와 이번 수치는 비교할 수 없다.
- 정확도와 비용은 영향받지 않는다. 토큰 수와 정확일치 판정은 벽시계와 무관하다.
  같은 논문의 출력 토큰이 82,988에서 82,635로 거의 같고 비용도 정상 범위다.

시간을 재려면 `time.monotonic()`으로 바꾸거나(macOS에서는 슬립 중 멈춘다), 측정 중
`caffeinate -i`로 슬립을 막아야 한다. 후자가 간단하다.

```bash
cd sasoo/backend
caffeinate -i .venv/bin/python -m tools.extraction_audit.measure --lane production --reparse gemini --no-cache --tag ...
```

## 별개로 확인된 결함 — `_is_retryable`이 400 필터를 재시도한다

위 시간 문제와 무관하게, 조사 중 실재하는 결함을 하나 찾았다.

`services/llm/gemini_client.py:61`의 `_is_retryable`은 `getattr(exc, "code", None)`이
`int`일 때만 상태 코드로 판정하고, `int`가 아니면 "판단 근거 없음"으로 보아 재시도한다.
그런데 이번 로그의 400 에러는 `code`가 문자열이다.

```
'code': 'invalid_request'
'code': 'The generated content was filtered because it may contain material that resembles existing copyrighted works.'
```

그래서 **함수의 docstring이 막겠다고 명시한 바로 그 케이스(400 copyright/recitation
필터)를 실제로는 재시도한다.** 로그의 `failed after retries` 문구가 그 증거다.

낭비되는 시간은 페이지당 최대 20초다(`_RETRY_DELAYS = [2, 8]`, `_PAGE_RETRIES = 1`).
이번 측정에서 필터에 걸린 페이지는 5개이므로 최대 100초 규모이고, 28.5시간과는
무관하다. 그래도 docstring이 주장하는 동작과 실제가 다르므로 고칠 값이 있다.

## 격자 복원 성공률이 조금 내려갔다

Gemini 46% → 38%, OpenAI 48% → 40%. 양쪽 공통이므로 공급사 요인이 아니라 파서 산출물
변화(캡션·후보 생성)에 따른 것으로 보인다. 이 경로는 여전히 provider를 받지 않아
양쪽 실행 모두 Gemini로 돈다(`measure.py:268,313`) — 2026-08-21의 한계가 그대로다.

## 이번 측정의 한계

1. `--repeat`를 쓰지 않아 노이즈 바닥이 없다. 표 1편 차이의 유의성을 판정할 수 없다.
2. 표 격자 복원 비용은 여전히 위 비용 수치에 포함되지 않는다. 그 경로는 항상 Gemini로
   돌기 때문에 `--reparse openai` 실행에서도 Gemini API를 쓴다.
3. **소요 시간을 재지 못했다.** 측정 구간의 19시간이 시스템 슬립이었다. 다시 재려면
   `caffeinate -i`로 감싸야 한다.
