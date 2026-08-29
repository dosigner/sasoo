# main 통합 패스 인수인계 — 승인 대기 1건, 감시 1건, 유예 5건

작성: 2026-08-23. 대상: 사용자와 다음 세션.
브랜치: `feat/provider-neutral-llm` (worktree `/Users/dongj/dev/논문_사수_개발중/.claude/worktrees/provider-neutral-llm`)
상태: 통합 완료, push 안 함, PR 안 만듦. 작업 트리 깨끗. HEAD `9b1249d`.

## 한 줄 요약

`origin/main`(v0.9.0, Gemini 3.7 Flash, 도입가 단가, Evidence Anchoring)을 이 브랜치에 병합했다. 텍스트 충돌 14파일 23 hunk와 의미 충돌 4건을 해소했고, 충돌 표시 없이 auto-merge된 뒤 깨져 있던 자리 4곳을 추가로 잡았다. 백엔드 `806 passed, 7 skipped, 145 subtests`, 실패 0건. 프론트 `145 passed`, `tsc --noEmit` 양쪽 통과.

## 이번 세션의 커밋

```
9b1249d test(model-registry): pdf_parse/visual role 이름 보호 복구, AST 스캔 docstring 정정
97e530e docs: 릴리스 노트 문구 초안 — 페이지 판독 공급사 전환 안내
8696c7e feat(audit): table_metrics가 fp의 세 갈래(duplicate/extra/unlabeled)를 남긴다
4ec1b9b test(pins): MODEL_FLASH_HQ의 문자열 값을 잠근다 — 조용한 3.6 되돌리기 차단
cedb2f5 merge: origin/main (v0.9.0, 3.7 Flash, 도입가 단가, Evidence Anchoring)
6a44f33 fix(registry): FLASH_HQ role의 effort를 minimal에서 low로 — 3.7 Flash 400 회피
2819f5b docs: main 통합 패스 계획 — 결정 6건 확정, 의미 충돌 4건
```

---

# 승인 대기 1건 — 통합 후 재측정

사용자 결정은 "최소 범위(12편 × 1회 × 2공급사)"이고, 실행 전 비용 보고와 승인이 조건이었다. 비용 산출은 끝났고 **실행은 승인 대기 중이다.** API 호출은 아직 0건이다.

**총 하한 $2.07 확정, 상한 미확정.**

| 공급사 | 예상 호출 | 비용 | 근거 |
|---|---|---|---|
| Gemini | 약 190회(페이지 단위) | $1.62 하한, 상한 미확정 | 이전 실측 $3.2458에 도입가(절반) 반영 |
| OpenAI | 약 191회 | $0.4435 확정 | 모델·effort·단가 모두 불변이라 이전 실측치 유효 |

이전 왕복이 $3.689였으므로 도입가 반영만으로 절반 아래로 내려간다.

**확정한 것.** 도입가가 오늘 실제로 적용되는지 `calc_cost`를 직접 불러 확인했다(1M in/1M out에서 $4.5 대 표준가 $9.0). 이전 실측 원장의 논문별 토큰으로 기록된 총비용을 정확히 재현해, 토큰 수와 단가 계산이 서로 맞는 것을 확인했다.

**상한을 못 낸 이유.** 커밋 `6a44f33`이 `pdf_parse`의 effort를 `minimal`에서 `low`로 올렸으므로 Gemini 쪽 thinking 토큰이 늘어난다. 그런데 **Gemini의 low-effort thinking 토큰량은 이 저장소에 측정치가 전무하다.** 이전 실측은 `minimal`이어서 `tokens_thought`가 항상 0이었다. OpenAI 쪽 low reasoning 토큰(190페이지에 34,402)이 있으나 다른 모델의 예산이라 전이할 근거가 없다. 억지 숫자를 만들지 않았다.

**산출액에 빠진 것.** 표 격자 복원 비용이다. `tools/extraction_audit/measure.py:268,313`이 `resolve_table_candidates`에 `provider`를 여전히 넘기지 않아 격자 복원이 항상 Gemini로 돈다(약 173건 추가 호출). 이전 인수인계 문서 결정 5의 미해결 항목이 병합 후에도 그대로다. `--reparse openai`를 돌려도 그 부분은 Gemini API를 쓴다.

**실행 명령.**

