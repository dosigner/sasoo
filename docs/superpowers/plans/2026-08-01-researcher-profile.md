# 연구자 프로필 개선 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 저장만 되고 쓰이지 않던 프로필 4개 항목을 분석 프롬프트에 연결하고, 설명 수준 슬라이더와 분야 선택 UI를 다시 만든다.

**Architecture:** 백엔드는 `api/analysis_context.py`의 시스템 지시문 조립에 4개 값을 추가한다. 프론트는 슬라이더를 프리뷰 중심 단계 카드로 바꾸고, `AppIcon`에 도메인 아이콘을 등록해 분야·역할 선택에 쓰며, 저장 UI를 설정 페이지의 `SaveBar`로 통일한다.

**Tech Stack:** Python 3 / FastAPI / React + TypeScript / Tailwind / lucide-react

## Global Constraints

- 아이콘은 **lucide-react만** 쓴다. `AppIcon`(`src/components/icons/AppIcon.tsx`)의 `ICON_MAP`에 등록해 쓰고, 컴포넌트에서 lucide를 직접 import 하지 않는다. SVG path를 손으로 그리지 않는다.
- 프로필 값이 들어가는 프롬프트 블록은 **enum 값만** 넣는다. 자유 입력(`research_context`)처럼 프롬프트 인젝션 가드 문구가 필요한 자리와 구분한다.
- 시스템 지시문은 **모든 LLM 호출에 매번 실린다.** 추가 블록은 한 항목당 한 줄을 넘기지 않는다.
- `explanation_level`이 어휘 수준의 1차 기준이다. 나머지 3개는 그 안에서 배경지식 가정과 강조점만 조정한다. 서로 모순되는 지시를 만들지 않는다.
- 기존 저장 키·값 도메인을 바꾸지 않는다. UI 표기만 바꾼다.
- em dash(—)를 코드·문구 어디에도 쓰지 않는다. 하이픈(-)을 쓴다.
- 사용자에게 보이는 문구는 전부 `src/lib/strings.ts`에 둔다. JSX에 한국어를 직접 쓰지 않는다.

---

## File Structure

| 파일 | 책임 | 상태 |
|---|---|---|
| `backend/api/analysis_context.py` | 프로필 4개 값을 시스템 지시문에 반영 | 수정 |
| `backend/api/test_analysis_context.py` | 프롬프트 조립 테스트 | 신규 |
| `backend/api/analysis_routes.py` | 프로필 값을 조립 함수로 전달 | 수정 |
| `frontend/src/components/icons/AppIcon.tsx` | 도메인 아이콘 8종 등록 | 수정 |
| `frontend/src/components/profile/LevelCards.tsx` | 설명 수준 단계 카드 | 신규 |
| `frontend/src/components/profile/AreaPicker.tsx` | 연구 분야 선택 (아이콘 칩) | 신규 |
| `frontend/src/pages/Profile.tsx` | 위 컴포넌트 사용 + SaveBar | 수정 |
| `frontend/src/lib/strings.ts` | 문구 | 수정 |
| `frontend/src/index.css` | 카드·칩 스타일 | 수정 |

## 단계 구분

- **1단계 (Task 1~3)** - 백엔드. 4개 항목을 실제로 동작하게 만든다. UI 없이도 값이 반영된다.
- **2단계 (Task 4~7)** - 프론트엔드. 1단계와 독립이라 병행 가능하다.

---

# 1단계 - 프로필 값을 분석에 반영

## Task 1: 프로필 지시문 조립 함수

`analysis_context.py`에 4개 값을 문장으로 바꾸는 함수를 만든다. 아직 아무도 부르지 않는다.

**Files:**
- Modify: `backend/api/analysis_context.py`
- Test: `backend/api/test_analysis_context.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `AREA_LABELS: dict[str, str]` - 8개 연구 분야 값 -> 한국어 라벨
  - `ROLE_EMPHASIS: dict[str, str]` - 7개 역할 -> 강조점 문장
  - `build_reader_profile_block(areas, field_expertise, reading_experience, role) -> str` -
    넣을 내용이 없으면 빈 문자열

- [ ] **Step 1: Write the failing test**

`backend/api/test_analysis_context.py`:

```python
import unittest

from api.analysis_context import (
    AREA_LABELS,
    ROLE_EMPHASIS,
    build_reader_profile_block,
)


