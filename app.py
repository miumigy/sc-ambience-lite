from __future__ import annotations

import pandas as pd
import streamlit as st

from src.config import load_config
from src.constants import PRODUCT_CONTEXT_MAX_HOPS
from src.data_loader import get_product_ids, load_all_data
from src.graph_client import Neo4jClient
from src.graph_seed import seed_sample_graph
from src.llm_client import OpenRouterClient
from src.risk_detector import detect_risks
from src.simulator import run_simulations
from src.utils import build_graph_context_from_csv, get_nodes_for_edges, get_subgraph_edges
from src.visualizer import render_network, render_subgraph


AVAILABLE_ACTIONS = ["transfer_inventory", "prioritize_customer", "no_action"]
TAB_LABELS = [
    "Supply Chain Map",
    "Data",
    "Risk Detection",
    "Graph Context",
    "AI Diagnosis",
    "Simulation",
    "Recommendation",
]


st.set_page_config(page_title="Supply Chain Ambience Lite", layout="wide")


@st.cache_data
def cached_data() -> dict[str, pd.DataFrame]:
    return load_all_data()


def get_neo4j_client():
    config = load_config()
    return Neo4jClient(config.neo4j_uri, config.neo4j_username, config.neo4j_password, config.neo4j_database)


def activate_tab(tab_name: str) -> None:
    if tab_name in TAB_LABELS:
        st.session_state["active_tab"] = tab_name


def show_product_context_badge(label: str, executed_product_id: str, current_product_id: str) -> None:
    st.caption(f"{label}: Product ID `{executed_product_id}`")
    if executed_product_id != current_product_id:
        st.warning(
            f"This result was generated for `{executed_product_id}`, "
            f"while the current sidebar selection is `{current_product_id}`. "
            "Run the action again to refresh it for the selected product."
        )


def get_graph_context(product_id: str, dataframes: dict[str, pd.DataFrame]) -> tuple[list[str], str]:
    try:
        client = get_neo4j_client()
        try:
            client.verify_connectivity()
            context = client.get_product_context(product_id, max_hops=PRODUCT_CONTEXT_MAX_HOPS)
            if context:
                return context, "Neo4j"
        finally:
            client.close()
    except Exception as exc:
        st.info(f"Neo4j context retrieval skipped. CSV fallback is used. Details: {exc}")
    return (
        build_graph_context_from_csv(
            dataframes["nodes"],
            dataframes["edges"],
            product_id,
            max_hops=PRODUCT_CONTEXT_MAX_HOPS,
        ),
        "CSV fallback",
    )


def run_ai_diagnosis(product_id: str, risk_summary: dict, graph_context: list[str]) -> None:
    config = load_config()
    st.session_state["diagnosis_product_id"] = product_id
    try:
        client = OpenRouterClient(config.openrouter_api_key, config.openrouter_model)
        st.session_state["diagnosis"] = client.diagnose(product_id, risk_summary, graph_context, AVAILABLE_ACTIONS)
        st.session_state["diagnosis_error"] = None
    except Exception as exc:
        st.session_state["diagnosis"] = None
        st.session_state["diagnosis_error"] = str(exc)


def run_recommendation_summary(product_id: str, simulation_df: pd.DataFrame) -> None:
    config = load_config()
    st.session_state["recommendation_product_id"] = product_id
    try:
        client = OpenRouterClient(config.openrouter_api_key, config.openrouter_model)
        st.session_state["recommendation_summary"] = client.summarize_recommendation(
            product_id,
            simulation_df.to_dict("records"),
        )
        st.session_state["recommendation_error"] = None
    except Exception as exc:
        st.session_state["recommendation_summary"] = None
        st.session_state["recommendation_error"] = str(exc)


dataframes = cached_data()
product_ids = get_product_ids(dataframes["nodes"], dataframes["demand"], dataframes["inventory"])
default_index = product_ids.index("P1") if "P1" in product_ids else 0

st.title("Supply Chain Ambience Lite")
st.caption("Graph DB and LLM powered action recommendation MVP for supply chain risk.")

with st.sidebar:
    st.header("Controls")
    product_id = st.selectbox("Product ID", product_ids, index=default_index)

    if st.button("Check Neo4j connection"):
        try:
            client = get_neo4j_client()
            try:
                client.verify_connectivity()
                st.success("Neo4j connection verified.")
            finally:
                client.close()
            activate_tab("Graph Context")
        except Exception as exc:
            st.error(f"Neo4j connection failed: {exc}")
            activate_tab("Graph Context")

    if st.button("Seed sample data to Neo4j"):
        try:
            client = get_neo4j_client()
            try:
                seed_sample_graph(client, dataframes["nodes"], dataframes["edges"])
                st.success("Sample graph data seeded to Neo4j.")
            finally:
                client.close()
            activate_tab("Supply Chain Map")
        except Exception as exc:
            st.error(f"Neo4j seed failed: {exc}")
            activate_tab("Supply Chain Map")

risk_df, risk_summary = detect_risks(product_id, dataframes)
graph_context, graph_context_source = get_graph_context(product_id, dataframes)