```bash
cd sasoo/backend
.venv/bin/python -m tools.extraction_audit.measure --lane production --reparse gemini --no-cache --tag reparse-gemini-postmerge
.venv/bin/python -m tools.extraction_audit.measure --lane production --reparse openai --no-cache --tag reparse-openai-postmerge
```

`--tag`를 이전과 다르게 주는 이유는 같은 값이면 원장 파일이 덮어써져 이전 실측과 대조할 수 없기 때문이다. `--reparse`와 `--lane deterministic`은 상호 배타다(deterministic lane이 `GEMINI_API_KEY`를 지우는데 `--reparse`는 그 키가 필요하다). `--lane production`과는 배타가 아니다.

측정 후 결과는 `docs/superpowers/plans/2026-08-21-openai-vision-audit-record.md`에 **덧붙인다**(이전 수치를 지우지 않는다). 대조표에 모델과 단가 기준일을 명시해야 한다 — 기준이 바뀐 두 측정을 나란히 두면서 그 사실을 적지 않으면 나중에 잘못 비교된다. `--repeat`를 쓰지 않았으므로 노이즈 바닥이 없다는 한계도 함께 적는다.

---

# 감시 1건 — OpenAI recipe의 출력 상한

병합이 `_STAGE_MAX_OUTPUT_TOKENS = {"recipe": 24_000}`을 **OpenAI 경로에도 적용시켰다.** 병합 전 이 브랜치의 OpenAI recipe에는 상한이 없었다.

24,000은 Gemini 실측값이다(근거는 `api/analysis_routes.py:1052-1059`의 주석). Responses API의 `max_output_tokens`도 reasoning 토큰을 포함해서 세고, **Luna의 medium reasoning 예산에 대한 측정치는 저장소에 없다.**

잘려도 `salvage_truncated_json`이 앞부분을 살리므로 파괴적이지는 않다. 다만 잘린 뒤쪽 파라미터가 조용히 사라지고 Evidence 앵커도 그만큼 줄어든다. 병합 커밋 메시지는 `TypeError` 해소만 다루고 상한값의 적정성은 다루지 않았다.

근거 없이 값을 바꾸는 대신 감시 항목으로 남긴다. `ai_provider=openai`로 recipe를 몇 번 돌려 `status`가 `incomplete`로 오는지, `tokens_out`이 24,000에 붙는지 보면 판단할 수 있다.

---

# 유예 5건

병합을 막지 않는다. 최종 리뷰가 triage한 결과를 함께 적는다.

## 병합 후 (2건)

1. **`test_gemini_keeps_current_model_and_minimal_effort` 함수명에 `minimal`이 남았다.** assert 값은 `low`다. 위치는 `services/test_gemini_parser.py:592`(`TestParserProviderRouting`, 클래스 정의 `:565`)이고 **상호참조가 같은 파일 `:230` 주석에 하나 더 있다.** 개명할 때 두 자리를 같이 고쳐야 한다. 같은 성질의 `test_resolvers_minimal` → `test_resolvers_low` 개명은 `services/test_model_registry.py`에서 이미 끝났다.

2. **릴리스 노트의 과잉 헤지.** `docs/superpowers/plans/2026-08-22-release-note-provider-switch.md`의 "다시 판독하지 않는다" 절이 단정 다음에 "재분석을 직접 요청하지 않으셨다면"이라는 조건을 붙였다. Task 4 리뷰가 프런트엔드 재분석 버튼(`Workbench.tsx:263`)까지 추적해 그 경로도 `force`를 붙이지 않는다는 것을 확정했으므로, 조건절 없이 이렇게 정리할 수 있다: "PDF 파일이 그대로면 저장된 결과를 그대로 씁니다. 공급사 설정을 바꾸는 것 자체가 기존 논문의 재판독을 유발하지는 않습니다." 초안 문서이므로 게시 시점에 다듬으면 된다.

## 수정 불필요 (2건)

3. **`table_metrics` 안의 invariant `assert`가 `python -O`에서 제거된다.** 개발자 불변식에 `assert`를 쓰는 것이 정확한 용법이고 이 CLI를 `-O`로 돌리는 경로가 없다. 다만 같은 이유로 `--selfcheck` 전체가 `-O`에서 무력화되면서 `selfcheck ok`를 그대로 찍는다. `-O`를 쓸 일이 생기면 그때 마지막 print를 조건화하면 된다.

