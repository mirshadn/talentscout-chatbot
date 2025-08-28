# app.py
import sys, os, glob
sys.path.insert(0, os.path.dirname(__file__))

import re, json, uuid, logging
import streamlit as st
from dotenv import load_dotenv

from schemas import Candidate, TechStack, END_KEYWORDS
from llm import generate_questions, grade_answer
from storage import save_candidate, load_candidate, delete_candidate
from utils import analyze_sentiment, detect_language, csv_or_list, is_affirmative

# Location and country helpers
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderServiceError
import pycountry
from rapidfuzz import process, fuzz, fuzz as rf_fuzz

load_dotenv()
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
st.set_page_config(page_title="TalentScout Hiring Assistant", page_icon="🧩", layout="centered")

# ----------------- Subtle CSS / UI polish -----------------
st.markdown("""
<style>
/* Increase top padding so first chat message isn't hidden */
section.stMain .block-container { padding-top: 2.5rem; padding-bottom: 3rem; }
/* Keep tighter chat message spacing */
[data-testid="stChatMessage"] { padding: 0.45rem 0.25rem; }
/* Sentiment badges */
.badge { display:inline-block; padding:2px 8px; border-radius:12px; font-size:0.75rem; margin-left:6px; }
.badge.pos { background:#e6ffed; color:#056f3d; border:1px solid #baf0cb; }
.badge.neu { background:#eef2f7; color:#243447; border:1px solid #d4dbe6; }
.badge.neg { background:#ffecec; color:#8a001b; border:1px solid #ffc2c7; }
.prog-label { font-size:0.85rem; margin-top:0.25rem; color:#8899a6; }
</style>
""", unsafe_allow_html=True)


# ---- Read secrets into env (optional) ----
try:
    if "openai" in st.secrets:
        os.environ["OPENAI_API_KEY"] = st.secrets.openai.get("api_key", "")
    if "app" in st.secrets:
        for k, v in st.secrets.app.items():
            if isinstance(v, (str, int, float)):
                os.environ[str(k).upper()] = str(v)
except Exception:
    pass

# ----------------- Lightweight personalization (by email) -----------------
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
PROFILE_DIR = os.path.join(DATA_DIR, "profiles")
os.makedirs(PROFILE_DIR, exist_ok=True)

def _profile_path(email: str) -> str:
    safe = (email or "").replace("/", "_")
    return os.path.join(PROFILE_DIR, f"{safe}.json")

def save_profile(email: str, profile: dict) -> None:
    if not email:
        return
    with open(_profile_path(email), "w", encoding="utf-8") as f:
        json.dump(profile or {}, f, ensure_ascii=False, indent=2)

def load_profile(email: str) -> dict | None:
    if not email:
        return None
    p = _profile_path(email)
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

# ---- Session State ----
if "messages" not in st.session_state:
    st.session_state.messages = []
if "candidate" not in st.session_state:
    st.session_state.candidate = Candidate().model_dump()
if "phase" not in st.session_state:
    st.session_state.phase = "greet"
if "questions" not in st.session_state:
    st.session_state.questions = []
if "q_index" not in st.session_state:
    st.session_state.q_index = 0
if "answers" not in st.session_state:
    st.session_state.answers = []
if "candidate_id" not in st.session_state:
    st.session_state.candidate_id = str(uuid.uuid4())[:8]
if "language" not in st.session_state:
    st.session_state.language = "en"
# personalization prefs (language is above); difficulty + recent topics
if "prefs" not in st.session_state:
    st.session_state.prefs = {"preferred_difficulty": "auto", "recent_topics": []}