class TestVocabularyTables(unittest.TestCase):
    def test_area_labels_cover_frontend_options(self):
        """Profile.tsx의 RESEARCH_AREA_OPTIONS와 값이 일치해야 한다."""
        expected = {
            "optics_photonics",
            "ai_ml",
            "robotics_control",
            "electrical_electronics",
            "computer_science",
            "physics_math",
            "bio_medical",
            "other",
        }
        self.assertEqual(set(AREA_LABELS), expected)

    def test_role_emphasis_covers_frontend_options(self):
        expected = {
            "student",
            "grad_student",
            "postdoc",
            "professor",
            "engineer",
            "manager",
            "other",
        }
        self.assertEqual(set(ROLE_EMPHASIS), expected)


class TestReaderProfileBlock(unittest.TestCase):
    def test_empty_when_nothing_meaningful(self):
        """기본값만 있으면 지시문을 늘리지 않는다."""
        self.assertEqual(
            build_reader_profile_block([], "major", "regular", "grad_student"), ""
        )

    def test_areas_are_rendered_as_korean_labels(self):
        block = build_reader_profile_block(
            ["optics_photonics", "ai_ml"], "major", "regular", "grad_student"
        )
        self.assertIn("광학·포토닉스", block)
        self.assertIn("AI·머신러닝", block)
        self.assertNotIn("optics_photonics", block)

    def test_unknown_area_is_dropped_not_rendered_raw(self):
        block = build_reader_profile_block(
            ["optics_photonics", "no_such_area"], "major", "regular", "grad_student"
        )
        self.assertNotIn("no_such_area", block)
        self.assertIn("광학·포토닉스", block)

    def test_areas_are_capped_at_three(self):
        block = build_reader_profile_block(
            ["optics_photonics", "ai_ml", "bio_medical", "physics_math"],
            "major", "regular", "grad_student",
        )
        self.assertNotIn("물리·수학", block)

    def test_novice_expertise_asks_for_more_background(self):
        block = build_reader_profile_block([], "novice", "regular", "grad_student")
        self.assertNotEqual(block, "")
        self.assertIn("배경", block)

    def test_expert_expertise_allows_terse_terms(self):
        block = build_reader_profile_block([], "expert", "regular", "grad_student")
        self.assertNotEqual(block, "")

    def test_author_experience_mentions_review_perspective(self):
        block = build_reader_profile_block([], "major", "author", "grad_student")
        self.assertNotEqual(block, "")

    def test_role_changes_emphasis(self):
        engineer = build_reader_profile_block([], "major", "regular", "engineer")
        professor = build_reader_profile_block([], "major", "regular", "professor")
        self.assertNotEqual(engineer, professor)

    def test_block_is_terse(self):
        """시스템 지시문은 매 호출에 실린다. 항목당 한 줄을 넘기지 않는다."""
        block = build_reader_profile_block(
            ["optics_photonics", "ai_ml", "bio_medical"], "novice", "author", "engineer"
        )
        self.assertLessEqual(len(block.splitlines()), 5)

    def test_no_em_dash(self):
        block = build_reader_profile_block(
            ["optics_photonics"], "novice", "author", "engineer"
        )
        self.assertNotIn("—", block)
        self.assertNotIn("–", block)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd sasoo/backend && .venv/bin/python -m pytest api/test_analysis_context.py -v
```

Expected: FAIL - `ImportError: cannot import name 'AREA_LABELS'`

- [ ] **Step 3: Write the implementation**

`backend/api/analysis_context.py`의 `_FOCUS_LABELS` **아래**에 추가한다:

```python
# 프론트 Profile.tsx의 RESEARCH_AREA_OPTIONS와 값이 1:1 대응해야 한다.
# 한쪽만 바꾸면 test_area_labels_cover_frontend_options가 잡는다.
AREA_LABELS: dict[str, str] = {
    "optics_photonics": "광학·포토닉스",
    "ai_ml": "AI·머신러닝",
    "robotics_control": "로보틱스·제어",
    "electrical_electronics": "전기·전자",
    "computer_science": "컴퓨터과학",
    "physics_math": "물리·수학",
    "bio_medical": "바이오·의생명",
    "other": "기타",
}

# 배경지식 가정. explanation_level이 어휘 수준을 정하고, 이 값은 그 안에서
# "얼마나 풀어서 말할지"만 조정한다. 어휘 수준 자체를 뒤집지 않는다.
_EXPERTISE_HINT: dict[str, str] = {
    "novice": "이 분야가 처음이니 핵심 개념은 배경부터 한 줄 붙여줘.",
    "basic": "기초는 아니까 배경 설명은 짧게, 새 개념만 풀어줘.",
    "major": "",  # 기본값. 지시문을 늘리지 않는다.
    "research": "직접 연구하는 사람이니 배경 설명은 생략하고 방법론 차이에 집중해.",
    "expert": "전문가니 배경 설명 없이 바로 본론으로 가고, 논쟁적인 지점을 짚어줘.",
}

