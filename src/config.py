from __future__ import annotations

import os
from dataclasses import dataclass


def _get_streamlit_secret(key: str) -> str | None:
    try:
        import streamlit as st

        value = st.secrets.get(key)
        return str(value) if value else None
    except Exception:
        return None


def get_config_value(key: str, default: str | None = None) -> str | None:
    return _get_streamlit_secret(key) or os.getenv(key) or default


@dataclass(frozen=True)
class AppConfig:
    openrouter_api_key: str | None
    openrouter_model: str
    neo4j_uri: str | None
    neo4j_username: str | None
    neo4j_password: str | None
    neo4j_database: str | None


def load_config() -> AppConfig:
    neo4j_uri = get_config_value("NEO4J_URI")
    neo4j_username = get_config_value("NEO4J_USERNAME", "neo4j")
    neo4j_database = (get_config_value("NEO4J_DATABASE") or "").strip() or None
    return AppConfig(
        openrouter_api_key=get_config_value("OPENROUTER_API_KEY"),
        openrouter_model=get_config_value("OPENROUTER_MODEL", "openai/gpt-4o-mini") or "openai/gpt-4o-mini",
        neo4j_uri=neo4j_uri,
        neo4j_username=neo4j_username,
        neo4j_password=get_config_value("NEO4J_PASSWORD"),
        neo4j_database=neo4j_database,
    )