# --------------- Minimal i18n strings (extend as needed) ---------------
I18N = {
    "en": {
        "greet": "Hello! I’m TalentScout, the hiring assistant for technology roles. I’ll gather a few details and then ask tailored technical questions; type 'exit' or 'bye' anytime to finish.",
        "ask_name": "What is the full name?",
        "ask_email": "What is the email address?",
        "ask_phone": "What is the phone number with country code ",
        "ask_yexp": "How many years of professional experience?",
        "ask_roles": "What position(s) are desired? (e.g., 'Backend Engineer; MLE')",
        "ask_loc": "What is the current location (City, Country)?",
        "ask_stack": "Could you share the primary technologies worked with recently? For example: Python, Django, PostgreSQL, Docker.",
        "thanks": "Thanks for the time. This conversation is now closed. Expect a follow‑up email with next steps."
    },
    "hi": {
        "greet": "नमस्ते! मैं TalentScout हूँ, तकनीकी भूमिकाओं के लिए भर्ती सहायक। कुछ विवरण लेकर उपयुक्त तकनीकी प्रश्न पूछूँगा; समाप्त करने के लिए 'exit' या 'bye' टाइप करें।",
        "ask_name": "पूरा नाम क्या है?",
        "ask_email": "ईमेल पता क्या है?",
        "ask_phone": "फ़ोन नंबर देश कोड सहित",
        "ask_yexp": "कुल अनुभव (वर्षों में) कितना है?",
        "ask_roles": "वांछित पद क्या हैं? (उदा., 'Backend Engineer; MLE')",
        "ask_loc": "वर्तमान स्थान (शहर, देश) क्या है?",
        "ask_stack": "हाल ही में किन तकनीकों पर काम किया है? उदाहरण: Python, Django, PostgreSQL, Docker.",
        "thanks": "समय देने के लिए धन्यवाद। यह वार्तालाप अब समाप्त है। आगे की प्रक्रिया की सूचना दी जाएगी।"
    }
}
def t(key: str) -> str:
    # Use base language (e.g., "en" from "en-US")
    lang = (st.session_state.language or "en").split("-")[0]
    return I18N.get(lang, I18N["en"]).get(key, I18N["en"].get(key, key))

# ---- Guards ----
def ensure_text(x) -> str:
    if x is None:
        return ""
    if isinstance(x, (dict, list)):
        if isinstance(x, dict) and "content" in x and isinstance(x["content"], str):
            return x["content"]
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

# ---- Chat helpers ----
def say(role: str, text: str, meta: dict = None):
    st.session_state.messages.append({"role": role, "content": text, "meta": meta or {}})

def _sent_badge(sent: dict) -> str:
    if not sent or "label" not in sent:
        return ""
    label = sent.get("label", "neutral")
    score = sent.get("score", 0.5)
    cls = "pos" if label == "positive" else "neg" if label == "negative" else "neu"
    return f"  <span class='badge {cls}'>sentiment: {label} · {score}</span>"

def show_chat():
    # Render messages with sentiment badges for user turns
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            if m["role"] == "user" and m.get("meta") and m["meta"].get("sentiment"):
                badge = _sent_badge(m["meta"]["sentiment"])
                st.markdown(f"{m['content']}{badge}", unsafe_allow_html=True)
            else:
                st.markdown(m["content"])
    # Show a progress bar for question rounds
    if st.session_state.questions:
        i = st.session_state.q_index
        n = len(st.session_state.questions)
        pct = int((min(i, n) / max(n, 1)) * 100)
        st.progress(pct, text=f"{i}/{n} answered")

def is_exit(text: str) -> bool:
    lower = ensure_text(text).strip().lower()
    tokens = re.findall(r"\w+", lower)
    return any(k in tokens or k == lower for k in END_KEYWORDS)

def normalize_positions(txt: str):
    return csv_or_list(txt)

# ---------------- Strong field validation ----------------
def validate_full_name(name: str) -> str:
    s = re.sub(r"\s+", " ", ensure_text(name).strip())
    parts = [p for p in s.split(" ") if p]
    if len(parts) < 2:
        raise ValueError("Please enter first and last name")
    if any(not re.fullmatch(r"[A-Za-z][A-Za-z.'\-]{1,}", p) for p in parts):
        raise ValueError("Name must contain only letters and common separators")
    if len(s) < 4 or len(s) > 100:
        raise ValueError("Name length must be 4–100 characters")
    return " ".join(p.capitalize() for p in parts)

TECH_ROLE_KEYWORDS = {
    "engineer","developer","dev","data","ml","ai","machine","learning","backend","front",
    "frontend","full","stack","fullstack","devops","site","reliability","sre","mobile",
    "android","ios","qa","test","testing","automation","cloud","platform","security",
    "analyst","scientist","architect","etl","mle","nlp","cv","vision","infra","infrastructure"
}
def validate_positions_strict(text: str) -> list:
    items = [x.strip() for x in re.split(r"[;,]", ensure_text(text)) if x.strip()]
    if not items:
        raise ValueError("Please provide at least one role")
    ok = []
    for it in items:
        if not re.fullmatch(r"[A-Za-z0-9 /&+\-_.]{2,50}", it):
            raise ValueError(f"Role contains invalid characters: {it}")
        tokens = re.findall(r"[A-Za-z]+", it.lower())
        if not any(k in tokens for k in TECH_ROLE_KEYWORDS):
            raise ValueError(f"Role seems non‑technical: {it}")
        ok.append(it)
    return ok