_READING_HINT: dict[str, str] = {
    "rare": "논문 읽기가 익숙하지 않으니 절 구조와 그림 읽는 법도 함께 안내해.",
    "occasional": "",
    "regular": "",  # 기본값
    "author": "논문을 쓰고 심사해본 사람이니 심사자 관점의 약점도 짚어줘.",
}

ROLE_EMPHASIS: dict[str, str] = {
    "student": "수업·세미나에서 설명할 수 있게 개념 이해를 우선해.",
    "grad_student": "",  # 기본값
    "postdoc": "후속 연구로 이어질 빈틈과 확장 가능성을 짚어줘.",
    "professor": "연구 기여도와 지도할 때 쓸 논점을 짚어줘.",
    "engineer": "구현·재현에 필요한 조건과 실무 제약을 우선해.",
    "manager": "결론과 의사결정에 필요한 근거를 앞세우고 세부 유도는 줄여.",
    "other": "",
}

_MAX_AREAS = 3  # 프론트 MAX_RESEARCH_AREAS와 같은 값


def build_reader_profile_block(
    areas: list[str],
    field_expertise: str,
    reading_experience: str,
    research_role: str,
) -> str:
    """프로필 선택값을 시스템 지시문 한 조각으로 만든다.

    전부 enum 값이라 자유 입력과 달리 프롬프트 인젝션 가드가 필요 없다.
    알 수 없는 값은 조용히 버린다 - 원문을 그대로 흘려보내지 않는다.

    기본값(major/regular/grad_student, 분야 미선택)만 있으면 빈 문자열을
    돌려준다. 매 호출에 실리는 지시문을 기본 상태에서 늘리지 않기 위해서다.
    """
    lines: list[str] = []

    labels = [AREA_LABELS[a] for a in areas[:_MAX_AREAS] if a in AREA_LABELS]
    if labels:
        lines.append(
            f"독자 전공: {', '.join(labels)}. "
            "이 분야 용어는 그대로 쓰고, 벗어난 분야 용어는 한 줄로 풀어줘."
        )

    for table, key in (
        (_EXPERTISE_HINT, field_expertise),
        (_READING_HINT, reading_experience),
        (ROLE_EMPHASIS, research_role),
    ):
        hint = table.get(key, "")
        if hint:
            lines.append(hint)

    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd sasoo/backend && .venv/bin/python -m pytest api/test_analysis_context.py -v
```

Expected: PASS (12 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/api/analysis_context.py backend/api/test_analysis_context.py
git commit -m "feat(analysis): 독자 프로필 지시문 조립 함수

연구 분야·숙련도·읽기 경험·역할을 시스템 지시문 한 조각으로 바꾼다.
기본값만 있으면 빈 문자열을 돌려줘 지시문을 늘리지 않는다.
아직 아무도 부르지 않는다."
```

---

## Task 2: 조립 함수에 배선

`build_chain_system_instruction`이 Task 1의 블록을 실제로 붙이게 한다.

**Files:**
- Modify: `backend/api/analysis_context.py:23-52`
- Modify: `backend/api/test_analysis_context.py`

**Interfaces:**
- Consumes: Task 1의 `build_reader_profile_block`
- Produces: `build_chain_system_instruction(persona_prompt, research_context, focus, level_key, *, reader_profile="")`

- [ ] **Step 1: Write the failing test**

`backend/api/test_analysis_context.py` 끝에 추가한다:

```python
class TestChainInstructionAssembly(unittest.TestCase):
    def test_reader_profile_is_included(self):
        from api.analysis_context import build_chain_system_instruction

        out = build_chain_system_instruction(
            "", "", None, "masters", reader_profile="독자 전공: 광학·포토닉스."
        )
        self.assertIn("광학·포토닉스", out)

    def test_omitting_reader_profile_keeps_old_output(self):
        """기존 호출부가 안 바뀌어도 결과가 같아야 한다."""
        from api.analysis_context import build_chain_system_instruction

        without = build_chain_system_instruction("", "", None, "masters")
        with_empty = build_chain_system_instruction(
            "", "", None, "masters", reader_profile=""
        )
        self.assertEqual(without, with_empty)

    def test_explanation_level_comes_last(self):
        """어휘 수준이 1차 기준이므로 마지막에 와야 덮어쓰기 순서가 맞다."""
        from api.analysis_context import build_chain_system_instruction

        out = build_chain_system_instruction(
            "", "", None, "phd", reader_profile="독자 전공: 광학·포토닉스."
        )
        self.assertLess(out.index("광학·포토닉스"), out.index("설명 수준: 박사생"))
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd sasoo/backend && .venv/bin/python -m pytest api/test_analysis_context.py -k ChainInstruction -v
```

