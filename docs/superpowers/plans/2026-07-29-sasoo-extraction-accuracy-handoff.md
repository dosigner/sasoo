# sasoo 그림·표 추출 정확도 — 후속 작업 인수인계

> 새 세션 시작 시 이 파일을 그대로 붙여넣거나 경로를 알려주면 된다.
> 작성: 2026-07-29 / 직전 세션에서 PR #36·#37·#39 병합 완료 후 남은 과제.

---

## 0. 한 줄 요약

sasoo의 그림·표 추출 파이프라인에서 성능 7건·정확도 5건·UI 1건을 고쳐 `main`에 병합했다.
**남은 과제는 두 가지: (2) 과추출 ±1~3, (3) SR_Agile 누락 −2.** 둘 다 원인까지 특정돼 있고
구현만 남았다.

> **[2026-07-29 갱신] 과제 (2)·(3) 둘 다 해결.** 브랜치 `fix/extraction-caption-precision-recovery`
> 커밋 `c22548a`. 그림 추출 총 절대오차 **7 → 0**, 정확일치 **8편 → 12편(전편)**.
> 백엔드 441 passed(신규 10), 프론트 80 passed, 표 추출 총오차 33 불변.
> 상세는 §3·§4 하단의 "해결" 절과 §5의 갱신된 기준선 참조. 병합은 사용자 몫이라 미병합 상태.

> **[2026-08-01 갱신] 표 추출도 완결.** 브랜치 `fix/table-accuracy`(`c22548a` 위).
> 라벨 집합 기준 총오차 **24 → 0**, 정확일치 **12/12**, 캡션 연결률 **100%**.
> 백엔드 457 passed(신규 16). 상세는 **§8**(표 작업 결과와 새 계약).
> 착수 계획은 `2026-07-31-sasoo-table-accuracy-plan.md`.

---

## 1. 환경

| 항목 | 값 |
|---|---|
| 저장소 | `/Users/dongj/dev/논문_사수_개발중` (main 브랜치, 원격 `dosigner/sasoo`) |
| 백엔드 | `sasoo/backend`, venv = `sasoo/backend/.venv/bin/python` |
| 백엔드 테스트 | `cd sasoo/backend && .venv/bin/python -m pytest -q` → **431 passed** |
| 프론트 테스트 | `cd sasoo && npm run test:unit` → **80 passed** (DOM 없는 순수 로직 전용) |
| 프론트 빌드 | `cd sasoo && npm run build:frontend` |

**DB 경로 함정 (중요):**
- 개발 모드: `sasoo/backend/library/sasoo.db` ← **실제로 쓰는 것**
- 패키지 앱: `~/Library/Application Support/sasoo/` ← 다른 데이터. 진단 전에 어느 쪽인지 반드시 확인.
- 결정 로직: `models/database.py`의 `_get_app_data_root()` — 번들이 아니면 `backend/library`.

---

## 2. 직전 세션에서 병합된 것 (되돌리지 말 것)

```
dafc3f8  fix(ui): 아티팩트 준비 중 "그림이 아직 없어요" 오표시 (#37)
ba6e4cc  fix(extraction): 표 전멸·서브피겨 폭증·그림 누락·과추출 (#39)
095fa74  perf(pipeline): 처리량 개선 — 정상 2.0배, 필터 발생 시 4.7배 (#36)
```

### 깨면 안 되는 계약

1. **한글 파일명**: `files.upload`에 경로를 넘기면 안 된다. SDK가 `os.path.basename`을
   `X-Goog-Upload-File-Name` 헤더에 싣는데 HTTP 헤더는 ASCII만 담는다. 반드시 열린 파일 객체
   + `mime_type` + `display_name`. (`google/genai/_extra_utils.py`)
2. **resolver 병렬화 2단계는 순차**: 그림 번호(`_normalized_figure_num`의 seen·fallback_index)와
   크롭 파일명이 후보 그룹 순서에 의존한다. 병렬화하면 재분석 시 번호가 바뀐다.
3. **audit(`find_suspect_pages`)을 표 resolve 앞으로 옮기지 말 것**: `tables`/`table_candidates`를
   실제로 읽어 판정한다.
