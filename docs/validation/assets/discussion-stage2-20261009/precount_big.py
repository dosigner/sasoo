"""경계 크기(약 23만 토큰)에서 계산 API 왕복 시간. 대화 기록 형태의 한국어, 영어 혼합 문장을 반복한다."""
import asyncio, os, sys, time, statistics as st
sys.path.insert(0, os.getcwd())
from tools.provider_compare import load_keys
k = load_keys(); os.environ["OPENAI_API_KEY"] = k["openai"]; os.environ["GEMINI_API_KEY"] = k["gemini"]
from services.llm.interactions_client import count_input_tokens
from services.model_registry import resolve
SYS = "너는 사수야. 논문 원문과 분석 결과를 근거로 답해.\n"
TURN = ("사용자: OT 경로가 diffusion 경로보다 항상 낫다고 봐도 돼? Table 1의 NLL 차이는 얼마야?\n"
        "사수: 논문은 CIFAR-10과 ImageNet에서 OT 경로가 NLL 2.99 대 3.10으로 낫다고 보고했어(Table 1, §6.1). "
        "다만 반복 실험의 오차막대가 없어서 모든 조건에서 우월하다고 일반화하긴 어려워.\n")
async def main():
    for provider in ("openai", "gemini"):
        model = resolve("chat", provider).model
        per = await count_input_tokens(TURN * 100, model=model, system_instruction=SYS) / 100
        prompt = TURN * int(232_000 / per)
        times, vals = [], []
        for _ in range(5):
            t = time.perf_counter()
            vals.append(await count_input_tokens(prompt, model=model, system_instruction=SYS))
            times.append(time.perf_counter() - t)
        print(provider, model, "chars", len(prompt), "tokens", vals[0], "latency median %.2fs max %.2fs min %.2fs" % (st.median(times), max(times), min(times)), flush=True)
asyncio.run(main()); os._exit(0)
