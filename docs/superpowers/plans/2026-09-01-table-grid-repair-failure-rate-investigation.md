# 표 격자 복원 실패율 조사 (2026-09-01)

대상: `services/table_resolver.py`의 `_repair_with_vlm` 호출 경로.
발단: 정답셋 12편 측정에서 격자 복원 성공률이 Gemini 34/90(38%), OpenAI 37/93(40%)로
양쪽 모두 낮게 나왔다(`docs/superpowers/plans/2026-08-21-openai-vision-audit-record.md`).
브랜치 `main`, 코드 수정은 하지 않았다. **API 호출 0건** — 저장된 원장 JSON과
`sasoo/backend/library/`의 `.odl_manifest.json` 14편을 정적으로 분석했다.

## 결론

**"격자 복원 실패율 60%"는 VLM이나 파서의 품질 지표가 아니다. 분모의 71%가 결과를 쓰지
않고 버려지는 호출이다.**

`resolve_table_candidates`는 2단계에서 `needs_vlm_repair` 후보 전부에 VLM을 호출한 뒤,
3단계 캡션 필수 게이트(`table_resolver.py:396`)에서 캡션 없는 후보를 전량 폐기한다.
즉 **폐기가 확정된 후보에 VLM을 먼저 호출한다.** 복원이 성공하든 실패하든 그 결과는
산출물에 반영되지 않는데, 측정 도구는 이 호출까지 분모에 넣는다.

캡션 없는 후보의 정체는 코드 주석이 이미 적어 두었다: **그래프의 범례 박스**다. 범례는
격자 구조를 가져 pdfplumber가 표로 인식하지만 캡션이 붙지 않는다.

사용자 가설("공급사 요인이 아니라 파서 산출물 쪽")은 방향이 맞다. 다만 정확히는 "파서가
격자를 못 만든다"가 아니라 **"파서가 표가 아닌 것을 표 후보로 내고, 리졸버가 버릴 후보에
VLM을 먼저 호출한다"**이다. 양쪽 공급사에서 동시에 낮게 나온 이유가 이것으로 설명된다 —
분모 오염은 공급사와 무관한 구조적 요인이다.

## 근거 1 — 분모 구성 (원장 JSON, 12편)

| 항목 | Gemini | OpenAI |
|---|---|---|
| 표 후보 | 83 | 85 |
| 그중 캡션 없음 | 54 (65%) | 56 (66%) |
| 정답 표 라벨 | 26 | 26 |
| 최종 산출 표 | 25 | 26 |
| VLM 호출 | 90 | 93 |
| 격자 복원 "성공" | 34 (38%) | 37 (40%) |

후보 83개가 정답 표 26개의 3.2배다. 캡션 없는 후보 비율 65%와 측정된 실패율 62%가 같은
범위에 있다.

극단 사례가 방향을 확정한다. `2026_SR_AgileMultiskill_ai_ml`은 후보 19개가 **전부** 캡션이
없고 정답 표는 0개, 최종 산출도 0개다. 이 논문의 VLM 호출은 전량 낭비다.
`2014_Saliency_Optimization`은 후보 18개 중 15개가 무캡션이고 정답은 2개다.

## 근거 2 — 호출 대상 직접 재현 (매니페스트 14편, API 호출 없음)

`_repair_reasons`와 `needs_vlm_repair` 판정을 실제 코드에서 import해 그대로 재현했다.
캡션 유무는 3단계 게이트와 동일한 기준(캡션 객체의 `text` 유무)으로 판정했다.

```
후보 합계             : 100
VLM 호출 대상         :  77
  캡션 있음(유효)     :  22   ← 이 중 원본 격자가 이미 온전한 것 6건
  캡션 없음(전량 폐기):  55   = 호출의 71.4%
```

논문별 낭비율은 0%에서 100%까지 갈리고, 표가 없는 논문일수록 100%에 붙는다.

