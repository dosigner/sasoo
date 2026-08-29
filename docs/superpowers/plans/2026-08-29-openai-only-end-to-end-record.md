# OpenAI 키 단독 완주 확인 — 실행 기록

작성: 2026-08-29. 대상: `feat/provider-neutral-llm` 병합분(PR #57, `fb58508`) 이후 코드.

이전 인수인계 두 건이 모두 "미검증"으로 남겨 둔 항목이다: **실제 앱을 OpenAI 키만으로
업로드부터 완주까지 해 본 적이 없다.** 테스트 810건은 전부 가짜 응답을 쓰므로 실제 API가
붙는 경로는 확인 범위 밖이었다. 이 문서가 그 공백을 메운다.

## 결론

**완주했다.** 6페이지 논문 1편이 오류 0건으로 끝났고, 원장에 남은 8개 단계 전부가
`gpt-5.6-luna`다. Gemini 모델은 한 번도 불리지 않았다.

## 실행 조건

Electron GUI는 띄우지 않았다. GUI 계층은 provider를 모르고 HTTP API만 호출하므로,
백엔드를 직접 완주시키는 것이 같은 것을 검증하면서 `pnpm install`과 GUI 자동화를 피한다.
**GUI 자체의 회귀는 이 확인의 범위가 아니다.**

실사용 데이터를 건드리지 않도록 격리했다.

- `SASOO_APP_DATA_ROOT`를 스크래치 경로로 지정해 빈 DB를 새로 만들었다.
- 실사용 DB에서 `openai_api_key`의 **암호문을 그대로 복사**해 스크래치 DB에 넣었다.
  평문은 어느 단계에서도 다루지 않았다(복호화는 백엔드가 런타임에 한다).
- `gemini_api_key`는 넣지 않았다. `GET /api/settings`가 `gemini_api_key: ''`,
  `openai_api_key: 'sk-proj-..._C8A'`, `ai_provider: 'openai'`를 반환하는 것을 확인한 뒤 시작했다.
- 포트 8931(실사용 앱의 8000과 분리).
- 라이브러리 루트가 worktree 자체 경로로 잡혀, 산출물이 사용자 라이브러리에 섞이지 않았다.

논문: `2019_FourierSpaceDNN_optics` (6페이지). 정답셋에서 가장 짧다.

## 단계별 결과

| 단계 | 모델 | tokens in/out | 비용 |
|---|---|---|---|
| screening | gpt-5.6-luna | 1,937 / 457 | $0.000936 |
| **visual_parse** | **gpt-5.6-luna** | 17,040 / 8,228 | $0.013282 |
| citation | gpt-5.6-luna | 3,276 / 1,593 | $0.002567 |
| visual | gpt-5.6-luna | 9,739 / 1,313 | $0.003523 |
| recipe | gpt-5.6-luna | 12,149 / 4,833 | $0.008229 |
| deep_dive | gpt-5.6-luna | 17,685 / 6,828 | $0.011731 |
| viz_plan | gpt-5.6-luna | 24,444 / 1,197 | $0.006325 |
| visualization | gpt-5.6-luna | 0 / 0 | $0.660000 |

`overall_status=completed`, 550초, 오류 0건. 총 **$0.706593**.

`visual_parse`가 이 PR의 핵심이다. PDF 페이지 비전 파싱이 OpenAI로 돌았다는 직접 증거다.

`visualization`의 $0.66은 토큰이 아니라 장당 과금되는 이미지 생성(gpt-image-2)이고
전체 비용의 93%다. 텍스트 경로만 보면 1편에 $0.047이다.

## 산출물

- `.odl_manifest.json` 46KB, 페이지 6개, 캡션 4개
- 그림 4개 크롭 PNG (180KB~704KB), 전부 `extraction_status=resolved`, `quality=high`
- 표 0개 (이 논문에 표가 없다)
- 마크다운, JSON, odl-reference 각 1부
- paperbanana 생성 이미지 4장 (1.3MB~2.1MB), 파일명이 한국어

## 계약 확인

**매니페스트의 엔진 문자열이 `"gemini"`인 채로 OpenAI가 파싱했다.**

```
engine: 'gemini'   text_engine: 'gemini'   visual_engine: 'gemini'
```

이 값이 공급사 이름이 아니라 "LLM 비전으로 파싱됨"을 뜻한다는 계약(인수인계 계약 1번)이
실동작에서 확인됐다. 값 공간을 바꾸면 승격·멱등 판정이 깨진다는 경고가 여전히 유효하다.

**Evidence Anchoring이 OpenAI 경로에서 동작한다.** recipe 파라미터 24개 중 15개가
`VERIFIED`다(`verifier_version: ev2`, `normalizer_version: norm-v2`).

| display_status | 건수 |
|---|---|
| VERIFIED | 15 |
| UNVERIFIED_VALUE_MISMATCH | 7 |
| UNVERIFIED_NOT_FOUND | 1 |
| UNVERIFIED_PARTIAL | 1 |

`match_method: normalized`, `match_ratio: 1.0`으로 원문 줄바꿈을 넘어 인용을 맞춘 사례를
확인했다. 검증률 62.5%가 정상 범위인지는 Gemini 대조가 없어 판정하지 않는다.

## 감시 항목 1건 — 결론 유보

병합이 `_STAGE_MAX_OUTPUT_TOKENS = {"recipe": 24_000}`을 OpenAI 경로에도 적용시킨 건이다.
이번 실행에서 recipe의 `tokens_out`은 4,833으로 상한의 20%였고 걸리지 않았다.

**6페이지 논문 1편으로는 판정할 수 없다.** 상한은 긴 논문에서 걸린다. 40페이지급으로
한 번 더 재기 전에는 열어 둔다.

## 이 확인이 다루지 않은 것

1. Electron GUI 자체(설정 화면, 업로드 UI, 워크벤치 렌더링).
2. 긴 논문. 상한 걸림, 문맥 초과, 페이지 수에 비례하는 실패 모드 전부 미확인.
3. 표가 있는 논문. 이 논문에 표가 없어 표 격자 복원 경로가 안 돌았다.
4. Gemini와의 품질 대조. 같은 논문을 Gemini로 돌려 비교하지 않았다.
