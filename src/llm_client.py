from __future__ import annotations

from typing import Any

from src.prompts import (
    DIAGNOSIS_SYSTEM_PROMPT,
    RECOMMENDATION_SYSTEM_PROMPT,
    build_diagnosis_user_prompt,
    build_recommendation_user_prompt,
)
from src.utils import extract_json_object, normalize_action_candidates


class OpenRouterClient:
    def __init__(self, api_key: str | None, model: str = "openai/gpt-4o-mini") -> None:
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY is not configured.")
        from openai import OpenAI

        self.model = model
        self.client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)

    def diagnose(
        self,
        product_id: str,
        risk_summary: dict[str, Any],
        graph_context: list[str],
        available_actions: list[str],
    ) -> dict[str, Any]:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": DIAGNOSIS_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_diagnosis_user_prompt(product_id, risk_summary, graph_context, available_actions),
                },
            ],
            temperature=0.2,
        )
        raw_text = response.choices[0].message.content or ""
        try:
            parsed = normalize_action_candidates(extract_json_object(raw_text))
        except ValueError as exc:
            return {
                "diagnosis": "",
                "root_causes": [],
                "affected_nodes": [],
                "action_candidates": [],
                "raw_text": raw_text,
                "parse_error": str(exc),
            }
        parsed["raw_text"] = raw_text
        return parsed

    def summarize_recommendation(self, product_id: str, simulation_results: list[dict[str, Any]]) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": RECOMMENDATION_SYSTEM_PROMPT},
                {"role": "user", "content": build_recommendation_user_prompt(product_id, simulation_results)},
            ],
            temperature=0.3,
        )
        return response.choices[0].message.content or ""