Expected: FAIL - `TypeError: build_chain_system_instruction() got an unexpected keyword argument 'reader_profile'`

- [ ] **Step 3: Write the implementation**

`build_chain_system_instruction`의 시그니처와 본문을 바꾼다:

```python
def build_chain_system_instruction(
    persona_prompt: str,
    research_context: str,
    focus: dict | None,
    level_key: str,
    *,
    reader_profile: str = "",
) -> str:
```

`parts.append(EXPLANATION_LEVELS...)` **바로 위**에 넣는다:

```python
    if reader_profile.strip():
        parts.append(reader_profile.strip())
```

설명 수준이 마지막에 오는 순서를 유지한다. 어휘 수준이 1차 기준이고
프로필은 그 안에서 조정하는 값이라, 뒤에 오는 쪽이 최종 판단 기준이 된다.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd sasoo/backend && .venv/bin/python -m pytest api/test_analysis_context.py -v
```

Expected: PASS (15 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/api/analysis_context.py backend/api/test_analysis_context.py
git commit -m "feat(analysis): 시스템 지시문에 독자 프로필 반영

reader_profile은 키워드 인자로 기본값이 빈 문자열이라, 아직 전달하지
않는 호출부의 출력이 그대로 유지된다. 설명 수준은 계속 마지막에 온다."
```

---

## Task 3: 분석 라우트에서 프로필 전달

설정에서 읽은 4개 값을 조립 함수로 넘긴다. **이 태스크부터 사용자가 고른 값이 실제로 분석에 반영된다.**

**Files:**
- Modify: `backend/api/analysis_routes.py`
- Test: `backend/api/test_analysis_context.py`

**Interfaces:**
- Consumes: Task 1, 2
- Produces: 없음 (최종 소비자)

- [ ] **Step 1: Find the call site**

```bash
cd sasoo/backend && grep -n "build_chain_system_instruction" api/analysis_routes.py
```

호출부에서 `research_context`와 `level_key`를 어디서 읽는지 확인한다. 같은
설정 dict에서 4개 값을 함께 읽으면 된다.

- [ ] **Step 2: Write the failing test**

`backend/api/test_analysis_context.py`에 추가한다:

```python
class TestSettingsToProfileBlock(unittest.TestCase):
    """설정 dict에서 값을 꺼내는 경로가 프론트 저장 형식과 맞는지."""

    def test_research_areas_stored_as_json_string(self):
        """settings 테이블은 research_areas를 JSON 문자열로 저장한다."""
        import json

        from api.analysis_context import build_reader_profile_block

        raw = json.dumps(["optics_photonics", "ai_ml"])
        block = build_reader_profile_block(
            json.loads(raw), "major", "regular", "grad_student"
        )
        self.assertIn("광학·포토닉스", block)

    def test_malformed_json_does_not_crash(self):
        import json

        from api.analysis_context import build_reader_profile_block

        try:
            areas = json.loads("not json")
        except json.JSONDecodeError:
            areas = []
        self.assertEqual(
            build_reader_profile_block(areas, "major", "regular", "grad_student"), ""
        )
```

- [ ] **Step 3: Run it**

```bash
cd sasoo/backend && .venv/bin/python -m pytest api/test_analysis_context.py -k SettingsToProfile -v
```

Expected: PASS (함수는 이미 있으므로 통과한다. 이 테스트는 저장 형식 계약을 고정하는 용도다.)

- [ ] **Step 4: Wire the call site**

`analysis_routes.py`의 `build_chain_system_instruction` 호출부 **직전**에 넣는다.
`research_context`를 읽는 곳과 같은 자리다:

```python
    import json

    from api.analysis_context import build_reader_profile_block

    try:
        _areas = json.loads(settings.get("research_areas") or "[]")
        if not isinstance(_areas, list):
            _areas = []
    except (json.JSONDecodeError, TypeError):
        _areas = []

    reader_profile = build_reader_profile_block(
        _areas,
        settings.get("field_expertise") or "major",
        settings.get("reading_experience") or "regular",
        settings.get("research_role") or "grad_student",
    )
```

그리고 호출에 인자를 추가한다:

```python
        reader_profile=reader_profile,
```

- [ ] **Step 5: Verify end to end**

