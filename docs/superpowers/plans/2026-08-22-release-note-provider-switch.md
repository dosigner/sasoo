# 릴리스 노트 문구 초안 — 페이지 비전 파싱의 공급사 중립화

> 이 문서는 **초안**입니다. 사용자(게시자)가 실제 릴리스 노트에 옮기면서 다듬어 쓰는 것을
> 전제로 합니다. 각 문장 아래에 근거가 된 코드 위치를 남겼으니, 나중에 코드가 바뀌면 이
> 문구가 여전히 맞는지 그 위치를 다시 확인하면 됩니다.

## 사용자에게 보일 문구 (초안)

### 바뀐 것

PDF 페이지의 "AI 판독"(그림·표를 읽어내는 비전 파싱 단계)이 이제 설정의 AI 공급사
(`ai_provider`)를 따릅니다. 이전에는 공급사 설정과 무관하게 Gemini 키의 유무만 보고
켜지거나 꺼졌습니다.

| 사용자 | 이전 | 이후 |
|---|---|---|
| Gemini 키만 있음 | Gemini로 판독 | 그대로 (Gemini로 판독) |
| OpenAI 키만 있음 | AI 판독을 쓸 수 없어 로컬 파싱(ODL)으로 떨어짐 | OpenAI(Luna)로 판독 |
| 두 키 모두 있고, AI 공급사를 OpenAI로 설정 | Gemini로 판독 | **OpenAI(Luna)로 판독** |

세 번째 경우처럼 두 키를 모두 가지고 계셨고 AI 공급사를 OpenAI로 설정해 두신 분은
판독 경로가 실제로 바뀝니다. 정확도나 비용 차이를 안내드리는 것은 아직 이르고,
저희도 통합 후 재측정을 아직 하지 못했습니다. 다만 "어느 회사의 AI가 페이지를
읽는가"가 바뀐다는 사실은 미리 알려드립니다.

이전 동작(Gemini로 판독)을 계속 쓰고 싶으시면 설정에서 AI 공급사를 Gemini로
바꿔 주세요.

### 기존에 이미 분석해 두신 논문은 어떻게 되나요

이미 그림·표 판독이 끝난 논문은 이번 변경으로 다시 판독되지 않습니다. PDF 파일이
그대로이고 재분석을 직접 요청하지 않으셨다면, 저장된 결과를 그대로 씁니다. 공급사
설정을 바꾸는 것 자체가 기존 논문의 재판독을 유발하지는 않습니다.

## 근거 (코드 확인 결과)

- **판독 경로가 `ai_provider`를 따른다**: `_plan_visual_engines(provider)`가
  `key_env_for(provider)`가 돌려주는 환경변수(예: `ai_provider=openai`이면
  `OPENAI_API_KEY`)의 존재 여부만으로 LLM 비전 엔진을 후보에 넣는다.
  (`sasoo/backend/services/odl_parser.py:910-937`, `key_env_for` 정의는
  `sasoo/backend/services/provider_state.py:27-31`)
- **`ai_provider`가 실제로 쓰이는 공급사를 정한다**: 후보 계획에 넘기는 provider는
  `_resolve_visual_provider()` → `active_provider()`가 정하며, 이는 설정 DB의
  `ai_provider` 값을 키 가용성으로 보정한 것이다. (`odl_parser.py:1070-1079`,
  `odl_parser.py:1508`, 보정 로직은 `services/model_registry.py:111-125`와
  `services/provider_state.py`의 `effective_provider`)
- **OpenAI 공급사의 실제 모델은 Luna(`gpt-5.6-luna`)**: `model_registry.py`의
  `"openai"` 레지스트리에서 `"visual"` role이 `ModelChoice(MODEL_LUNA, "low")`로
  등록돼 있다. (`services/model_registry.py:70-90`, `MODEL_LUNA` 정의는
  `services/models.py:40`)
- **"gemini"라는 이름은 공급사가 아니라 "LLM 비전 경로" 자체를 가리키는 레거시
  이름**: `provider_state.py` 모듈 docstring이 이를 명시하고, 매니페스트의
  `visual_engine`/`text_engine` 필드에는 실제로 어느 공급사를 썼는지와 무관하게
  문자열 `"gemini"`가 그대로 기록된다. (`provider_state.py:14-19`,
  `odl_parser.py:1329`, `:1344-1345`)
- **변경 전 동작(Gemini 키 직접 조회)**: 이번 변경 이전 코드는 `os.environ`에서
  `GEMINI_API_KEY`를 직접 읽어 `vision_ok`를 정했다(공급사 설정을 보지 않음). 이번
  브랜치의 `_plan_visual_engines`가 `key_env_for(provider)`로 바뀐 것이 이 문서가
  다루는 변경의 본체다. (변경 전 동작은 브리프 작성자가 이미 코드에서 확인한 사실이며,
  변경 후 동작은 위 `odl_parser.py:910-937`에서 재확인함)

### "다시 판독하지 않는다"의 확인 (이번 작업에서 직접 검증)

- `ensure_visual_artifacts()`는 `force=False`이고 `_manifest_is_current(...)`가
  참이면 파싱을 건너뛰고 기존 manifest를 그대로 반환한다.
  (`odl_parser.py:1466-1475`)
- `_manifest_is_current`가 호출하는 `_visual_manifest_is_current`는 PDF
  서명(mtime/size), `requested_mode`, `extraction_pipeline_version`,
  `parser_version`, `resolver_version`, `visual_artifacts_ready`만 검사한다.
  **공급사(`ai_provider`)나 `visual_engine` 값은 이 판정에 들어가지 않는다.**
  (`odl_parser.py:401-424`) 텍스트 쪽의 `_text_manifest_is_current`도 동일하게
  공급사를 보지 않는다. (`odl_parser.py:378-398`)
- 따라서 PDF가 바뀌지 않고 파이프라인 버전이 같다면, 공급사를 바꾸는 것 자체가
  재판독을 유발하지 않는다.
- API 계층에서 이미 분석된 논문의 visual 아티팩트에 `force=True`를 넘기는
  경로는 찾지 못했다. `ensure_paper_artifacts`/`schedule_paper_artifacts_refresh`
  호출부(`api/papers.py:275`, `api/figure_service.py:449`,
  `api/analysis_routes.py:2759`)는 모두 `force` 인자를 생략해 기본값
  `False`를 쓴다. `force=True`가 쓰이는 유일한 지점은 신규 업로드 시 텍스트
  스테이지(`ensure_text_artifacts_async`, `api/papers.py:213`)이며, 이는 새
  논문의 최초 파싱이라 "기존 판독 결과"와 무관하다.
  → 위 두 사실을 근거로 "다시 판독하지 않는다"는 현재 코드에서 사실로 확인됐다.

## 이 문서에서 뺀 것 (근거를 못 찾았거나 브리프 범위 밖)

- 정확도·비용 비교: 통합 후 재측정이 없어(별도 태스크, 승인 대기) 넣지 않았다.
- "재분석을 수동으로 요청하면 어떻게 되는가"의 상세 동작(예: 사용자가 명시적으로
  강제 재분석을 트리거할 수 있는 UI/엔드포인트가 있는지)은 이번 확인 범위에서
  찾지 못했다. 본문에는 "재분석을 직접 요청하지 않으셨다면"이라는 조건으로
  범위를 한정해 이 불확실성을 흡수했다.
