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

# Chat only blocks to load the document-context sidecar. Four threads is plenty,
# and reserving them means pipeline load can never starve a user's question.
CHAT_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="sasoo-chat")

# Everything the pipeline blocks on: sync SDK calls, image renders, PDF parsing.
PIPELINE_EXECUTOR = ThreadPoolExecutor(
    max_workers=max(4, min(16, _CPU)),
    thread_name_prefix="sasoo-pipeline",
)

# Caps concurrent Gemini calls made by the pipeline. Chat never takes this
# semaphore, so a burst of phase work cannot queue a question behind it.
PIPELINE_LLM_CONCURRENCY = 4

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
RENDER_SEM = asyncio.Semaphore(3)


async def run_pipeline_blocking(fn, *args):
    """Run a blocking pipeline call on the pipeline pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(PIPELINE_EXECUTOR, fn, *args)


async def run_chat_blocking(fn, *args):
    """Run a blocking chat call on the reserved chat pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(CHAT_EXECUTOR, fn, *args)