4. **`print_lane`이 새 진단 키를 안 찍는다.** 고정폭 표에 번호별 dict를 얹을 자리가 없고, `fp`/`fn` 합계는 이미 찍히며 바로 다음 줄에 원장 경로가 나온다. 진단 목적은 JSON이 담는다.

## 기록만 (1건)

5. **한 리포트 안에서 `extra` 키의 타입이 갈린다.** `measure.py:395`의 `figure_metrics["extra"]`는 `list[int]`, `:363`의 `table_metrics["extra"]`는 `dict[int, int]`다. 이름을 기존 관용구에 맞춘 판단(아래 판단 4)이 "같은 것이 다른 키가 되는 문제"를 없애면서 "같은 키가 다른 모양을 뜻하는 문제"를 만들었다. 되돌릴 필요는 없다 — 현재 JSON을 재파싱하는 소비자가 없다(`services/test_extraction_accuracy_regression.py`는 `error`/`caption_linked`/`extracted_count`만 읽는다). JSON 소비자가 생기면 표와 그림 분기를 따로 써야 한다.

---

# 깨면 안 되는 계약 (이전 3개 + 이번에 추가된 것)

1. **매니페스트에 저장되는 엔진 문자열 `"gemini"`의 값 공간을 바꾸지 말 것.** 공급사 이름이 아니라 "LLM 비전으로 파싱됨"을 뜻하는 레거시 이름이다. 최종 리뷰가 `GEMINI_ENGINE_NAME`을 `"llm_vision"`으로 바꿔 11건 실패로 실증했다.

2. **페이지 파서 role은 `pdf_parse`다.** `visual`(그림 판독 단계)과 섞지 말 것. **이 보호가 이번 세션에 한 번 무력화됐다가 복구됐다.** 원래 보호는 값으로 구별했는데(`pdf_parse`=minimal vs `visual`=low), 커밋 `6a44f33`이 `pdf_parse`를 `low`로 올려 두 role의 값이 양쪽 provider에서 같아지자 값으로는 구별할 수 없게 됐다. 커밋 `9b1249d`가 값 대신 **role 이름 자체를 단정**하도록 고쳤다(`services/test_model_registry.py`의 `TestPdfParseRole`이 `model_registry.resolve`를 spy로 감싸 `assert_any_call("pdf_parse", ...)`을 본다). 이 테스트를 지우거나 값 비교로 되돌리지 말 것.

3. **`SASOO_GEMINI_PARSER_THINKING`의 빈 문자열은 "오버라이드 없음"(레지스트리 값 사용)이다.** 같은 파일의 `MEDIA_RESOLUTION`은 여전히 옛 관용구(`_env_str(..., "low")`)이고 통일하면 안 된다.

4. **`minimal`은 flash-lite를 쓰는 role에서만 쓴다.** `MODEL_FLASH_HQ`(= `gemini-3.7-flash`)는 `minimal`을 400으로 거부한다. `services/test_model_registry.py::test_flash_hq_roles_never_use_minimal_effort`가 잠근다.

5. **`MODEL_FLASH_HQ`의 문자열 값이 잠겨 있다.** `services/test_model_pins.py::test_flash_hq_is_the_37_flash_id`. 이 단정이 없으면 이미 단가표에 있는 Gemini ID(예: 3.6)로 조용히 되돌려도 전 스위트가 통과한다.

6. **`max_output_tokens`는 두 클라이언트 모두에 있어야 한다.** `gemini_client.py`와 `openai_client.py` 양쪽이다. `interactions_client.py`는 30줄 디스패처이고 `**kwargs`로 통과시키므로, 한쪽만 고치면 그 provider에서만 `TypeError`가 난다. `analysis_routes`가 `recipe` phase에서 24,000을 넘긴다. 회귀 테스트는 `test_gemini_client.py`와 `test_openai_client.py` 양쪽에 있다.

7. **캐시 키의 두 장치는 상보적이다.** main의 `_phase_cache_key`가 `_CHAIN_CACHE_VERSION`으로 체인 버전 무효화를 하고, 이 브랜치의 `compute_input_hash(provider=, model=, effort=)`가 공급사 격리를 한다. 한쪽만 남기면 그쪽 보호가 사라진다. `_phase_cache_key`의 `thinking` 인자에 `None`이 들어가면 문자열 join에서 터지므로 호출부는 전부 `choice.effort or ""`를 쓴다.

