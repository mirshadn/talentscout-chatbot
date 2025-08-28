# model_client.py
import os, time, random
from typing import Dict, Any
from openai import OpenAI
from openai import RateLimitError, APIError, APIConnectionError, APITimeoutError

OPENAI_MODEL_DEFAULT = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

def _jittered_backoff(attempt: int, base: float = 0.5, cap: float = 8.0) -> float:
    return min(cap, base * (2 ** attempt)) + random.uniform(0, 0.25)

def chat(messages: list[Dict[str, Any]],
         model: str | None = None,
         temperature: float = 0.2,
         timeout: int = 30,
         max_tries: int = 5) -> Dict[str, Any]:
    client = OpenAI()
    model = model or OPENAI_MODEL_DEFAULT

    for i in range(max_tries):
        try:
            resp = client.chat.completions.create(
                model=model,
                temperature=temperature,
                messages=messages,
                timeout=timeout,
            )
            content = resp.choices.message.content
            return {"ok": True, "content": content, "insufficient_quota": False, "error": ""}
        except RateLimitError as e:
            msg = str(e).lower()
            if "insufficient_quota" in msg or "exceeded your current quota" in msg:
                return {"ok": False, "content": None, "insufficient_quota": True, "error": "insufficient_quota"}
            time.sleep(_jittered_backoff(i))
        except (APIError, APIConnectionError, APITimeoutError):
            time.sleep(_jittered_backoff(i))
        except Exception as e:
            return {"ok": False, "content": None, "insufficient_quota": False, "error": str(e)}

    return {"ok": False, "content": None, "insufficient_quota": False, "error": "max_retries"}