# ---- Geocoding + country validation with fuzzy correction ----
_geocoder = None
def _geo():
    global _geocoder
    if _geocoder is None:
        _geocoder = Nominatim(user_agent="talentscout_app", timeout=10)
    return _geocoder

COUNTRIES = [c.name for c in pycountry.countries]

def _correct_country(name: str):
    cand, score, _ = process.extractOne(ensure_text(name).strip(), COUNTRIES, scorer=fuzz.WRatio)
    return cand if score >= 90 else None

# STRICT city–country validation: constrain geocode by ISO country
def normalize_location_input(text: str) -> str:
    s = re.sub(r"\s+", " ", ensure_text(text).strip())
    if "," not in s:
        raise ValueError("Please provide location as 'City, Country'")

    raw_city, raw_country = [p.strip() for p in s.split(",", 1)]
    if not raw_city or not raw_country:
        raise ValueError("Please provide both city and country")

    fixed_country = _correct_country(raw_country) or raw_country
    try:
        country_obj = pycountry.countries.lookup(fixed_country)
        country_name = country_obj.name
        country_code = country_obj.alpha_2
    except Exception:
        raise ValueError("Country not recognized, please correct spelling")

    # Constrain geocode to the specified country
    loc = _geo().geocode(raw_city, country_codes=country_code, addressdetails=True, exactly_one=True)
    if not loc:
        # Probe globally to suggest likely country if mismatch
        probe = _geo().geocode(raw_city, addressdetails=True, exactly_one=True)
        if probe and probe.raw.get("address", {}).get("country"):
            suggested_country = probe.raw["address"]["country"]
            raise ValueError(f"City not found in {country_name}. Did you mean {raw_city.title()}, {suggested_country}?")
        raise ValueError(f"City '{raw_city}' not found in {country_name}. Please re‑enter.")

    addr = loc.raw.get("address", {})
    geo_country = addr.get("country")
    if not geo_country or geo_country.lower() != country_name.lower():
        raise ValueError(f"City not found in {country_name}. Please re‑enter.")

    city_norm = addr.get("city") or addr.get("town") or addr.get("village") or raw_city
    return f"{city_norm.title()}, {country_name}"

# --------- Tech stack parsing (case-insensitive & hardened) ----------
KNOWN = {
    "languages": {
        "Python","JavaScript","TypeScript","Java","C++","C#","Go","Rust","Kotlin","Swift",
        "Ruby","PHP","R","Scala","MATLAB","SQL","Bash","Shell"
    },
    "frameworks": {
        "Django","Flask","FastAPI","Spring","Spring Boot","React","Next.js","Angular","Vue",
        "Express","Node.js",".NET","ASP.NET","Laravel","Rails","Svelte","Nuxt","NestJS",
        "PyTorch","TensorFlow","Keras","scikit-learn","XGBoost","LightGBM","pandas","NumPy"
    },
    "databases": {
        "PostgreSQL","MySQL","SQLite","MongoDB","Redis","Cassandra","Elasticsearch","Oracle",
        "SQL Server","DynamoDB","Snowflake","BigQuery"
    },
    "tools": {
        "Docker","Kubernetes","AWS","GCP","Azure","Git","GitHub","GitLab","Bitbucket",
        "Terraform","Ansible","Jenkins","Airflow","Kafka","RabbitMQ","Nginx","Linux","VSCode"
    }
}
ALIASES = {
    "postgres":"PostgreSQL","postgresql":"PostgreSQL","postgre":"PostgreSQL",
    "node":"Node.js","nodejs":"Node.js","reactjs":"React","nextjs":"Next.js",
    "ms sql":"SQL Server","mssql":"SQL Server","google cloud":"GCP","gcloud":"GCP",
    "amazon web services":"AWS","azure devops":"Azure","k8s":"Kubernetes",
    "tf":"Terraform","scikit learn":"scikit-learn","pytorch lightning":"PyTorch",
    "ts":"TypeScript","js":"JavaScript"
}
NON_TECH = {"snake","cat","dog","human","food","movie","music","song","dance"}

# Lowercase index for case-insensitive exact/alias/fuzzy
INDEX_LOWER: dict[str, tuple[str,str]] = {}
for cat, vocab in KNOWN.items():
    for item in vocab:
        INDEX_LOWER[item.casefold()] = (cat, item)