8. **단가 폴백은 공급사별로 갈린다.** `_rate()`의 폴백이 `_fallback_for(model)`이어야 한다. `PRICING[_FALLBACK]`(Gemini)로 되돌리면 미지의 `gpt-*` 모델이 Gemini 단가로 조용히 오산된다.

---

# 이 병합에서 배운 것 — auto-merge가 조용히 깨뜨린 4곳

이전 PR이 닫힌 원인과 같은 종류다. **충돌 표시가 없었기 때문에 텍스트만 맞추면 드러나지 않았다.** 전부 main의 사용부만 auto-merge로 들어오고 이식이 덜 된 경우다.

1. **`_phase_cache_key` 네 호출부가 계획이 "버려라"고 지시한 `_STAGE_MODELS`/`_STAGE_THINKING`을 참조하고 있었다.** 지시대로 지우기만 하면 체인 네 스테이지가 `NameError`로 통째로 죽는다. 레지스트리 `choice`로 배선해 해결했다.
2. `MODEL_CITATION`/`MODEL_MERMAID`/`MODEL_VIZ_PLANNING` 임포트가 사라져 17건 실패.
3. main 신규 테스트 2개가 이 브랜치에 없는 `_THINKING_LEVEL`/`_STAGE_THINKING`을 참조.
4. `test_model_registry`의 `gemini-3.6-flash` 리터럴이 낡음.

**교훈 하나.** `git show --cc`(combined diff)는 두 부모 어느 쪽과도 다른 hunk만 담으므로, **auto-merge된 뒤 의미가 어긋난 자리는 combined diff에 나오지 않는다.** 위 4곳이 발견된 경로는 combined diff가 아니라 테스트 실패였다. 다음 병합에서도 combined diff만 보고 안심하지 말 것.

---

# 검증된 것과 미검증

## 검증

- 백엔드 `806 passed, 7 skipped, 145 subtests`, 실패 0건. 여러 에이전트가 독립적으로 관찰.
- 프론트 `145 passed`(17파일), `frontend`·`electron` `tsc --noEmit` 둘 다 exit 0.
- 의미 충돌 4자리를 **실행으로** 확인: 디스패처 4조합(`max_output_tokens`가 두 provider에 도달하고 `None`일 때 키 생략), 단가 5조합(미지 `gpt-*`→Luna, 미지 `gemini-*`→Gemini, 3.7이 오늘 도입가·2027년 표준가, PRO 300k는 long-context), 캐시 키 4성질, `_STAGE_MAX_OUTPUT_TOKENS` 실사용 위치 2곳.
- **Evidence 회귀 게이트 4건이 실제 데이터에서 통과한다.** `SASOO_APP_DATA_ROOT`로 실제 앱 데이터 루트를 가리켜 돌린 결과 `8 passed`(순수 4 + 코퍼스 4), skip 0. LLM 호출 0건. 즉 병합의 `result_id` 보존과 `_insert_analysis_result`의 `-> int` 반환이 Evidence 앵커를 실제로 결속한다.
  ```bash
  cd sasoo/backend
  SASOO_APP_DATA_ROOT="$HOME/Library/Application Support/sasoo" .venv/bin/python -m pytest services/test_evidence_regression.py
  ```
  이 방법을 기억해 둘 것. worktree의 `sasoo/backend/library/sasoo.db`는 0바이트라 게이트가 `sqlite3.Error`를 삼켜 조용히 skip된다 — **진짜 스키마 회귀도 똑같이 조용히 skip된다.**
- **추출 정확도 회귀 3건도 통과한다.** 메인 체크아웃의 매니페스트와 래스터를 심볼릭 링크로 붙여 돌린 결과 `3 passed / 36 subtests`, 62초, API 키 없이. 브랜치의 간판 계약(그림 12/12 정확일치, 표 기준선, 캡션 게이트)이 병합과 Task 3 이후에도 유지된다. worktree에는 정답셋 12편의 PDF는 있으나 `.odl_manifest.json`이 전부 없어서 기본 상태로는 skip된다.
- 새 테스트들이 실제로 회귀를 잡는 것을 각각 실증: `test_flash_hq_is_the_37_flash_id`(3.6으로 되돌리면 그 단정만 실패), `TestPdfParseRole`(`visual`로 바꾸면 실패), `_selfcheck_table_metrics`(`missing`을 반대 방향 차집합으로 바꾸면 실패 — `fp`는 그대로라 내부 invariant로는 안 걸리는 변경), `openai_client`의 `max_output_tokens`(포워딩을 지우면 `KeyError`).