| 논문 | 후보 | VLM 호출 | 무캡션 | 낭비율 |
|---|---|---|---|---|
| 2012_ICSOS_SpaceOpticalNetworks | 1 | 1 | 1 | 100% |
| 2014_Saliency_Optimization | 18 | 10 | 7 | 70% |
| 2017_COMST_OpticalComm | 9 | 3 | 3 | 100% |
| 2022_SciRep_CoherentFsoLeo | 5 | 4 | 2 | 50% |
| 2023_FlowMatching | 10 | 10 | 5 | 50% |
| 2025_GR00TN1 | 22 | 21 | 12 | 57% |
| 2025_OptExpress_UplinkPrecomp | 3 | 1 | 0 | 0% |
| 2025_TurboQuant | 5 | 5 | 5 | 100% |
| 2026_SR_AgileMultiskill | 18 | 15 | 15 | 100% |
| OptFor_RefractiveMCAO | 2 | 2 | 0 | 0% |
| TurPy_OpticTurb | 7 | 5 | 5 | 100% |

폐기되는 55건의 복원 사유는 `ruled_bbox_without_grid` 46건이 압도적이다. "격자선처럼 보이는
사각형은 있는데 텍스트 격자가 비어 있다"는 조건으로, 범례 박스의 특징과 정확히 일치한다.
출처는 `pdfplumber` 25건, `raster_ruled_table` 19건, `odl` 7건, `hybrid` 4건이다.

재현 스크립트는 `$CLAUDE_JOB_DIR/tmp/grid_audit.py`, `grid_audit2.py`에 있다(일회성).

## 근거 3 — 낭비가 스스로를 증폭시킨다 (2패스 구조)

VLM 호출 수(90, 93)가 후보 수(83, 85)보다 많은 이유다.

1. 무캡션 후보가 캡션 게이트에서 폐기될 때 그 페이지가 `low_confidence_pages`에 등록된다
   (`table_resolver.py:396-399`).
2. `measure.py:318` 부근의 `retry_table_pages = low_table_pages | suspect_pages`가 그
   페이지를 재시도 대상으로 삼는다.
3. 재시도는 같은 페이지를 `aggressive=True`로 다시 파싱해 후보를 **더** 만들고
   `resolve_table_candidates`를 재호출한다.
4. 새로 생긴 후보도 대개 캡션이 없으므로 다시 VLM을 호출하고 다시 폐기된다.

프로덕션 경로(`services/odl_parser.py`)도 같은 2패스 구조를 쓴다. 이 조사는 감사 도구의
문제가 아니라 리졸버 자체의 문제다.

## 정확도에 대한 함의 — 위험 규모가 과대평가돼 있었다

인수인계 문서가 "표 셀 품질에 영향을 줄 수 있다"고 적은 우려는 범위를 좁혀야 한다.

- 폐기될 후보에 대한 호출은 **정확도에 영향을 주지 않는다.** 결과를 쓰지 않기 때문이다.
- 실제 셀 품질 위험은 **캡션 있는 22건, 그중 원본 격자가 부실한 16건**에 국한된다. 이 16건이
  실패하면 원본 격자로 되돌아가고, 원본이 `_has_meaningful_grid`를 통과하지 못하면 표가
  아예 산출되지 않거나(fn) 격자가 빈약한 채로 나온다.
- 즉 위험의 규모는 90건이 아니라 16건 수준이다. 실패율 60%라는 숫자가 실제 위험을 3~4배
  과대평가하고 있었다.

이 16건의 실패 내역은 **미측정**이다. 로그가 남아 있지 않고, 재측정에는 API 호출이 든다.

## 수정 (2026-09-01 적용 완료)

1단계의 `needs_vlm_repair` 계산에 캡션 조건을 넣으면 2단계와 3단계의 기준이 일치한다.

```python
# 현재
needs_vlm_repair = bool(unresolved_reasons) and (
    bool(candidate.get("plausible_ruled_bbox"))
    or bool(candidate.get("best_caption_id"))
    or (isinstance(page_number, int) and page_number in suspect_pages)
)

# 제안 — 캡션 없는 후보는 3단계 게이트에서 전량 폐기되므로 복원해도 결과를 쓰지 않는다.
has_caption = bool(captions_by_id.get(candidate.get("best_caption_id") or "", {}).get("text"))
needs_vlm_repair = has_caption and bool(unresolved_reasons)
```