ALIASES_LOWER: dict[str, tuple[str,str]] = {}
for alias, canon in ALIASES.items():
    cl = canon.casefold()
    if cl in INDEX_LOWER:
        ALIASES_LOWER[alias.casefold()] = INDEX_LOWER[cl]
ALL_CANON_KEYS = list(INDEX_LOWER.keys())

def _match_known(token: str) -> tuple[str, str] | None:
    tkn = (token or "").strip()
    if not tkn:
        return None
    low = tkn.casefold()
    if low in NON_TECH:
        return None
    if low in INDEX_LOWER:
        return INDEX_LOWER[low]
    if low in ALIASES_LOWER:
        return ALIASES_LOWER[low]
    best = process.extractOne(low, ALL_CANON_KEYS, scorer=rf_fuzz.token_set_ratio)
    if best and best[1] >= 92:
        return INDEX_LOWER[best[0]]
    return None

def parse_stack(text: str):
    s = ensure_text(text)
    # 1) JSON
    try:
        data = json.loads(s)
        buckets = {"languages": [], "frameworks": [], "databases": [], "tools": []}
        for cat in buckets:
            for item in data.get(cat, []) or []:
                hit = _match_known(str(item))
                if hit and hit[0] == cat and hit[1] not in buckets[cat]:
                    buckets[cat].append(hit[1])
        if any(buckets.values()):
            return buckets
    except Exception:
        pass
    # 2) Labeled lines
    buckets = {"languages": [], "frameworks": [], "databases": [], "tools": []}
    any_label = False
    for line in s.splitlines():
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        k = key.strip().lower()
        if k in buckets:
            any_label = True
            for token in csv_or_list(val):
                hit = _match_known(token)
                if hit and hit[0] == k and hit[1] not in buckets[k]:
                    buckets[k].append(hit[1])
    if any_label and any(buckets.values()):
        return buckets
    # 3) Free text
    tokens = re.split(r"[;,/|]+|\s{2,}", s)
    for tok in tokens:
        hit = _match_known(tok)
        if hit and hit[1] not in buckets[hit[0]]:
            buckets[hit[0]].append(hit[1])
    return buckets

# ---------------- Flow helpers ----------------
def next_missing_field(cand: Candidate) -> str:
    order = ["consent","full_name","email","phone",
             "years_experience","desired_positions",
             "current_location","tech_stack"]
    missing = cand.missing_fields()
    for f in order:
        if f in missing:
            return f
    return ""

def ask_for(field: str):
    prompts = {
        "consent": "May I collect a few basic details to begin the screening? Reply 'yes' to proceed or 'exit' to stop.",
        "full_name": t("ask_name"),
        "email": t("ask_email"),
        "phone": t("ask_phone"),
        "years_experience": t("ask_yexp"),
        "desired_positions": t("ask_roles"),
        "current_location": t("ask_loc"),
        "tech_stack": t("ask_stack"),
    }
    say("assistant", prompts[field])

def ask_current_question():
    i = st.session_state.q_index
    if 0 <= i < len(st.session_state.questions):
        q = st.session_state.questions[i]
        say("assistant", f"Q{i+1}. [{q['topic']}, {q['difficulty']}] {q['question']}")
    else:
        say("assistant", "No more questions.")