## 미검증

- **실제 앱을 띄워 OpenAI 키만으로 업로드부터 완주까지 해 보지 않았다.** 이전 인수인계에도 있던 항목이고 여전히 남아 있다.
- 통합 후 정확도·비용 재측정(승인 대기).
- `--repeat` 노이즈 바닥, box_2d IoU의 12편 재확인, Terra, Luna 격자 복원 비용, PyInstaller 번들.
- OpenAI recipe의 24,000 상한 적정성(위 감시 항목).

---

# 이 세션에서 대신 내린 판단

사용자를 대신해 내린 판단이다. 틀린 것이 하나 있으니 함께 적는다.

| # | 판단 | 결과 |
|---|---|---|
| 1 | Task 3의 자기 점검은 `table_metrics`를 실제 호출해야 한다(계획은 조건부로 남겼다) | 타당. 복제 점검이었다면 통과했을 자리를 실증으로 확인 |
| 2 | Task 5는 비용 산출까지만, 실행은 승인 대기 | 타당 |
| 3 | `provider_compare.py`는 HEAD 채택, main 블록 이식 불필요(계획 텍스트가 부정확했다) | 타당 |
| 4 | 키 이름을 `missed`/`spurious`가 아니라 기존 `missing`/`extra`로 | 부분 문제. 판단은 옳지만 "같은 키가 다른 타입이 되는" 대가를 기록하지 않았다(위 유예 5번) |
| 5 | `extra`를 단순 집합 차집합으로 내지 않고 세 갈래로 분해 | 타당 |
| 6 | **Evidence 회귀 4건은 이 worktree에서 확인 불가** | **틀렸다.** 선택지를 "DB만 복사"와 "논문 폴더까지 복사" 둘로 놓은 것이 오류였다. `SASOO_APP_DATA_ROOT`로 복사 없이 실제 코퍼스에 붙는 세 번째 길이 있었고, 최종 리뷰가 그것으로 4건 전부 통과시켰다 |
| 7 | 최종 리뷰 범위를 이번 세션 6커밋으로 한정 | 결론은 타당. 근거 문장이 부정확했다 — combined diff가 auto-merge 의미 어긋남을 담지 못한다(위 "배운 것" 참조) |

---

# 관련 문서

- 이번 통합 계획: `docs/superpowers/plans/2026-08-22-provider-neutral-main-integration.md`
- 릴리스 노트 초안: `docs/superpowers/plans/2026-08-22-release-note-provider-switch.md`
- 이전 인수인계: `docs/superpowers/plans/2026-08-21-provider-neutral-vision-handoff.md`
- 실측 기록: `docs/superpowers/plans/2026-08-21-openai-vision-audit-record.md`
- 비전 엔진 구현 플랜: `docs/superpowers/plans/2026-08-21-pdf-visual-engine-provider-neutral.md`
- 앞선 작업 플랜: `docs/superpowers/plans/2026-08-03-ai-provider-neutral-llm.md` (2,079줄, 이 브랜치에만 있음)
- 스펙: `docs/superpowers/specs/2026-07-31-ai-provider-selection-design.md` (R2에 superseded 주석)

# 환경 함정 (변함 없음)

1. **pytest와 git은 샌드박스를 해제해서 실행할 것.** 안 하면 OpenDataLoader의 Java 런타임 때문에 `test_end_to_end_java_mode_writes_manifest_and_cache`가 실패하고 git은 `.gitconfig` 접근 거부로 실패한다. 코드 결함이 아니다.
2. 이 worktree에는 venv가 없다. `/Users/dongj/dev/논문_사수_개발중/sasoo/backend/.venv/bin/python`을 절대 경로로 쓴다.
3. 정답셋과 코퍼스 DB는 저장소 루트가 아니라 `sasoo/backend/library/`에 있다(`measure.py:61`, `models/database.py:221`).
