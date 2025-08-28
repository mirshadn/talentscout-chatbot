# storage.py
import os, json

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CAND_DIR = os.path.join(DATA_DIR, "candidates")
PROF_DIR = os.path.join(DATA_DIR, "profiles")
os.makedirs(CAND_DIR, exist_ok=True)
os.makedirs(PROF_DIR, exist_ok=True)

def _cpath(cid: str) -> str:
    return os.path.join(CAND_DIR, f"{cid}.json")

def save_candidate(cid: str, data: dict) -> None:
    with open(_cpath(cid), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_candidate(cid: str):
    p = _cpath(cid)
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def delete_candidate(cid: str) -> bool:
    p = _cpath(cid)
    if os.path.exists(p):
        os.remove(p)
        return True
    return False

# ---------- Personalization by email ----------
def _ppath(email: str) -> str:
    safe = (email or "").replace("/", "_")
    return os.path.join(PROF_DIR, f"{safe}.json")

def save_profile(email: str, profile: dict) -> None:
    if not email:
        return
    with open(_ppath(email), "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)

def load_profile(email: str) -> dict | None:
    if not email:
        return None
    p = _ppath(email)
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)