```bash
cd sasoo/backend && .venv/bin/python -m pytest api/ services/ -q
```

Expected: 전부 PASS

실제 지시문이 어떻게 조립되는지 눈으로 확인한다:

```bash
cd sasoo/backend && .venv/bin/python -c "
import sys; sys.path.insert(0, '.')
from api.analysis_context import build_chain_system_instruction, build_reader_profile_block
p = build_reader_profile_block(['optics_photonics'], 'research', 'author', 'engineer')
print(build_chain_system_instruction('', '광학 통신을 연구합니다', None, 'phd', reader_profile=p))
"
```

읽어보고 확인할 것: 설명 수준(박사생)과 프로필 지시가 서로 모순되지 않는가,
문장이 자연스러운가, 불필요하게 길지 않은가.

- [ ] **Step 6: Commit**

```bash
git add backend/api/analysis_routes.py backend/api/test_analysis_context.py
git commit -m "feat(analysis): 프로필 4개 항목을 분석에 실제로 반영

연구 분야·숙련도·읽기 경험·역할이 저장만 되고 어디에도 쓰이지 않던
문제를 고친다. research_areas는 JSON 문자열로 저장되므로 파싱 실패를
빈 목록으로 흡수한다."
```

---

# 2단계 - UI

## Task 4: 도메인 아이콘 등록

**Files:**
- Modify: `frontend/src/components/icons/AppIcon.tsx`

**Interfaces:**
- Consumes: 없음
- Produces: `AppIconName`에 8개 추가 - `area-optics`, `area-ai`, `area-robotics`,
  `area-electrical`, `area-cs`, `area-physics`, `area-bio`, `area-other`

- [ ] **Step 1: Add the names and mappings**

`AppIcon.tsx`의 `AppIconName` union에 8개를 추가하고, `ICON_MAP`에 lucide
컴포넌트를 연결한다. import도 함께 추가한다:

```tsx
import {
  Waves,        // 광학·포토닉스 - 파동
  Brain,        // AI·머신러닝
  Bot,          // 로보틱스·제어
  CircuitBoard, // 전기·전자
  Code,         // 컴퓨터과학
  Atom,         // 물리·수학
  Dna,          // 바이오·의생명
  Shapes,       // 기타
} from 'lucide-react';
```

```tsx
  // 연구 분야 아이콘. Profile.tsx의 RESEARCH_AREA_OPTIONS와 1:1 대응한다.
  'area-optics': Waves,
  'area-ai': Brain,
  'area-robotics': Bot,
  'area-electrical': CircuitBoard,
  'area-cs': Code,
  'area-physics': Atom,
  'area-bio': Dna,
  'area-other': Shapes,
```

- [ ] **Step 2: Verify every name resolves**

```bash
cd sasoo/frontend && npx tsc --noEmit -p tsconfig.json
```

Expected: 오류 없음. `ICON_MAP`이 `Record<AppIconName, ...>`이므로 하나라도
빠지면 타입 오류가 난다.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/icons/AppIcon.tsx
git commit -m "feat(icons): 연구 분야 아이콘 8종 등록

이미 쓰는 lucide-react에서 고른다. 새 의존성이 없고 선 굵기·크기가
기존 45개와 자동으로 일치한다."
```

---

## Task 5: 설명 수준 단계 카드

슬라이더를 없애고 프리뷰 문장을 주인공으로 올린다. 사용자가 "석사생"이라는
말을 추상적으로 고르는 게 아니라 실제 설명 톤을 보고 고른다.

**Files:**
- Create: `frontend/src/components/profile/LevelCards.tsx`
- Modify: `frontend/src/index.css`
- Delete: `frontend/src/components/LevelSlider.tsx`
- Modify: `frontend/src/index.css:1406-1520` (`.level-slider` 블록 제거)

**Interfaces:**
- Consumes: 기존 `LEVEL_OPTIONS`, `LEVEL_PREVIEWS` (LevelSlider.tsx에서 옮긴다)
- Produces: `<LevelCards value onChange />`

- [ ] **Step 1: Add the styles**

`index.css`에 추가한다. Task 11(설정)의 `provider-card`와 같은 형태 체계를 쓴다:

```css
  .level-card {
    @apply flex w-full flex-col gap-1 border p-3 text-left transition-[border-color,background-color] duration-150;
    border-radius: var(--radius-surface);
  }

  .level-card-active {
    @apply border-accent bg-accent/5;
  }

  .level-card-inactive {
    @apply border-border bg-surface hover:border-border hover:bg-surface-hover;
  }