**산출물은 바뀌지 않는다.** 캡션 텍스트가 있으면 원래 조건의 `or bool(best_caption_id)`가
자동으로 참이므로 유효 호출은 그대로 남는다. 매니페스트 14편으로 두 식을 대조해 확인했다 —
기존 호출 중 결과가 실제로 쓰이는 것 22건, 제안이 호출하는 것 22건으로 일치하고, 제안이
기존에 없던 호출을 만드는 경우는 없었다(`assert`로 확인). `best_caption_id`는 있으나 캡션
객체의 `text`가 없는 경계 사례는 이 코퍼스에 0건이며, 그 경우에도 기존 경로는 호출 후 폐기라
산출물은 같다. 캡션이 없는 후보는 기존에도 결과가 폐기됐고,
`low_confidence_pages` 등록도 skip 경로와 캡션 게이트 경로 양쪽에서 동일하게 일어난다.

기대 효과는 VLM 호출 약 71% 감소다. 격자 복원 비용은 지금까지 한 번도 측정된 적이 없으므로
(두 실측 모두 페이지 파싱 비용만 집계했다) 절감액은 **미산출**이다. 2패스 증폭까지 줄어들면
감소폭은 71%보다 커질 수 있다.

같이 손볼 값이 있는 자리:

- `measure.py`의 `VlmCache.successes`는 `_has_meaningful_grid(result[0])`로 센다. VLM이
  실패해 원본을 그대로 돌려줘도 그 원본이 온전하면 "성공"으로 잡히므로, **분자도 오염돼
  있다.** 지표를 "유효 호출 대비 복원 성공"으로 다시 정의해야 수치가 의미를 갖는다.
- `table_resolver.py:326`의 `repair_targets` 필터에 있는 `and not item["skip"]`은
  중복 조건이다. `skip`의 정의상 `needs_vlm_repair`가 참이면 `skip`은 항상 거짓이다.

## 적용 결과

`services/table_resolver.py`에 위 변경을 넣었고, `measure.py`의 분자도 함께 고쳤다.
`_repair_with_vlm`은 실패하면 model에 `"heuristic"`을 넣어 원본 격자를 돌려주므로, 그
신호를 보면 "호출이 실패했는데 원본이 이미 온전했던" 경우를 성공에서 제외할 수 있다.

회귀 테스트는 `services/test_resolver_pipeline.py::TableRepairCallScopeTests` 3건이다.
`_repair_with_vlm`을 `AsyncMock`으로 감싸 호출 횟수를 직접 센다. 옛 조건으로 되돌리면
무캡션 2건이 `AssertionError: 1 != 0`으로 실패하고 유효 호출 1건은 통과하는 것을 실행으로
확인했다 — 낭비만 잡고 필요한 호출은 건드리지 않는다는 뜻이다.

백엔드 전체 `836 passed, 185 subtests`, 실패 0건.

## 검증하지 않은 것

- 실제 파이프라인을 돌렸을 때의 호출 수 감소분과 절감액. API 호출이 필요해 재측정하지
  않았다. 매니페스트 기준 예측은 약 71% 감소다.
- 캡션 있는 16건의 복원 실패 내역과 원인. 로그가 없다.
- 저장된 매니페스트 14편은 `--reparse`가 새로 만든 매니페스트와 동일하지 않다. 후보 수가
  대체로 일치하나(2012_ICSOS 1대 1, 2014_Saliency 18대 18) 일부는 어긋난다
  (2013_IEEETIP는 원장 5개, 저장본 0개). 비율 구조를 보는 데는 충분하지만 절대 수치를
  원장과 직접 대조하면 안 된다.
- 격자 복원 경로의 비용. 여전히 어느 측정에도 포함된 적이 없다.
