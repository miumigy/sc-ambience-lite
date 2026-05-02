from __future__ import annotations

import json
from typing import Any


DIAGNOSIS_SYSTEM_PROMPT = """
You are a supply chain risk diagnosis AI.
Use only facts retrieved from the Graph DB or CSV fallback and current
operational data from CSV. Do not invent facilities, customers, materials,
routes, products, or actions that are not supported by the provided context.
Return only a valid JSON object. All string values, including diagnosis,
root_causes, affected_nodes, action candidate titles, and action candidate
descriptions, must be written in English.
""".strip()


RECOMMENDATION_SYSTEM_PROMPT = """
You are a supply chain transformation consultant.
Based only on the simulation results, explain the situation in clear, concise,
and practical English for operations, planning, and management stakeholders.
Do not overstate certainty. Explicitly mention assumptions and items that a
human should verify before execution.
Always write the full recommendation summary in English.
""".strip()


def build_diagnosis_user_prompt(
    product_id: str,
    risk_summary: dict[str, Any],
    graph_context: list[str],
    available_actions: list[str],
) -> str:
    expected_schema = {
        "diagnosis": "English string",
        "root_causes": ["English string"],
        "affected_nodes": ["English string"],
        "action_candidates": [
            {
                "action_type": "transfer_inventory | prioritize_customer | no_action",
                "title": "English string",
                "description": "English string",
                "from": "string",
                "to": "string",
                "product": product_id,
                "quantity": 0,
            }
        ],
    }
    payload = {
        "product_id": product_id,
        "risk_summary": risk_summary,
        "graph_context": graph_context,
        "available_actions": available_actions,
        "simulation_can_evaluate": [
            "shortage_before",
            "shortage_after",
            "additional_cost",
            "service_level",
            "recommendation_score",
        ],
        "required_json_schema": expected_schema,
        "output_language": "English",
        "important_instruction": "Return JSON only. Do not include Japanese text in any field.",
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_recommendation_user_prompt(product_id: str, simulation_results: list[dict[str, Any]]) -> str:
    payload = {
        "product_id": product_id,
        "simulation_results": simulation_results,
        "please_explain": [
            "What is happening",
            "Why it matters",
            "Recommended action",
            "Expected impact",
            "Cautions and assumptions",
            "What humans should verify next",
        ],
        "output_language": "English",
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
