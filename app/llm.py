"""Model-agnostic LLM client.

Only open, self-hostable runtimes are supported so the solution never locks
C4IR / MINAGRI / RAB into a proprietary vendor:
  - ollama        : local open-weight models (Llama, Qwen, Gemma, ...)
  - openai_compat : any OpenAI-compatible server (vLLM, llama.cpp, TGI, LocalAI)
  - none          : no generation; the advisor returns curated text verbatim
"""
import httpx

from . import config


class LLMUnavailable(Exception):
    pass


def model_name() -> str:
    return "none" if config.LLM_PROVIDER == "none" else f"{config.LLM_PROVIDER}:{config.LLM_MODEL}"


def chat(system: str, user: str, max_tokens: int = 350) -> str:
    provider = config.LLM_PROVIDER
    try:
        if provider == "ollama":
            r = httpx.post(
                f"{config.LLM_BASE_URL.rstrip('/')}/api/chat",
                json={
                    "model": config.LLM_MODEL,
                    "stream": False,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    "options": {"temperature": 0.1, "num_predict": max_tokens},
                },
                timeout=config.LLM_TIMEOUT_S,
            )
            r.raise_for_status()
            return r.json()["message"]["content"].strip()
        if provider == "openai_compat":
            headers = {"Authorization": f"Bearer {config.LLM_API_KEY}"} if config.LLM_API_KEY else {}
            r = httpx.post(
                f"{config.LLM_BASE_URL.rstrip('/')}/v1/chat/completions",
                headers=headers,
                json={
                    "model": config.LLM_MODEL,
                    "temperature": 0.1,
                    "max_tokens": max_tokens,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                },
                timeout=config.LLM_TIMEOUT_S,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise LLMUnavailable(str(exc)) from exc
    raise LLMUnavailable(f"provider '{provider}' does not generate")