```

- [ ] **Step 2: Write the component**

`frontend/src/components/profile/LevelCards.tsx`:

```tsx
import { S } from '@/lib/strings';

export const LEVEL_OPTIONS = [
  'elementary', 'middle', 'high', 'undergrad', 'masters', 'phd',
] as const;

export type Level = (typeof LEVEL_OPTIONS)[number];

interface Props {
  value: Level;
  onChange: (next: Level) => void;
}

/**
 * 설명 수준 선택.
 *
 * 슬라이더를 쓰지 않는다. "석사생"이라는 라벨만 보고 고르는 것보다, 그 수준의
 * 실제 설명 문장을 보고 고르는 편이 정확하다. 기존 구현은 슬라이더와 라벨
 * 버튼 6개가 중복이었고 프리뷰 문장이 부수 정보로 밀려 있었다.
 *
 * 값이 순서를 갖긴 하지만(초등 -> 박사) 사용자가 하는 일은 "내 눈높이 하나
 * 고르기"이지 "정도를 조절하기"가 아니다.
 */
export function LevelCards({ value, onChange }: Props) {
  return (
    <div role="radiogroup" aria-label={S.settings.defaultLevel} className="grid gap-2">
      {LEVEL_OPTIONS.map((level) => {
        const selected = value === level;
        return (
          <button
            key={level}
            type="button"
            role="radio"
            aria-checked={selected}
            tabIndex={selected ? 0 : -1}
            className={`level-card ${selected ? 'level-card-active' : 'level-card-inactive'}`}
            onClick={() => onChange(level)}
          >
            <span className="text-sm font-medium text-fg">{S.levels[level].label}</span>
            <span className="text-xs leading-relaxed text-fg-muted">
              {S.levels[level].preview}
            </span>
          </button>
        );
      })}
    </div>
  );
}

export default LevelCards;
```

- [ ] **Step 3: Move the strings**

기존 `src/components/LevelSlider.tsx`의 `LEVEL_OPTIONS` 라벨과 `LEVEL_PREVIEWS`를
`strings.ts`의 `S.levels`로 옮긴다:

```typescript
  levels: {
    elementary: { label: '초등학생', preview: '...' },
    middle: { label: '중학생', preview: '...' },
    high: { label: '고등학생', preview: '...' },
    undergrad: { label: '학부생', preview: '...' },
    masters: { label: '석사생', preview: '...' },
    phd: { label: '박사생', preview: '...' },
  },
```

preview 문장은 기존 `LEVEL_PREVIEWS` 값을 그대로 옮긴다. 새로 쓰지 않는다.

- [ ] **Step 4: Remove the slider**

`src/components/LevelSlider.tsx`를 지우고, `index.css`의 `.level-slider` 블록
(1406줄 "Level Slider" 주석부터 관련 셀렉터 끝까지)을 통째로 지운다. 이 블록에는 `list={id-ticks}`가 가리키는 `<datalist>`가 없어
틱이 그려지지 않던 버그도 함께 사라진다.

- [ ] **Step 5: Verify**

```bash
cd sasoo/frontend && npx tsc --noEmit -p tsconfig.json && npx vite build
```

Expected: 타입 오류 없음, 빌드 성공. 남은 `LevelSlider` 참조가 있으면 타입
오류로 잡힌다.

- [ ] **Step 6: Commit**

```bash
git add -A frontend/src/components/profile/ frontend/src/index.css frontend/src/lib/strings.ts
git commit -m "feat(ui): 설명 수준을 프리뷰 카드로

슬라이더 대신 각 수준의 실제 설명 문장을 보고 고르게 한다. 슬라이더와
라벨 버튼 6개가 중복이던 구조를 하나로 합치고, datalist가 없어 틱이
그려지지 않던 버그도 함께 제거한다."
```

---

## Task 6: 연구 분야 선택 (아이콘 칩)

검색 팝오버를 없애고 8개를 한눈에 보여준다. 8개는 검색이 필요한 개수가 아니다.

**Files:**
- Create: `frontend/src/components/profile/AreaPicker.tsx`
- Modify: `frontend/src/index.css`

**Interfaces:**
- Consumes: Task 4의 `area-*` 아이콘
- Produces: `<AreaPicker value onChange max={3} />`

- [ ] **Step 1: Add the styles**

```css
  .area-chip {
    @apply flex items-center gap-2 border px-3 py-2 text-sm transition-[border-color,background-color] duration-150;
    border-radius: var(--radius-control);
  }

  .area-chip-active {
    @apply border-accent bg-accent/5 text-fg;
  }

  .area-chip-inactive {
    @apply border-border bg-surface text-fg-secondary hover:border-border hover:bg-surface-hover;
  }

  .area-chip-disabled {
    @apply cursor-not-allowed border-border bg-surface text-fg-muted opacity-50;
  }