4. **페이지 markdown은 `(page_number, md)` 쌍 유지**: `enumerate` 재번호는 실패 페이지가 있을 때
   `--- Page N ---` 마커를 밀어 `document_audit._page_text_map`을 깨뜨린다.
5. **부분 실패 보충은 PyMuPDF로**: ODL은 페이지 단위 요청이 안 돼 전체 재파싱이 되고 속도 이득이 사라진다.
6. **캡션 라벨 해석은 `strip_caption_decoration()`을 거칠 것**: gemini는 캡션을 마크다운 그대로
   내보내 `**Fig. 1. ...**`처럼 볼드로 시작한다. 라벨 패턴은 전부 문두 매칭이라 `**` 하나에 깨진다.
   현재 4개 지점이 이 헬퍼를 쓴다(`_caption_kind`, `_normalized_figure_num`, `_table_num`,
   `figure_candidates`의 라벨 중복제거).
7. **캡션 없는 후보는 버린다**(사용자 결정 2026-07-29). 문서 단위 안전장치는 제거됐다.
   전멸 시 `figure_resolver`가 경고 로그를 남기고, 그 동작이 테스트로 고정돼 있다.

`c22548a`에서 추가된 계약:

8. **라벨 뒤 구분자를 무조건 요구하지 말 것**: `Fig. 2 Subharmonic Phase Screen Generation.`
   처럼 구분자 없는 진짜 캡션이 실제로 있다(TurPy_OpticTurb). 판정 기준은 구분자가 아니라
   **라벨 뒤 첫 글자의 대소문자**다 — 소문자면 본문 문장(서술 동사), 그 외는 캡션.
9. **캡션 복원은 라벨이 없는 페이지에만**: `recover_missing_caption_blocks`가 파서가 이미
   잡은 라벨을 다시 넣으면 같은 그림의 후보가 둘이 되어 "Fig. 1 [2]"가 나온다. 반대로 라벨
   점유는 `_caption_kind`가 인정한 블록만 해야 한다(본문 언급이 진짜 캡션의 복원을 막으면 안 됨).
10. **복원 bbox는 좌하단 원점으로 뒤집을 것**: PyMuPDF는 좌상단 원점이다. 안 뒤집으면 캡션이
    페이지 반대편으로 잡혀 `_fallback_bbox_from_caption`의 그림 영역이 위아래로 뒤집힌다.

---

## 3. 남은 과제 (2) — 과추출: 본문 언급이 캡션으로 오인됨

### 진단 (완료, 재조사 불필요)

`_caption_kind`가 `Fig. N`으로 시작하기만 하면 캡션으로 인정한다. 그래서 **본문 문장**이
캡션 블록이 된다.

```
진짜 캡션 : 'Fig. 1. Given a group of images...'     ← 라벨 뒤 마침표/콜론
본문 언급 : 'Fig. 1 illustrates the co-saliency...'  ← 라벨 뒤 바로 동사
            'Figure 9 shows time-series data...'
            'Figure 4(a) shows the atmospheric...'
            'Fig. 12 shows some segmentation...'
```

이 가짜 캡션이 별도 후보를 만들어 중복 그림이 된다. **초과분과 정확히 일치한다:**

| 논문 | 원문 | 추출 | 초과 라벨 |
|---|---|---|---|
| 2013_IEEETIP_ClusterCoSaliency | 16 | 17 | `Fig. 2 [2]` |
| 2022_SciRep_CoherentFsoLeo | 9 | 10 | `Fig. 9 [2]` |
| 2022_ApplOpt_PredictionNet | 8 | 11 | `Fig. 3 [2]`, `Fig. 4 [2]`, `Fig. 6 [2]` |

기존 라벨 중복제거(`figure_candidates._caption_candidates_for_page`)는 **페이지 단위**라
본문 언급이 다른 페이지에 있으면 안 걸린다(예: 캡션 p3, 언급 p4).

### 제안하는 수정

`_caption_kind`(`services/document_manifest.py`)에서 **라벨 뒤 구분자를 요구**한다.

