# prompts.py
SYSTEM_PROMPT = (
    "You are a concise, fair technical interviewer. "
    "Generate clear, unambiguous questions and keep outputs in JSON when asked."
)

GEN_QUESTIONS_INSTRUCTION = (
    "Given the candidate's declared tech stack, produce structured interview "
    "questions grouped by topic and difficulty. Return JSON with the top-level "
    "key 'questions' as a list of items, each item having keys: "
    "'topic' (string), 'question' (string), and 'difficulty' "
    "in {'beginner','intermediate','advanced'}."
)

FEWSHOTS = {
    "Python": [
        {"topic": "Python", "difficulty": "beginner",
         "question": "Explain what a list and a dict are in Python and show a short example."},
        {"topic": "Python", "difficulty": "intermediate",
         "question": "When would a context manager be used? Provide a short with-statement example."}
    ],
    "Django": [
        {"topic": "Django", "difficulty": "beginner",
         "question": "What are models, views, and templates? Give a brief overview."}
    ],
    "SQL": [
        {"topic": "SQL", "difficulty": "intermediate",
         "question": "Compare INNER JOIN and LEFT JOIN with a simple example."}
    ]
}