def validate_and_set(field: str, text: str) -> bool:
    c = Candidate(**st.session_state.candidate)
    try:
        ttxt = ensure_text(text).strip()

        if field == "consent":
            if is_affirmative(ttxt):
                c.consent = True
            else:
                say("assistant", "No problem. Type 'yes' to proceed with consent or 'exit' to end.")
                st.session_state.candidate = c.model_dump()
                return False

        elif field == "full_name":
            c.full_name = validate_full_name(ttxt)

        elif field == "email":
            # Clean + syntax-first, optional DNS/MX (soft warning)
            from email_validator import validate_email, EmailNotValidError
            import unicodedata
            COMMON = ["gmail.com","yahoo.com","outlook.com","hotmail.com","icloud.com",
                      "proton.me","protonmail.com","live.com","aol.com","pm.me"]
            mode = os.getenv("EMAIL_DELIVERABILITY", "relaxed").strip().lower()  # relaxed|strict

            def clean_email(s: str) -> str:
                s = unicodedata.normalize("NFKC", s or "")
                s = s.replace("\u200b","").replace("\u200c","").replace("\u200d","").replace("\ufeff","").replace("\xa0"," ")
                s = s.strip()
                m = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", s)
                return m.group(0) if m else s

            def fix_domain(addr: str) -> str:
                if "@" not in addr: return addr
                local, dom = addr.rsplit("@", 1)
                cand = process.extractOne(dom, COMMON, scorer=fuzz.WRatio)
                if cand and cand[1] >= 92:
                    return f"{local}@{cand[0]}"
                return addr

            raw = clean_email(ttxt)
            try:
                v = validate_email(fix_domain(raw), check_deliverability=False)
                normalized = v.normalized
                if mode == "strict":
                    try:
                        validate_email(normalized, check_deliverability=True)
                    except EmailNotValidError as e:
                        say("assistant", f"Email looks valid but DNS/MX couldn’t be verified ({str(e)}). Proceeding; this will be re‑checked later.")
                c.email = normalized

                # Load personalization for this email if present
                prof = load_profile(c.email) or {}
                if prof.get("language"):
                    st.session_state.language = prof["language"]
                if prof.get("preferred_difficulty"):
                    st.session_state.prefs["preferred_difficulty"] = prof["preferred_difficulty"]
                if prof.get("recent_topics"):
                    st.session_state.prefs["recent_topics"] = prof["recent_topics"][:8]

            except EmailNotValidError as e:
                raise ValueError(str(e))

        elif field == "phone":
            import phonenumbers
            from phonenumbers import NumberParseException, PhoneNumberFormat
            default_region = os.getenv("DEFAULT_REGION", None)
            try:
                num = phonenumbers.parse(ttxt, None if ttxt.startswith("+") else default_region)
                if not phonenumbers.is_valid_number(num):
                    raise ValueError("Invalid phone number")
                c.phone = phonenumbers.format_number(num, PhoneNumberFormat.E164)
            except NumberParseException:
                raise ValueError("Invalid phone number")

        elif field == "years_experience":
            val = float(ttxt)
            if not (0 <= val <= 60):
                raise ValueError("Years must be between 0 and 60")
            c.years_experience = val

        elif field == "desired_positions":
            c.desired_positions = validate_positions_strict(ttxt)

        elif field == "current_location":
            c.current_location = normalize_location_input(ttxt)

        elif field == "tech_stack":
            parsed = parse_stack(text)
            if not any(parsed.values()):
                say("assistant", "That input doesn’t look like a technology list. Please enter items like 'Python, Django, PostgreSQL, Docker'.")
                st.session_state.candidate = c.model_dump()
                return False
            c.tech_stack = TechStack(**parsed)
            # Update recent topics for personalization
            topics = []
            for k in ("languages","frameworks","databases","tools"):
                topics.extend(parsed.get(k, []))
            if topics:
                st.session_state.prefs["recent_topics"] = list(dict.fromkeys(topics))[:8]

        st.session_state.candidate = c.model_dump()
        return True

    except Exception:
        say("assistant", f"That doesn't look valid for {field}. Please re-check and try again, or type 'exit' to finish.")
        return False

# ---- UI: Sidebar ----
with st.sidebar:
    st.title("TalentScout • Controls")
    st.caption("Session and privacy controls")

    st.write(f"Candidate ID: `{st.session_state.candidate_id}`")

    # ISO language override guard (e.g., 'en', 'hi', 'ar' or 'en-US')
    lang_override = st.text_input("Language override (ISO, optional)", value="")
    if lang_override.strip():
        if re.fullmatch(r"[A-Za-z]{2,3}(-[A-Za-z]{2})?", lang_override.strip()):
            st.session_state.language = lang_override.strip()
        else:
            st.warning("Please enter a valid ISO code like 'en' or leave blank.")

    # Personalization: preferred difficulty for question generation/evaluation
    st.session_state.prefs["preferred_difficulty"] = st.selectbox(
        "Preferred difficulty (personalization)",
        ["auto", "beginner", "intermediate", "advanced"],
        index=["auto","beginner","intermediate","advanced"].index(
            st.session_state.prefs.get("preferred_difficulty","auto")
        )
    )

    # Save is only enabled after consent
    c = Candidate(**st.session_state.candidate)
    save_disabled = not c.consent
    if st.button("Save record now", disabled=save_disabled):
        if not c.consent:
            st.warning("Cannot save without consent.")
        else:
            save_candidate(st.session_state.candidate_id, st.session_state.candidate)
            # Persist personalization by email if available
            if c.email:
                save_profile(c.email, {
                    "language": st.session_state.language,
                    "preferred_difficulty": st.session_state.prefs.get("preferred_difficulty","auto"),
                    "recent_topics": st.session_state.prefs.get("recent_topics", [])
                })
            st.success(f"Saved to data/candidates/{st.session_state.candidate_id}.json")

    # Load by typing
    load_id = st.text_input("Load candidate by ID", value="")
    if st.button("Load"):
        rec = load_candidate(load_id.strip())
        if rec:
            st.session_state.candidate = rec
            st.session_state.messages.append({"role":"assistant","content":"Record loaded into session.", "meta":{}})
            st.success("Loaded.")
        else:
            st.error("No such record.")

    # Convenience: list existing IDs for loading
    data_dir = os.path.join(os.path.dirname(__file__), "data", "candidates")
    os.makedirs(data_dir, exist_ok=True)
    files = sorted([os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(data_dir, "*.json"))])
    if files:
        pick = st.selectbox("Or pick an existing record", files, index=0)
        if st.button("Load selected"):
            rec = load_candidate(pick)
            if rec:
                st.session_state.candidate = rec
                st.success(f"Loaded {pick}.")
            else:
                st.error("Record not found. Try again.")

    # Delete by ID
    del_id = st.text_input("Delete candidate by ID", value="")
    if st.button("Delete"):
        if delete_candidate(del_id.strip()):
            st.success("Deleted.")
        else:
            st.error("No such record to delete.")