- 캡션: `Fig. 1.` / `Figure 2:` / `Fig.2,` → 라벨 뒤 `.` `:` `,` 또는 줄바꿈
- 본문: `Fig. 1 illustrates` / `Figure 4(a) shows` → 거부

주의할 점:
- `Fig.2. Architecture...`처럼 **공백 없는** 표기가 실제로 있다(2022_ApplOpt p3).
- `Figure\xa01.`처럼 **non-breaking space**가 있다(2022_SciRep). 정규화 필요.
- 구분자 없는 캡션(`Figure 1 Schematic of ...`)이 존재할 수 있으니, 무작정 거부하면 누락이 는다.
  → **반드시 아래 측정 스크립트로 전 논문 영향을 확인한 뒤 결정할 것.**

대안: 문서 단위 라벨 중복제거(같은 라벨이면 캡션다운 것 하나만 남김). 구분자 규칙과
조합하면 더 안전할 수 있다.

### 해결 (2026-07-29, `c22548a`)

전 논문 캡션 블록 151건의 라벨 뒤 구분자를 전수 조사한 결과가 판단을 갈랐다.

| 라벨 뒤 | 건수 | 정체 |
|---|---|---|
| `.` | 114 | 진짜 캡션 |
| `:` | 25 | 진짜 캡션 |
| ` shows` | 6 | 본문 언급 |
| ` illustrates` | 3 | 본문 언급 |
| `(a) shows` | 2 | 본문 언급 |
| ` Subharmonic` | 1 | **구분자 없는 진짜 캡션** (TurPy `Fig. 2`) |

즉 §3이 우려한 "구분자 없는 캡션"이 실제로 1건 있고, 구분자를 무조건 요구하면 그 논문이
깨진다. 대신 **라벨 뒤 첫 글자가 소문자면 본문 문장, 구분자나 대문자면 캡션**으로 갈랐다 —
본문 언급은 라벨 뒤가 항상 서술 동사(소문자)이기 때문이고, 이 규칙이 151건 전부를 정확히
가른다. `Fig. 2(e) shows`처럼 서브라벨이 끼는 경우는 서브라벨을 건너뛴 뒤 같은 규칙을 쓴다.
`Figure\xa01.`(non-breaking space) 때문에 NFKC 정규화를 판정 앞에 뒀다.

구현: `document_manifest._label_is_followed_by_caption_body()` + `_caption_kind()` 개편.
문서 단위 중복제거(대안)는 쓰지 않았다 — 필요가 없었다.

**측정 스크립트 함정 (중요):** §5 스크립트의 `if k: c["kind"] = k`는 새 규칙이 `None`을
낼 때 저장된 옛 `"figure"` 값을 그대로 남긴다. 그래서 "덜 인정"하는 방향의 변경이 측정에
**전혀 반영되지 않는다**(이 수정도 처음엔 오차 7 그대로로 보였다).
반드시 `c["kind"] = _caption_kind(...) or "unknown"`으로 쓸 것. §5 스크립트는 수정해 뒀다.

---

## 4. 남은 과제 (3) — SR_Agile 누락 −2

`2026_SR_AgileMultiskill_ai_ml`: 원문 Figure 1~8인데 **파서가 캡션을 6개만 잡는다**
(Fig. 3, 5 없음) → 캡션 없는 후보는 버리는 규칙 때문에 그 둘이 사라진다.

이건 resolver 계층이 아니라 **파서(gemini) 계층 문제**다. 확인할 것:
1. 해당 페이지의 gemini markdown에 Fig. 3/5 캡션 텍스트가 아예 없는지, 아니면
   `elements`에 caption 타입으로 안 담긴 것인지
2. 전자면 프롬프트 문제, 후자면 `_assemble_page_nodes` 매핑 문제

관련 파일: `services/gemini_parser.py`의 `_PAGE_PROMPT_SLIM`, `_assemble_page_nodes`.

### 해결 (2026-07-29, `c22548a`)

조사 결과 **둘 다 아니었다.** 진단 순서와 결과:

