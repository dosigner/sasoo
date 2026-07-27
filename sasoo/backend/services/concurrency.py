"""
Sasoo - thread-pool and API concurrency budgets.

The analysis pipeline and the chat endpoint used to share asyncio's default
executor, whose size is `min(32, cpu_count + 4)`. A visualization phase fans out
6-10 renders at once and each one holds a thread for its planner call and again
for the render itself, so on the 4-8 core Windows desktop target the pool fills
up. A chat request that lands in that window waits for a free thread with no
timeout: the SSE response opens, emits nothing, and hangs forever.

Chat therefore gets a pool of its own that the pipeline can never touch, and the
pipeline's own fan-out is bounded so it stops melting the shared Gemini/OpenAI
quotas (the OpenAI image API was already returning 429 under the unbounded
mermaid gather).
"""

import asyncio
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from weakref import WeakKeyDictionary

_CPU = os.cpu_count() or 4


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        return default
    return value if value > 0 else default


# Chat only blocks to load the document-context sidecar. Four threads is plenty,
# and reserving them means pipeline load can never starve a user's question.
CHAT_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="sasoo-chat")

# Caps concurrent Gemini calls made by the pipeline. Chat never takes this
# semaphore, so a burst of phase work cannot queue a question behind it.
#
# 4 -> 8: 페이지 단위 비전 파싱이 이 상한에 그대로 묶여 있었다. 30페이지 논문이면
# 4장씩 8웨이브(페이지당 5~15초)라 파싱만 60~120초가 나갔다. 이 값을 올리기 전에
# 재시도 정책 정비(비재시도성 오류 즉시 중단 + 백오프 중 세마포어 반납)가 선행됐다 —
# 429가 늘어도 제대로 백오프되고 대기가 슬롯을 잠그지 않는다.
# 429 관측치에 따라 env로 되돌릴 수 있게 열어 둔다.
PIPELINE_LLM_CONCURRENCY = _env_int("SASOO_PIPELINE_LLM_CONCURRENCY", 8)

# Image renders run up to RENDER_TIMEOUT_S and hold a thread the entire time.
RENDER_CONCURRENCY = 3

# Everything the pipeline blocks on: sync SDK calls, image renders, PDF parsing.
#
# 풀 크기는 CPU가 아니라 "동시에 블로킹될 수 있는 작업 수"로 잡아야 한다. 여기 스레드는
# 대부분 HTTPS 응답을 기다리며 잠들어 있어 CPU를 먹지 않는다. 예전 max(4, min(16, _CPU))는
# 4코어 Windows 데스크톱에서 스레드가 4개뿐이라, LLM 동시성만 8로 올려도 풀에서 다시
# 막혔다. LLM 동시 호출 + 렌더 동시 실행 + 여유 2를 담을 수 있게 바닥을 깐다.
PIPELINE_EXECUTOR = ThreadPoolExecutor(
    max_workers=max(_CPU, PIPELINE_LLM_CONCURRENCY + RENDER_CONCURRENCY + 2),
    thread_name_prefix="sasoo-pipeline",
)

# 루프별 파이프라인 세마포어 레지스트리.
#
# asyncio.Semaphore는 처음으로 acquire()가 실제로 "대기"해야 하는 순간(value<=0)의
# 이벤트 루프에 내부 _loop를 영구 바인딩한다. 단일 프로세스-전역 세마포어를 쓰면,
# gemini 파서가 odl_parser._run_coroutine_sync의 중첩 asyncio.run() 루프에서 pipeline
# LLM 호출로 이 세마포어를 경합하는 동안 메인 FastAPI 루프도 같은 세마포어를 경합하면,
# 먼저 대기 경로를 밟은 루프에 바인딩되고 이후 다른 루프의 모든 pipeline 호출이
# "bound to a different event loop" RuntimeError로 죽는다(figure/table resolver는 폴백도 없다).
#
# 해법: 세마포어를 프로세스 전역이 아니라 "현재 실행 중인 루프별"로 둔다. 루프당 동시성
# 캡(PIPELINE_LLM_CONCURRENCY)은 그대로 유지하면서 크로스루프 바인딩을 원천 제거한다.
# WeakKeyDictionary라 루프가 GC되면 항목도 자동 소멸한다(asyncio.run 종료 후 누수 없음).
_pipeline_llm_sems: "WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = (
    WeakKeyDictionary()
)
_pipeline_llm_sems_lock = threading.Lock()


def pipeline_llm_sem() -> asyncio.Semaphore:
    """현재 실행 중인 이벤트 루프에 바인딩된 파이프라인 LLM 세마포어를 반환한다.

    루프마다 별도 asyncio.Semaphore(PIPELINE_LLM_CONCURRENCY)를 lazily 생성·재사용한다.
    반드시 실행 중인 루프 안에서 호출해야 한다(asyncio.get_running_loop 사용).
    서로 다른 루프(메인 FastAPI 루프 / 중첩 asyncio.run 루프)가 각자의 세마포어를
    쓰므로 크로스루프 바인딩 RuntimeError가 발생하지 않는다.
    """
    loop = asyncio.get_running_loop()
    sem = _pipeline_llm_sems.get(loop)
    if sem is None:
        # 서로 다른 스레드의 루프가 동시에 첫 접근할 수 있으므로 double-checked locking으로
        # 레지스트리(dict) 동시 수정 레이스를 막는다. 세마포어 생성은 루프당 1회뿐이라 경합은 미미.
        with _pipeline_llm_sems_lock:
            sem = _pipeline_llm_sems.get(loop)
            if sem is None:
                sem = asyncio.Semaphore(PIPELINE_LLM_CONCURRENCY)
                _pipeline_llm_sems[loop] = sem
    return sem

# Image renders run up to RENDER_TIMEOUT_S and hold a thread the entire time.
# Keeping this well under the pool size leaves room for the rest of a phase.
RENDER_SEM = asyncio.Semaphore(RENDER_CONCURRENCY)


async def run_pipeline_blocking(fn, *args):
    """Run a blocking pipeline call on the pipeline pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(PIPELINE_EXECUTOR, fn, *args)


async def run_chat_blocking(fn, *args):
    """Run a blocking chat call on the reserved chat pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(CHAT_EXECUTOR, fn, *args)
