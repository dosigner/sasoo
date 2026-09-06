"""3.7 vs 3.8 Flash A/B: provider_compare를 그대로 쓰되 레지스트리의 FLASH_HQ 항목만 바꿔 끼운다.
사용: ab_flash.py <model> <rep> <stages>
"""
import asyncio, shutil, sys
from pathlib import Path
from dotenv import load_dotenv
BACKEND = Path("/Users/dongj/dev/논문_사수_개발중/sasoo/backend")
load_dotenv(BACKEND / ".env")
sys.path.insert(0, str(BACKEND)); sys.path.insert(0, str(BACKEND / "tools"))

model, rep, stages = sys.argv[1], sys.argv[2], sys.argv[3]
import services.model_registry as reg
from services.models import MODEL_FLASH_HQ
patched = {}
for role, ch in reg._REGISTRY["gemini"].items():
    patched[role] = reg.ModelChoice(model, ch.effort) if ch.model == MODEL_FLASH_HQ else ch
reg._REGISTRY["gemini"] = patched
assert reg.resolve("recipe", "gemini").model == model

import provider_compare as pc
sys.argv = ["provider_compare.py", "--paper-id", "43", "--providers", "gemini", "--stages", stages]
asyncio.run(pc.main_async())
out = pc.OUT_DIR / "summary.json"
dst = Path("/Users/dongj/.claude/jobs/edc48ac3/tmp") / f"ab_{model}_r{rep}.json"
shutil.copy(out, dst); print("saved", dst)
