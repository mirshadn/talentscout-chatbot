from __future__ import annotations
from typing import List, Optional, Dict, Tuple
from pydantic import BaseModel, EmailStr, field_validator, conint
import phonenumbers

# Controlled vocabulary for roles (extend as needed)
ROLE_MAP = {
    "aiml engineer": "ML Engineer",
    "ml engineer": "ML Engineer",
    "machine learning engineer": "ML Engineer",
    "data scientist": "Data Scientist",
    "backend engineer": "Backend Engineer",
    "software engineer": "Software Engineer",
    "mle": "ML Engineer",
}

# Minimal location catalog (extend as needed)
CANON_COUNTRIES = {
    "india": "India",
    "bangladesh": "Bangladesh",
    "united states": "United States",
    "usa": "United States",
    "china": "China",
}

CANON_CITIES: Dict[Tuple[str, str], str] = {
    ("surat", "india"): "Surat, India",
    ("dhaka", "bangladesh"): "Dhaka, Bangladesh",
    ("mumbai", "india"): "Mumbai, India",
    ("bengal", "bangladesh"): "Bengal, Bangladesh",
}

def normalize_role(text: str) -> Optional[str]:
    t = (text or "").strip().lower()
    return ROLE_MAP.get(t)

def normalize_location(raw: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Returns (city_normalized, country_normalized, display) or (None, None, None) if invalid.
    Accepts 'City, Country' and maps to a canonical display string.
    """
    if not raw:
        return None, None, None
    parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
    if len(parts) != 2:
        return None, None, None
    city, country = parts
    country_norm = CANON_COUNTRIES.get(country)
    if not country_norm:
        return None, None, None
    # Exact table lookup
    key = (city, country_norm.lower())
    display = CANON_CITIES.get(key)
    if display:
        return city.title(), country_norm, display
    # Fallback: title-case city with recognized country
    return city.title(), country_norm, f"{city.title()}, {country_norm}"

class TechStack(BaseModel):
    languages: Optional[List[str]] = None
    frameworks: Optional[List[str]] = None
    databases: Optional[List[str]] = None
    tools: Optional[List[str]] = None

class Candidate(BaseModel):
    consent: bool
    full_name: str
    email: EmailStr
    phone: str
    years_experience: conint(ge=0, le=40)  # enforce 0–40
    desired_positions: List[str]
    current_location: str
    tech_stack: TechStack
    language: str = "en"

    @field_validator("phone")
    @classmethod
    def _phone_e164(cls, v: str) -> str:
        try:
            num = phonenumbers.parse(v, None)
            if not phonenumbers.is_possible_number(num) or not phonenumbers.is_valid_number(num):
                raise ValueError("invalid phone")
            return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
        except Exception as e:
            raise ValueError("Phone must be E.164 like +917022612686") from e

    @field_validator("desired_positions", mode="before")
    @classmethod
    def _roles_list(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            maybe = normalize_role(v)
            return [maybe] if maybe else []
        if isinstance(v, list):
            out = []
            for item in v:
                if not isinstance(item, str):
                    continue
                mapped = normalize_role(item)
                if mapped:
                    out.append(mapped)
            return out
        return []

    @field_validator("current_location", mode="before")
    @classmethod
    def _city_country(cls, v: str):
        cty, ctry, disp = normalize_location(v or "")
        if not disp:
            raise ValueError("Location must be 'City, Country' (e.g., 'Surat, India')")
        return disp

    @field_validator("language", mode="before")
    @classmethod
    def _lang_guard(cls, v: str):
        # Default to English unless a robust detector is added
        return "en"
