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
from concurrent.futures import ThreadPoolExecutor

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
PIPELINE_LLM_SEM = asyncio.Semaphore(4)

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
