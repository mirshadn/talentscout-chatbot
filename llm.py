# llm.py
import os, json, logging
from typing import Dict, List, Tuple, Any
from dotenv import load_dotenv
from schemas import Question
from prompts import SYSTEM_PROMPT, GEN_QUESTIONS_INSTRUCTION, FEWSHOTS
from utils import extract_first_json_object
from model_client import chat as openai_chat

load_dotenv()
logger = logging.getLogger("talentscout.llm")
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

PROVIDER = os.getenv("PROVIDER", "openai").lower()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")
QUESTIONS_PER_TOPIC = int(os.getenv("QUESTIONS_PER_TOPIC", "3"))
MAX_TOPICS = int(os.getenv("MAX_TOPICS", "2"))
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.2"))
EVAL_ANSWERS = os.getenv("EVAL_ANSWERS", "true").lower() == "true"

def _as_dict(stack: Any) -> Dict[str, List[str]]:
    if hasattr(stack, "model_dump"):
        try:
            return stack.model_dump()
        except Exception:
            pass
    if isinstance(stack, dict):
        return stack
    return {"languages": [], "frameworks": [], "databases": [], "tools": []}

def _validate_questions(items: List[Dict]) -> List[Dict]:
    validated = []
    for q in items:
        try:
            validated.append(Question(**q).model_dump())
        except Exception:
            continue
    return validated

def _cap_per_topic(items: List[Dict]) -> List[Dict]:
    per, out = {}, []
    for q in items:
        t = q["topic"]
        per[t] = per.get(t, 0) + 1
        if per[t] <= QUESTIONS_PER_TOPIC:
            out.append(q)
    return out

def _format_stack(stack: Any) -> str:
    s = _as_dict(stack)
    def fmt(k): return ", ".join(s.get(k, []) or [])
    return (f"Languages: {fmt('languages')}\n"
            f"Frameworks: {fmt('frameworks')}\n"
            f"Databases: {fmt('databases')}\n"
            f"Tools: {fmt('tools')}")

def _topics(stack: Any) -> List[str]:
    s = _as_dict(stack)
    topics = []
    for k in ["languages","frameworks","databases","tools"]:
        topics.extend(s.get(k, []) or [])
    return topics

def _fewshot_snippets(stack: Any) -> List[Dict]:
    out, topics = [], _topics(stack)
    for t in topics[:MAX_TOPICS]:
        if t in FEWSHOTS:
            out.extend(FEWSHOTS[t])
    return out[:max(QUESTIONS_PER_TOPIC, 3)]

def _fallback(stack: Any) -> List[Dict]:
    topics = _topics(stack)
    if not topics:
        topics = ["General"]
    base = []
    for t in topics[:MAX_TOPICS] if MAX_TOPICS > 0 else topics:
        base.extend([
            {"topic": t, "question": f"Explain fundamentals of {t} and show a simple example.", "difficulty": "beginner"},
            {"topic": t, "question": f"Describe a debugging incident you solved in {t}.", "difficulty": "intermediate"},
            {"topic": t, "question": f"Design for performance/reliability in {t} under load—key trade-offs?", "difficulty": "advanced"},
        ])
    return _cap_per_topic(_validate_questions(base))

def generate_questions(stack: Any, language: str = "en") -> Tuple[List[Dict], str]:
    stack_dict = _as_dict(stack)
    user_prompt = (
        GEN_QUESTIONS_INSTRUCTION
        + f"\n\nDeclared tech stack:\n{_format_stack(stack_dict)}\n\n"
        + (f"Respond in ISO language '{language}'. " if language else "")
        + "Return JSON only."
    )
    examples = _fewshot_snippets(stack_dict)
    try:
        if PROVIDER == "openai":
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps({"examples": examples}) if examples else "No examples."},
                {"role": "user", "content": user_prompt},
            ]
            res = openai_chat(messages, model=OPENAI_MODEL, temperature=TEMPERATURE)
            if not res["ok"]:
                logger.warning("OpenAI chat failed: %s", res["error"])
                return _fallback(stack_dict), f"fallback:{res['error']}"
            content = res["content"]
        elif PROVIDER == "ollama":
            import ollama
            resp = ollama.chat(
                model=OLLAMA_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps({"examples": examples}) if examples else "No examples."},
                    {"role": "user", "content": user_prompt},
                ],
                options={"temperature": TEMPERATURE},
            )
            content = resp["message"]["content"]
        else:
            raise RuntimeError(f"Unknown PROVIDER: {PROVIDER}")

        data = extract_first_json_object(content)
        items = _validate_questions(data.get("questions", []))
        if not items:
            raise ValueError("Empty or invalid questions")
        return _cap_per_topic(items), ""
    except Exception as e:
        logger.warning("LLM error, using fallback: %s", e)
        return _fallback(stack_dict), f"fallback:{e}"

def _heuristic_grade(question: Dict, answer: str) -> Dict:
    topic = (question.get("topic") or "").lower()
    text = " " + (answer or "").lower() + " "
    KEYWORDS = {
        "python": ["function", "class", "list", "dict", "loop", "with", "context", "generator", "example"],
        "django": ["model", "view", "template", "orm", "queryset", "middleware", "settings", "migration"],
        "react": ["state", "props", "hook", "component", "useeffect", "memo", "render", "jsx"],
        "sql": ["select", "join", "index", "transaction", "foreign key", "where", "group by", "explain"],
        "docker": ["image", "container", "dockerfile", "build", "compose", "registry", "volume", "network"],
        "kubernetes": ["pod", "deployment", "service", "ingress", "namespace", "cluster", "helm", "scaling"],
        "pytorch": ["tensor", "autograd", "module", "optimizer", "dataset", "dataloader", "backward"],
    }
    kws = KEYWORDS.get(topic, [])
    hits = sum(1 for k in kws if k in text)
    verdict = "pass" if hits >= 2 or len(answer.strip()) >= 80 else "needs_improvement"
    feedback = "Covers several key concepts." if verdict == "pass" else "Add key concepts and a small code/example to strengthen the answer."
    return {"verdict": verdict, "feedback": feedback}

def grade_answer(question: Dict, answer: str, language: str = "en") -> Dict:
    if not EVAL_ANSWERS or PROVIDER != "openai":
        return _heuristic_grade(question, answer)
    try:
        rubric = (
            f"Topic: {question.get('topic')}. Difficulty: {question.get('difficulty')}."
            " Judge correctness, clarity, key concepts, and presence of a brief example when appropriate. Reply JSON only."
        )
        messages = [
            {"role": "system", "content": "You are a strict but fair technical interviewer. Reply with JSON only."},
            {"role": "user", "content": json.dumps({
                "rubric": rubric, "question": question.get("question"),
                "answer": answer, "language": language
            })},
        ]
        res = openai_chat(messages, model=OPENAI_MODEL, temperature=0.1)
        if not res["ok"]:
            return _heuristic_grade(question, answer)
        data = extract_first_json_object(res["content"])
        verdict = (data.get("verdict") or "needs_improvement").lower().replace(" ", "_")
        feedback = data.get("feedback") or ""
        if verdict not in ("pass", "needs_improvement"):
            return _heuristic_grade(question, answer)
        return {"verdict": verdict, "feedback": feedback}
    except Exception:
        return _heuristic_grade(question, answer)
