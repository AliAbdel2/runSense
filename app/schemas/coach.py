from pydantic import BaseModel, ConfigDict, Field


class CoachAskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=500)
    athlete_id: str = Field(default="sara", min_length=1, max_length=100)