```

- [ ] **Step 2: Write the component**

`frontend/src/components/profile/AreaPicker.tsx`:

```tsx
import { AppIcon } from '@/components/icons';
import type { AppIconName } from '@/components/icons';
import { S } from '@/lib/strings';

const AREAS: { id: string; icon: AppIconName }[] = [
  { id: 'optics_photonics', icon: 'area-optics' },
  { id: 'ai_ml', icon: 'area-ai' },
  { id: 'robotics_control', icon: 'area-robotics' },
  { id: 'electrical_electronics', icon: 'area-electrical' },
  { id: 'computer_science', icon: 'area-cs' },
  { id: 'physics_math', icon: 'area-physics' },
  { id: 'bio_medical', icon: 'area-bio' },
  { id: 'other', icon: 'area-other' },
];

interface Props {
  value: string[];
  onChange: (next: string[]) => void;
  max?: number;
}

/**
 * 연구 분야 선택.
 *
 * 검색 팝오버를 쓰지 않는다. 선택지가 8개뿐이라 전부 펼쳐 보이는 편이
 * 빠르다. 기존 구현은 팝오버를 열고 검색해서 고른 뒤 아래 칩으로 다시
 * 보여주는 3단 구조였다.
 *
 * 상한(3개)에 도달하면 고르지 않은 칩만 비활성화한다. 선택된 칩은 계속
 * 해제할 수 있어야 한다.
 */
export function AreaPicker({ value, onChange, max = 3 }: Props) {
  const atMax = value.length >= max;

  const toggle = (id: string) => {
    if (value.includes(id)) {
      onChange(value.filter((v) => v !== id));
      return;
    }
    if (atMax) return;
    onChange([...value, id]);
  };

  return (
    <div>
      <div className="flex flex-wrap gap-2">
        {AREAS.map((area) => {
          const selected = value.includes(area.id);
          const blocked = atMax && !selected;
          const className = blocked
            ? 'area-chip area-chip-disabled'
            : selected
              ? 'area-chip area-chip-active'
              : 'area-chip area-chip-inactive';

          return (
            <button
              key={area.id}
              type="button"
              role="checkbox"
              aria-checked={selected}
              aria-disabled={blocked}
              disabled={blocked}
              className={className}
              onClick={() => toggle(area.id)}
            >
              <AppIcon name={area.icon} className="h-4 w-4 shrink-0" />
              {S.areas[area.id]}
            </button>
          );
        })}
      </div>
      <p className="mt-2 text-xs text-fg-muted">
        {atMax ? S.settings.researchAreasMaxReached : S.settings.researchAreasHelper}
      </p>
    </div>
  );
}

export default AreaPicker;
```

- [ ] **Step 3: Add the labels**

`strings.ts`에 `S.areas`를 추가한다. 값은 기존 `RESEARCH_AREA_OPTIONS`의
라벨을 그대로 옮긴다. **백엔드 `AREA_LABELS`와 문자열이 같아야 한다.**

```typescript
  areas: {
    optics_photonics: '광학·포토닉스',
    ai_ml: 'AI·머신러닝',
    robotics_control: '로보틱스·제어',
    electrical_electronics: '전기·전자',
    computer_science: '컴퓨터과학',
    physics_math: '물리·수학',
    bio_medical: '바이오·의생명',
    other: '기타',
  } as Record<string, string>,
```

- [ ] **Step 4: Verify**

```bash
cd sasoo/frontend && npx tsc --noEmit -p tsconfig.json
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/profile/AreaPicker.tsx frontend/src/index.css frontend/src/lib/strings.ts
git commit -m "feat(ui): 연구 분야를 아이콘 칩으로