1. gemini markdown에 Fig. 3(p6)·Fig. 5(p9) 캡션이 **온전히 존재**한다 → 프롬프트 문제 아님.
2. `_PAGE_PROMPT_SLIM`은 이미 "every figure MUST be an image element", "each caption is a
   separate caption element"를 명시하고 있다 → 프롬프트를 더 강하게 써도 보장이 없다.
3. 매니페스트의 p6·p9는 `text=1(러닝 헤더), img=0, cap=0`. 즉 `_assemble_page_nodes`의 매핑
   버그가 아니라 **gemini가 그 두 페이지에서 시각 요소를 아예 방출하지 않았다** — 확률적 누락.

프롬프트로는 재발을 막을 수 없고, 캡션 텍스트는 PDF 안에 결정적으로 존재한다. 그래서
**PyMuPDF 텍스트 블록에서 캡션을 되살리는 경로**를 넣었다:
`document_manifest.recover_missing_caption_blocks()`, `build_document_manifest` 말미에서 호출.

- 파서가 이미 같은 라벨을 잡은 페이지는 건드리지 않는다(중복 캡션 = "Fig. 1 [2]").
- 라벨 점유는 `_caption_kind`가 캡션으로 인정한 블록만 한다 — 본문 언급이 남아 있는 페이지에서
  진짜 캡션 복원이 막히면 안 된다.
- bbox는 좌하단 원점으로 뒤집어 저장한다(PyMuPDF는 좌상단). 안 뒤집으면 캡션이 페이지
  반대편으로 잡혀 그림 영역 폴백이 위아래로 뒤집힌다. 복원 bbox는 gemini 원본과 일치했다
  (p3: 복원 `[36.0, 158.3, 559.6, 177.6]` vs gemini `[35.6, 158.0, 558.4, 176.9]`).
- `get_text("dict")` 대신 `get_text("blocks")` — 페이지당 19.6ms → 5.8ms.
- 12편 중 **SR_Agile 2건만 복원되고 나머지 11편은 0건**이라 부작용이 없다.

부가 효과: `parser_failed_pages`(PyMuPDF 텍스트로 메운 페이지)의 캡션도 함께 복원되므로
§7의 "실패 페이지 보완 (A) 캡션 복원"이 자연히 해결된다.

---

## 5. 진단 방법론 (그대로 재사용할 것)

**정답 기준**: 원문 본문의 `Figure N` **번호 집합**. 줄머리 캡션만 세면 과소평가된다
(gemini markdown은 캡션이 줄머리에 없다).

> ⚠️ **이 방법론은 그림 전용이다. 표에 그대로 쓰면 안 된다.**
> 아래 스크립트의 `os.environ.pop("GEMINI_API_KEY")`는 그림 경로에선 무해하지만
> (휴리스틱만으로 정답이 나온다), **표 경로는 격자 복원이 VLM에 의존**한다.
> `caption_fallback_crop` 후보는 `text_grid=[]`로 생성되므로(`table_candidates.py:334-368`)
> 키가 없으면 `_repair_with_vlm`이 빈 grid를 그대로 돌려주고(`table_resolver.py:173-174`)
> 최종 필터에서 **구조적으로 100% 탈락**한다. 표는 항상 VLM을 켜고 측정할 것.
> 또한 `TABLE_LABEL_PATTERN`은 digit-only라 **로마 숫자 표(`Table I`)를 통째로 못 본다** —
> 표 정답 기준을 이 정규식으로 세우면 IEEE 논문에서 정답이 0이 된다.
> 상세: `2026-07-31-sasoo-table-accuracy-plan.md`

