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
| 논문당 평균 비용 | $0.270482 | $0.036959 | Gemini 실효 모델 `gemini-3.6-flash`(pdf_parse effort=minimal), OpenAI 실효 모델 `gpt-5.6-luna`(effort=low, minimal 미지원) |
| 총 비용(12편) | $3.245781 | $0.443513 | |
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
      속도는 약 2.8배 빠르다. **정확도 동등성을 더 신뢰하려면 `--repeat`로 노이즈 바닥을 재는
      후속 측정이 필요하다.**
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