# ---- Greeting ----
if st.session_state.phase == "greet":
    say("assistant", t("greet"))
    st.session_state.phase = "gather"

# ---- Input FIRST ----
user_text = st.chat_input("Type here…")
if user_text:
    # Auto language detection unless user explicitly overrode with valid ISO
    detected = detect_language(user_text, default=st.session_state.language or "en")
    if not re.fullmatch(r"[A-Za-z]{2,3}(-[A-Za-z]{2})?", st.session_state.language or ""):
        st.session_state.language = detected

    sent = analyze_sentiment(user_text)
    say("user", ensure_text(user_text), meta={"lang": st.session_state.language, "sentiment": sent})

    if is_exit(user_text):
        say("assistant", t("thanks"))
        st.session_state.phase = "end"
        show_chat()
        st.stop()

    if st.session_state.phase == "questions":
        i = st.session_state.q_index
        if 0 <= i < len(st.session_state.questions):
            q = st.session_state.questions[i]
            result = grade_answer(q, ensure_text(user_text), language=st.session_state.language or "en")
            verdict = result.get("verdict", "needs_improvement").replace("_", " ").title()
            feedback = result.get("feedback", "").strip()
            st.session_state.answers.append({"question": q, "answer": ensure_text(user_text), "verdict": verdict, "feedback": feedback})
            say("assistant", f"Evaluation: {verdict}. {feedback}" if feedback else f"Evaluation: {verdict}.")
            st.session_state.q_index += 1
            if st.session_state.q_index < len(st.session_state.questions):
                ask_current_question()
            else:
                say("assistant", "Thanks for answering the questions. Type 'exit' to finish or share more details.")
                st.session_state.phase = "wrapup"
        else:
            say("assistant", "No more questions. Type 'exit' to finish or share more details.")
    else:
        cand = Candidate(**st.session_state.candidate)
        if not cand.language:
            cand.language = st.session_state.language
            st.session_state.candidate = cand.model_dump()

        missing = next_missing_field(cand)
        if missing:
            if validate_and_set(missing, user_text):
                cand = Candidate(**st.session_state.candidate)
                next_field = next_missing_field(cand)
                if next_field:
                    ask_for(next_field)
                else:
                    stack_dict = cand.tech_stack.model_dump() if cand.tech_stack else {}
                    # Make preferred difficulty available for downstream logic if used
                    os.environ["PREFERRED_DIFFICULTY"] = st.session_state.prefs.get("preferred_difficulty","auto")
                    qs, err = generate_questions(stack_dict, language=cand.language or st.session_state.language)
                    st.session_state.questions = qs or []
                    st.session_state.q_index = 0
                    st.session_state.answers = []
                    if st.session_state.questions:
                        st.session_state.phase = "questions"
                        ask_current_question()
                    else:
                        say("assistant", "Unable to prepare questions right now. Please try again or type 'exit' to finish.")
            else:
                ask_for(missing)
        else:
            say("assistant", "Noted. Type 'exit' to conclude, or add more details.")

# ---- Render AFTER updates ----
show_chat()

# ---- Debug ----
with st.expander("Session (debug)"):
    st.json({k: v for k, v in st.session_state.items()
             if k in ("candidate","candidate_id","phase","questions","q_index","answers","prefs","language")})
