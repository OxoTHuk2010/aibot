from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, Field, HttpUrl, field_validator

class SourceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    source_type: Literal['rss', 'telegram', 'html']