from __future__ import annotations

import json
import os
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MappingReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    equivalent_event: bool
    exhaustive_outcomes: bool
    confidence: float = Field(ge=0, le=1)
    reasoning: str
    warnings: list[str]


class LLMEventMatcher:
    @property
    def available(self) -> bool:
        return bool(os.getenv("OPENAI_API_KEY"))

    async def review(self, candidate: dict[str, Any]) -> MappingReview:
        if not self.available:
            raise RuntimeError("OPENAI_API_KEY is missing.")
        from openai import AsyncOpenAI

        schema = MappingReview.model_json_schema()
        response = await AsyncOpenAI().responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
            input=[
                {
                    "role": "system",
                    "content": (
                        "You review prediction-market event equivalence. Compare resolution "
                        "criteria, deadlines, cancellation treatment, event scope, and every "
                        "mapped outcome. Be conservative. Do not calculate prices or recommend trades."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "name": candidate["name"],
                            "description": candidate.get("description"),
                            "mappings": candidate["mappings"],
                        }
                    ),
                },
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "mapping_review",
                    "schema": schema,
                    "strict": True,
                }
            },
        )
        return MappingReview.model_validate_json(response.output_text)
