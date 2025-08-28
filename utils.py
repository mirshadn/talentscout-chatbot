# utils.py
import json, re
from typing import Any, List, Dict
from functools import lru_cache

# ---------- Lightweight app utilities ----------
def csv_or_list(text: str) -> List[str]:
    return [x.strip() for x in re.split(r"[;,]", text or "") if x.strip()]

# Language detection (auto + safe fallback)
def detect_language(text: str, default: str = "en") -> str:
    try:
        from langdetect import detect
        t = (text or "").strip()
        if not t:
            return default
        # langdetect returns ISO-639-1 (e.g., "en")
        code = detect(t)
        return code or default
    except Exception:
        return default

# Sentiment analysis (fast, cached)
@lru_cache(maxsize=1)
def _sentiment_analyzer():
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        return SentimentIntensityAnalyzer()
    except Exception:
        return None

def analyze_sentiment(text: str) -> Dict[str, float | str]:
    """
    Returns {'label': 'positive|neutral|negative', 'score': float in [0,1]}
    Falls back to neutral if analyzer is unavailable.
    """
    a = _sentiment_analyzer()
    if not a:
        return {"label": "neutral", "score": 0.5}
    s = (text or "").strip()
    if not s:
        return {"label": "neutral", "score": 0.5}
    res = a.polarity_scores(s)
    comp = float(res.get("compound", 0.0))
    label = "positive" if comp >= 0.05 else "negative" if comp <= -0.05 else "neutral"
    score = (comp + 1.0) / 2.0  # map [-1,1] -> [0,1]
    return {"label": label, "score": round(score, 3)}

# ---------- Safe text coercion for regex/JSON ----------
def _ensure_text(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, (dict, list)):
        try:
            return json.dumps(x, ensure_ascii=False)
        except Exception:
            return str(x)
    if isinstance(x, (bytes, bytearray)):
        try:
            return x.decode("utf-8", "ignore")
        except Exception:
            return str(x)
    return str(x)

# ---------- JSON extraction helpers ----------
def extract_first_json_object(text: Any) -> dict:
    if isinstance(text, dict):
        return text
    if isinstance(text, list):
        return {"questions": text} if any(isinstance(i, dict) and "question" in i for i in text) else {"items": text}
    if text is None:
        return {}
    s = _ensure_text(text)
    m = re.search(r"``````", s, flags=re.DOTALL)
    if not m:
        m = re.search(r"(\{.*?\}|\[.*?\])", s, flags=re.DOTALL)
    candidate = m.group(1) if m else s
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, list):
            return {"questions": parsed} if any(isinstance(i, dict) and "question" in i for i in parsed) else {"items": parsed}
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    try:
        parsed = json.loads(s)
        if isinstance(parsed, list):
            return {"questions": parsed} if any(isinstance(i, dict) and "question" in i for i in parsed) else {"items": parsed}
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    try:
        inner = json.loads(candidate)
        if isinstance(inner, (str, bytes, bytearray)):
            parsed = json.loads(_ensure_text(inner))
            if isinstance(parsed, list):
                return {"questions": parsed} if any(isinstance(i, dict) and "question" in i for i in parsed) else {"items": parsed}
            if isinstance(parsed, dict):
                return parsed
        if isinstance(inner, dict):
            return inner
        if isinstance(inner, list):
            return {"questions": inner} if any(isinstance(i, dict) and "question" in i for i in inner) else {"items": inner}
    except Exception:
        return {}
    return {}

def extract_json(text: Any) -> dict:
    obj = extract_first_json_object(text)
    return obj if isinstance(obj, dict) else {"items": obj}

# ---------- Affirmative helper ----------
import re as _re
AFFIRM_WORDS = {"y","yes","yeah","yep","yup","sure","ok","okay","affirmative","agree","si","sí","oui","da"}
def is_affirmative(text: str) -> bool:
    if not text:
        return False
    t = _re.sub(r"\W+", "", str(text).strip().lower())
    return t in AFFIRM_WORDS or t.startswith("y")
