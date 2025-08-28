TalentScout - AI Hiring Assistant
TalentScout is a Streamlit-based chatbot that automates the first round of technical screening by collecting key candidate details, validating them safely, and running stack‑aware Q&A with instant evaluation. It supports multilingual prompts, inline sentiment badges, and lightweight personalization (language, difficulty, recent topics) saved by email. Core validations include RFC email with unicode normalization, E.164 phone formatting, ISO country with country‑constrained city geocoding, and case‑insensitive tech‑stack parsing with aliases and conservative fuzzy matching. Data is stored locally as JSON for development, while real secrets stay in local environment files (not committed).

Key features

Automated intake with strict validation (email, phone, location, tech stack).

Dynamic, stack‑aware questions with real‑time feedback.

Multilingual prompts and visible sentiment for user turns.

Personalization by email (language/difficulty/recent topics).