```python
# sasoo/backend 에서 실행
import asyncio, json, os, re, tempfile
from pathlib import Path
from services.document_manifest import _caption_kind, recover_missing_caption_blocks
from services.figure_candidates import build_figure_candidates
from services.figure_resolver import resolve_figure_candidates
os.environ.pop("GEMINI_API_KEY", None)          # VLM 없이 휴리스틱 경로만
FIG = re.compile(r"\b(?:Figure|Fig\.?)\s*(\d{1,2})\b", re.I)

for d in sorted(Path("library").iterdir()):
    if not (d/".odl_manifest.json").exists(): continue
    pdf = next(d.glob("*.pdf"), None)
    if pdf is None: continue
    m = json.load(open(d/".odl_manifest.json"))
    # 저장된 매니페스트의 kind는 옛 코드 산출물이므로 현재 규칙으로 재계산한다.
    # 주의: `if k: c["kind"] = k`로 쓰면 새 규칙이 None을 낼 때 옛 "figure"가 남아
    # "덜 인정"하는 방향의 변경이 측정에 전혀 반영되지 않는다. 반드시 or "unknown".
    for c in m.get("captions", []):
        c["kind"] = _caption_kind(c.get("text") or "") or "unknown"
    for p in m.get("pages", []):
        for c in p.get("caption_blocks", []):
            c["kind"] = _caption_kind(c.get("text") or "") or "unknown"
    # 저장된 매니페스트는 캡션 복원 이전 산출물이므로 현재 파이프라인과 같게 복원을 태운다
    m.setdefault("captions", []).extend(recover_missing_caption_blocks(
        pdf_path=pdf, pages={p["page_number"]: p for p in m.get("pages", [])}))
    mds = list(d.glob("*.odl-reference.md")) or list(d.glob("*.md"))
    truth = {int(x) for x in FIG.findall(mds[0].read_text(encoding="utf-8", errors="ignore"))
             if 1 <= int(x) <= 30}
    m["figure_candidates"] = build_figure_candidates(m, pdf_path=pdf)
    tmp = Path(tempfile.mkdtemp())
    r = asyncio.run(resolve_figure_candidates(m, paper_dir=tmp, pdf_path=pdf, resolver_version="v"))
    pages = set(r["low_confidence_pages"])
    figs = [f for f in r["figures"] if f["page_number"] not in pages]
    if pages:   # aggressive 재시도까지 재현해야 실제 파이프라인과 같다
        agg = build_figure_candidates(m, pdf_path=pdf, page_numbers=pages, aggressive=True)
        m["figure_candidates"] = [c for c in m["figure_candidates"]
                                  if c["page_number"] not in pages] + agg
        figs += asyncio.run(resolve_figure_candidates(
            m, paper_dir=tmp, pdf_path=pdf, resolver_version="v", page_numbers=pages))["figures"]
    nums = sorted({f["figure_num"] for f in figs})
    print(f'{d.name[:34]:<34} 원문 {len(truth):>2} / 추출 {len(nums):>2}  {nums}')
```

**현재 기준선 (이 수치보다 나빠지면 회귀):**

| 논문 | 원문 | `dafc3f8` | `c22548a` | |
|---|---|---|---|---|
| 2012_ICSOS_SpaceOpticalNetworks | 3 | 3 | 3 | ✅ |
| 2013_IEEETIP_ClusterCoSaliency | 16 | 17 | 16 | ✅ 과제 (2) 해결 |
| 2014_Saliency_Optimization | 9 | 9 | 9 | ✅ |
| 2017_COMST_OpticalComm | 13 | 13 | 13 | ✅ |
| 2019_FourierSpaceDNN | 4 | 4 | 4 | ✅ |
| 2022_ApplOpt_PredictionNet | 8 | 11 | 8 | ✅ 과제 (2) 해결 |
| 2022_SciRep_CoherentFsoLeo | 9 | 10 | 9 | ✅ 과제 (2) 해결 |
| 2025_OptExpress_UplinkPrecomp | 5 | 5 | 5 | ✅ |
| 2025_TurboQuant | 5 | 5 | 5 | ✅ |
| 2026_SR_AgileMultiskill | 8 | 6 | 8 | ✅ 과제 (3) 해결 |
| OptFor_RefractiveMCAO | 8 | 8 | 8 | ✅ |
| TurPy_OpticTurb | 7 | 7 | 7 | ✅ |

**총 절대오차 7 → 0. 12편 전부 정확히 일치.** 이제 목표는 이 12편을 깨지 않는 것이다.