with st.sidebar:
    if st.button("Run AI diagnosis"):
        run_ai_diagnosis(product_id, risk_summary, graph_context)
        activate_tab("AI Diagnosis")

    if st.button("Run simulation"):
        diagnosis = st.session_state.get("diagnosis") or {}
        candidates = diagnosis.get("action_candidates", [])
        st.session_state["simulation_df"] = run_simulations(candidates, dataframes, product_id)
        st.session_state["simulation_product_id"] = product_id
        activate_tab("Simulation")

    if st.button("Generate recommendation summary"):
        simulation_df = st.session_state.get("simulation_df")
        if simulation_df is None:
            st.warning("Run simulation first.")
            activate_tab("Simulation")
        else:
            run_recommendation_summary(product_id, simulation_df)
            activate_tab("Recommendation")

active_tab = st.session_state.get("active_tab", "Supply Chain Map")
tabs = st.tabs(TAB_LABELS, default=active_tab, key=f"main_tabs_{active_tab}")

with tabs[0]:
    st.subheader("Overall Supply Chain Network")
    render_network(dataframes["nodes"], dataframes["edges"], selected_product_id=product_id, height=620)

    st.subheader(f"Subgraph around {product_id}")
    render_subgraph(dataframes["nodes"], dataframes["edges"], center_node_id=product_id, height=520)

    sub_edges = get_subgraph_edges(dataframes["edges"], product_id, max_hops=PRODUCT_CONTEXT_MAX_HOPS)
    sub_nodes = get_nodes_for_edges(dataframes["nodes"], sub_edges, extra_node_ids={product_id})

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### Nodes")
        st.dataframe(dataframes["nodes"], use_container_width=True)
        st.markdown(f"#### Related nodes for {product_id}")
        st.dataframe(sub_nodes, use_container_width=True)
    with col2:
        st.markdown("#### Relationships")
        st.dataframe(dataframes["edges"], use_container_width=True)
        st.markdown(f"#### Related edges for {product_id}")
        st.dataframe(sub_edges, use_container_width=True)

with tabs[1]:
    st.subheader("Current Situation Data")
    for name, df in dataframes.items():
        with st.expander(name, expanded=name in {"demand", "inventory", "safety_stock"}):
            st.dataframe(df, use_container_width=True)

with tabs[2]:
    st.subheader("Risk Detection")
    show_product_context_badge("Current calculation", product_id, product_id)
    st.json(risk_summary)
    if risk_df.empty:
        st.success("No risk detected by the current pandas rules.")
    else:
        st.dataframe(risk_df, use_container_width=True)

with tabs[3]:
    st.subheader("Graph Context")
    show_product_context_badge("Current graph context", product_id, product_id)
    st.caption(f"Source: {graph_context_source}")
    if graph_context:
        for item in graph_context:
            st.write(f"- {item}")
    else:
        st.warning("No graph context found for the selected product.")

with tabs[4]:
    st.subheader("AI Diagnosis by OpenRouter")
    diagnosis_product_id = st.session_state.get("diagnosis_product_id")
    if diagnosis_product_id:
        show_product_context_badge("Diagnosis result", diagnosis_product_id, product_id)
    if st.session_state.get("diagnosis_error"):
        st.error(st.session_state["diagnosis_error"])
    diagnosis = st.session_state.get("diagnosis")
    if diagnosis:
        if diagnosis.get("parse_error"):
            st.warning(f"LLM response could not be parsed as JSON: {diagnosis['parse_error']}")
        st.json({k: v for k, v in diagnosis.items() if k != "raw_text"})
        with st.expander("Raw LLM response"):
            st.write(diagnosis.get("raw_text", ""))
    else:
        st.info("Run AI diagnosis from the sidebar. CSV, graph, risk, and simulation features work without OpenRouter.")

with tabs[5]:
    st.subheader("Simulation")
    simulation_df = st.session_state.get("simulation_df")
    simulation_product_id = st.session_state.get("simulation_product_id")
    if simulation_df is None:
        show_product_context_badge("Preview calculation", product_id, product_id)
        st.info("Run simulation from the sidebar. Without AI candidates, the app still evaluates no_action.")
        preview_df = run_simulations([], dataframes, product_id)
        st.dataframe(preview_df, use_container_width=True)
    else:
        show_product_context_badge("Simulation result", simulation_product_id or product_id, product_id)
        st.dataframe(simulation_df, use_container_width=True)

with tabs[6]:
    st.subheader("Recommendation Summary")
    simulation_df = st.session_state.get("simulation_df")
    recommendation_product_id = st.session_state.get("recommendation_product_id")
    simulation_product_id = st.session_state.get("simulation_product_id")
    if recommendation_product_id:
        show_product_context_badge("Recommendation result", recommendation_product_id, product_id)
    elif simulation_product_id:
        show_product_context_badge("Simulation result shown below", simulation_product_id, product_id)
    if simulation_df is not None:
        st.markdown("#### Simulation Results")
        st.dataframe(simulation_df, use_container_width=True)
    if st.session_state.get("recommendation_error"):
        st.error(st.session_state["recommendation_error"])
    if st.session_state.get("recommendation_summary"):
        st.markdown(st.session_state["recommendation_summary"])
    else:
        st.info("Generate a recommendation summary from the sidebar after running simulation.")
