# schemas.py
from typing import List, Optional
from pydantic import BaseModel, Field

END_KEYWORDS = {"exit","bye","quit","stop","goodbye"}

class TechStack(BaseModel):
    languages: List[str] = Field(default_factory=list)
    frameworks: List[str] = Field(default_factory=list)
    databases: List[str] = Field(default_factory=list)
    tools: List[str] = Field(default_factory=list)

class Candidate(BaseModel):
    consent: bool = False
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    years_experience: Optional[float] = None
    desired_positions: List[str] = Field(default_factory=list)
    current_location: Optional[str] = None
    tech_stack: Optional[TechStack] = None
    language: Optional[str] = "en"

    def missing_fields(self) -> List[str]:
        missing = []
        if not self.consent: missing.append("consent")
        if not self.full_name: missing.append("full_name")
        if not self.email: missing.append("email")
        if not self.phone: missing.append("phone")
        if self.years_experience is None: missing.append("years_experience")
        if not self.desired_positions: missing.append("desired_positions")
        if not self.current_location: missing.append("current_location")
        if not self.tech_stack: missing.append("tech_stack")
        return missing

class Question(BaseModel):
    topic: str
    question: str
    difficulty: str