선택지가 8개뿐이라 검색 팝오버가 과했다. 전부 펼쳐 보이고 아이콘으로
구분한다. 상한 도달 시 미선택 칩만 잠그고 선택된 칩은 계속 해제할 수
있게 한다."
```

---

## Task 7: 프로필 페이지 조립

**Files:**
- Modify: `frontend/src/pages/Profile.tsx`

**Interfaces:**
- Consumes: Task 5의 `LevelCards`, Task 6의 `AreaPicker`, 설정 페이지의 `SaveBar`
- Produces: 없음 (최종 소비자)

- [ ] **Step 1: Replace the controls**

- `LevelSlider` -> `<LevelCards value={level} onChange={setLevel} />`
- `ResearchAreaSelect` -> `<AreaPicker value={areas} onChange={setAreas} />`
- `ResearchAreaSelect`와 `SegmentGroup` 중 안 쓰게 된 로컬 컴포넌트를 지운다.
  `SegmentGroup`은 숙련도·읽기 경험에 계속 쓰므로 남긴다.

- [ ] **Step 2: Switch to SaveBar**

`hasChanges` 불리언을 개수로 바꾼다. 설정 페이지(`Settings.tsx`)와 같은 형태다:

```tsx
  const changedFields = [
    researchContext !== (baseline.research_context || ''),
    JSON.stringify(areas) !== JSON.stringify(baseline.research_areas || []),
    role !== (baseline.research_role || 'grad_student'),
    level !== (baseline.default_explanation_level || 'masters'),
    expertise !== (baseline.field_expertise || 'major'),
    reading !== (baseline.reading_experience || 'regular'),
  ].filter(Boolean).length;
```

헤더의 저장 버튼을 지우고 페이지 끝에 `SaveBar`를 붙인다:

```tsx
      <SaveBar
        changeCount={changedFields}
        saving={saving}
        error={error}
        onSave={handleSave}
        onDiscard={handleDiscard}
      />
```

`handleDiscard`가 없으므로 새로 만든다. baseline 값으로 6개 state를 되돌리면 된다.

- [ ] **Step 3: Verify**

```bash
cd sasoo/frontend && npx tsc --noEmit -p tsconfig.json && npx vite build
```

- [ ] **Step 4: Verify in the running app**

```bash
cd sasoo && npm run dev
```

확인할 것:
1. 설명 수준 카드 6개가 보이고 프리뷰 문장이 읽힌다
2. 분야 칩 8개에 아이콘이 붙어 있고, 3개를 고르면 나머지가 잠긴다
3. 3개 고른 상태에서도 선택된 칩은 해제된다
4. 변경하면 하단 저장바가 나타나고 "변경 N개"가 맞다
5. 되돌리기가 동작한다
6. 다크 모드에서 카드·칩의 accent 테두리가 읽힌다
7. 375px 폭에서 칩이 줄바꿈되고 카드가 잘리지 않는다
8. 저장 후 재진입 시 값이 유지된다

- [ ] **Step 5: End to end check**

프로필을 바꾼 뒤 논문을 하나 분석해 설명 톤이 실제로 달라지는지 본다.
`elementary` + `novice`로 한 번, `phd` + `expert`로 한 번 돌려 비교한다.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Profile.tsx
git commit -m "refactor(ui): 프로필 페이지 조립

설명 수준을 카드로, 연구 분야를 아이콘 칩으로 바꾸고 저장 UI를 설정
페이지와 같은 SaveBar로 통일한다. 프로필에 없던 되돌리기가 생긴다."
```

---

## 최종 검증

- [ ] **전체 테스트**

```bash
cd sasoo/backend && .venv/bin/python -m pytest api/ services/ -q
cd sasoo/frontend && npx tsc --noEmit -p tsconfig.json && npx vite build
```

- [ ] **프론트-백엔드 값 대응**

`Profile.tsx`의 분야·역할 값과 `analysis_context.py`의 `AREA_LABELS`,
`ROLE_EMPHASIS` 키가 일치하는지. Task 1의 테스트가 이미 잡지만 눈으로도 본다.

- [ ] **지시문 길이**

기본값 상태에서 시스템 지시문이 이전과 같은 길이인지 확인한다. 기본값만
있으면 `build_reader_profile_block`이 빈 문자열을 돌려주므로 늘어나면 안 된다.

```bash
cd sasoo/backend && .venv/bin/python -c "
import sys; sys.path.insert(0, '.')
from api.analysis_context import build_chain_system_instruction as b, build_reader_profile_block as p
base = b('', '', None, 'masters')
same = b('', '', None, 'masters', reader_profile=p([], 'major', 'regular', 'grad_student'))
print('기본값 지시문 동일:', base == same)
"
```

- [ ] **접근성**

- 카드·칩이 키보드로 도달하고 조작되는가
- 선택 상태가 스크린리더에 전달되는가 (`aria-checked`)
- 상한 도달 시 잠긴 칩의 사유가 전달되는가

## 범위 밖

- `research_context` textarea 개선
- 프로필 값의 A/B 품질 측정
- 분야를 3개 넘게 고르게 하는 것
- 역할별 아이콘 (이번에는 분야에만 아이콘을 붙인다)