표 추출은 같은 조건에서 총오차 33으로 **변하지 않았다**(회귀 없음). 다만 표 정확도 자체는
낮은 상태로 남아 있다 — 단, 이 33은 정답 기준이 그림만큼 신뢰할 만하지 않다("본문의
`Table N` 언급"이 기준이라, 본문에서 언급 없이 실린 표가 전부 과추출로 계산된다).
표를 손대려면 정답 기준부터 다시 세워야 한다.

---

## 6. 이 프로젝트의 작업 규칙 (직전 세션에서 반복 확인된 것)

1. **신규 테스트는 반드시 구코드/변이 코드에서 실패하는지 확인한 뒤에만 통과로 인정한다.**
   직전 세션에서 픽스처가 실제 조건을 재현 못 해 구코드에서도 통과한 사례가 있었다.
   테스트 안에 "픽스처가 조건을 재현하는지" 먼저 단언하는 줄을 넣으면 좋다.
2. **벤치마크는 `call_interaction`을 통째로 대체하면 안 된다** — 재시도·세마포어를 우회해
   거짓 수치가 나온다. SDK 클라이언트(`interactions_client._get_client`) 레벨에 심을 것.
3. **저장된 매니페스트는 옛 코드 산출물**이다. 그것만 보고 "현재 버그"라고 판단하지 말고,
   현재 코드로 재현해 확인할 것(직전 세션에서 이미 고쳐진 문제를 버그로 오인할 뻔했다).
4. **프론트 테스트는 DOM 없는 순수 로직만**(`vitest.config.ts`의 명시적 규약). 컴포넌트
   렌더 테스트 대신 판정을 순수 함수로 분리해 테스트한다.
5. 병합은 사용자만 한다. **stacked PR을 squash 병합할 때 `--delete-branch`를 쓰면 하위 PR이
   자동 CLOSED 된다** — 직전 세션에서 실제로 발생했고 리베이스로 복구했다. 하위 PR의 base를
   먼저 `main`으로 재타겟할 것.

---

## 7. 그 외 남은 항목 (우선순위 낮음)

- **4코어 Windows 검증**: 스레드풀이 `max(_CPU, LLM동시성+렌더+2)` = 13으로 계산되는 건
  공식 확인만 됨. Windows 릴리스 전 실기 필요.
- **429 재확인**: 12페이지 논문(2웨이브)에서 0건 확인됨. 30페이지급으로 한 번 더 보면 확실.
  되돌리기: `SASOO_PIPELINE_LLM_CONCURRENCY=4 SASOO_GEMINI_PARSER_PAGE_CONCURRENCY=4`
- **실패 페이지 보완(A+B)**: ~~캡션 복원~~ + 구조 전용 재시도.
  (A) 캡션 복원은 `c22548a`의 `recover_missing_caption_blocks`가 파서 실패 페이지까지 함께
  덮으므로 해결됐다. 남은 건 (B) 구조 전용 재시도뿐이고, 실패 페이지가 실제로 관측되지 않아
  우선순위는 여전히 낮다.
- **표 추출 정확도**: 그림과 달리 손대지 않았다. 착수하려면 정답 기준부터 다시 세워야 한다(§5).

---

## 8. 표 추출 정확도 (2026-08-01 완결)

브랜치 `fix/table-accuracy`, `c22548a` → `ba063d4` → `ea2b4e2` → `173208d` → `27e9b8e`.
착수 계획과 사전 분석은 `2026-07-31-sasoo-table-accuracy-plan.md`.

### 8.1 결과

| 지표 | 착수 전 | 완료 |
|---|---|---|
| 표 총오차 (라벨 집합 FP+FN) | 24 | **0** |
| 표 정확일치 | 3/12 | **12/12** |
| 캡션 연결률 | 26% (38개 중 10개) | **100%** |
| 그림 (회귀 확인) | 12/12 | **12/12 유지** |
| 백엔드 테스트 | 441 | 457 |

목표는 "총오차 8 이하 / 정확일치 8편 이상"이었고 그것을 넘었다. 이유는 표가 그림보다
쉬워서가 아니라, **오차 24 중 대부분이 한 가지 구조적 원인(캡션 게이트 부재)에서 나왔기**
때문이다. 병합셀·회전 같은 난이도는 이 코퍼스에서 실제로 문제가 되지 않았다.

### 8.2 정답 기준 — `docs/table_gold.json`

**gold의 정의는 "라벨을 가진 표"다.** 라벨 없이 그림 패널 안에 들어간 격자
(2026_SR_Agile p10의 Fig. 6-Cii)는 그림으로 이미 산출되므로 넣지 않는다 —
라벨 집합 지표(FP/FN)가 성립하지 않기 때문이다.

3개 소스의 **합집합**으로 만들고 육안 검수로 확정했다. 소스마다 맹점이 다르다:
- (A) PDF 텍스트 블록: 캡션이 표 본문 블록과 병합되면 못 본다 (2014_Saliency)
- (B) markdown 캡션형 라벨
- (C) 매니페스트 캡션: 파서의 확률적 누락에 뚫린다 (2017_COMST의 Table II)

총 26개 라벨 / 12편. 생성 스크립트는 `tools/extraction_audit/{collect,build}_table_gold.py`.
**gold는 고정 자산이다 — 코드가 바뀌어도 다시 만들지 말고 그대로 회귀 기준으로 쓴다.**

### 8.3 고친 것

1. **로마 숫자 라벨** (`ea2b4e2`) — `TABLE_LABEL_PATTERN`이 digit-only라 IEEE 계열의
   `Table I`~`Table VIII`을 캡션으로 인정하지 않았다. 2017_COMST는 원문 표 8개인데
   캡션 인정 0개, 후보 9개 전부 무캡션이었다. **캡션 게이트의 선결 조건**이다 —
   로마 지원 없이 게이트를 켜면 그 논문의 진짜 표 8개가 통째로 죽는다.
2. **캡션 필수 게이트 + 라벨 중복제거** (`173208d`) — 아래 §8.4 계약 11·12.
3. **VLM 실패의 무음 삼킴** (`173208d`) — 키 없음·429·파싱 실패·타임아웃이 전부 같은
   결과(빈 grid)로 보여 표가 사라져도 원인을 알 수 없었다. 예외는 계속 삼키되(한 표의
   실패가 문서를 깨면 안 된다) 로그를 남긴다. 전멸 경고도 `figure_resolver`와 동형으로 추가.

### 8.4 깨면 안 되는 계약 (11~13, 기존 1~10에 이어)

11. **캡션 없는 표 후보는 버린다** — 그림 계약 7의 대칭. 무캡션 후보의 정체는 크롭으로
    확인한 결과 대부분 **그래프의 범례 박스**다(2014_Saliency p7의 PR 곡선 범례 9개,
    2013_IEEETIP p8, 2026_SR p12). 범례는 격자 구조라 pdfplumber가 표로 보지만 캡션이
    붙지 않는다. 되돌리면 과추출이 즉시 24로 돌아온다.
12. **중복제거는 캡션 id가 아니라 라벨 기준** — "Table 1 [2]"의 원인이 두 가지고 둘 다
    실측된다: (a) 한 캡션에 후보 여럿(2022_SciRep 3건), (b) 같은 라벨의 캡션 자체가
    중복(2025_TurboQuant p20의 "Table 1"이 2개). 캡션 id 기준으로는 (b)를 못 잡는다.
13. **게이트는 `table_resolver`의 방출 시점에 둔다** — `build_table_candidates`에 넣으면
    `document_audit`이 `table_candidates`를 직접 읽어 suspect page를 판정하므로(계약 3)
    audit 입력이 바뀌고, 그게 다시 **그림** aggressive 재시도까지 흔든다.

### 8.5 표 측정 방법론 (그림과 다르다)

- **표는 항상 VLM을 켜고 잰다.** §5 스크립트의 `os.environ.pop("GEMINI_API_KEY")`는
  **그림 전용**이다. 표의 격자 복원은 본질적으로 VLM에 의존하므로(캡션 폴백 후보는
  `text_grid=[]`로 생성된다) 키를 빼면 결정적으로 100% 탈락한다. 실제로 이 함정 때문에
  "누락 −6"이라는 존재하지 않는 결함을 쫓을 뻔했다 — 키를 넣으니 OptFor는 0 → 5로 살아났다.
- **하네스는 `tools/extraction_audit/measure.py`** (그림+표 동시, 2-lane).
  - `deterministic`(키 없음): VLM 비결정성 없는 진단 — 후보 수, 캡션 인정률, 후보 연결률
  - `production`(키 있음): 최종 FP/FN, 캡션 연결률 — **이쪽이 제품 실동작이다**
- **키는 패키지 앱 DB에 있다.** 개발 DB(`backend/library/sasoo.db`)의 `gemini_api_key`는
  비어 있을 수 있고 실제 키는 `~/Library/Application Support/sasoo/sasoo.db`에 있다.
  `load_api_keys_from_settings(..., worker=True)`로 읽을 것 — `worker=False`는 credential
  store 락을 잡고 사용자 DB에 마이그레이션 UPDATE를 친다. `init_db()`도 쓰지 말 것
  (스키마 마이그레이션 위험) — 읽기 전용 sqlite 연결로 연다.
- **노이즈 바닥을 먼저 재고 그보다 작은 개선은 개선이라 부르지 않는다.**
  캐시를 끄고 3회 반복한 실측: **표 총오차 변동폭 1, 그림 총오차 변동폭 2.**
  VLM 캐시(`--no-cache`로 끔)는 비용이 아니라 재현성 때문에 쓴다.
- 비용은 문제가 아니다. 저장된 매니페스트를 재사용하므로 파싱 재호출이 0이고,
  전 코퍼스 1회가 VLM 호출 ~100건 / 3~20분이다.

### 8.6 이번에 드러난 별건 (표와 무관, 미해결)

1. **그림 서브피겨 라벨이 숫자로 붙으면 부모와 구분되지 않는다.** 2013_IEEETIP에서
   Fig. 12의 서브피겨가 `Fig. 121`~`Fig. 127`로 생성됐다(보통은 `Fig. 11C`처럼 알파벳).
   레코드에는 `parent_figure_num`이 있어 구분되지만, 표시 라벨만 보면 "Figure 121"이라는
   존재하지 않는 그림으로 읽힌다.
2. **그림 정확도는 VLM을 켜면 실행마다 흔들린다(총오차 0~5).** §5의 "12편 정확일치"는
   **결정적 lane(키 없음)** 기준이다. 서브피겨 검출(`_maybe_detect_subfigures`)과 후보
   선택(`_maybe_select_candidate`)이 키가 있을 때만 동작하기 때문이다. 회귀 판정에는
   결정적 lane을 쓰고, 프로덕션 lane은 노이즈 폭(2)을 감안해 읽을 것.
3. **2013_IEEETIP의 저장된 매니페스트에는 페이지 래스터가 없다**(13페이지 전부).
   표의 격자 복원은 래스터가 없으면 VLM을 호출조차 하지 않는다. 하네스는 스크래치에
   래스터를 만들어 보정한다(사용자 라이브러리는 건드리지 않는다). 다른 논문에서 같은
   증상이 보이면 제품 버그로 단정하기 전에 `raster_path`부터 확인할 것.

### 8.7 하지 않기로 한 것

- **오프라인(VLM 없는) 격자 복원기 신설** — 표의 산출물은 csv/html/markdown 격자이고,
  격자 없는 표는 그림과 달리 소비 가능한 산출물이 아니다. "격자 복원이 VLM 의존"은
  결함이 아니라 매체 특성이다. 코퍼스에서 그게 필요한 건 1편뿐이라 투입 대비 회수가 맞지 않는다.
- **VLM 실패 시 캡션+크롭만으로 표를 노출하는 안전망** — 위와 같은 이유로 접었다.
  대신 실패가 로그에 남게 했다(§8.3-3). 필요해지면 그때 다시 판단할 것.
- **pdfplumber `table_settings` 튜닝** — 캡션 게이트로 오차가 0이 되어 손댈 이유가 없다.
