from __future__ import annotations

import json
from collections import deque
from typing import Any

import pandas as pd


RELATIONSHIP_PHRASES = {
    "SUPPLIES": "{source} supplies {target}",
    "CONSUMED_BY": "{target} consumes {source}",
    "PRODUCED_AT": "{source} is produced at {target}",
    "STORED_AT": "{source} is stored at {target}",
    "SERVES": "{source} serves {target}",
    "CAN_TRANSFER_TO": "{source} can transfer inventory to {target}",
    "CAN_SUBSTITUTE": "{source} can substitute {target}",
}


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract the first valid JSON object from an LLM response."""
    decoder = json.JSONDecoder()
    stripped = text.strip()
    for index, char in enumerate(stripped):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(stripped[index:])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    raise ValueError("No valid JSON object found in the LLM response.")


def normalize_action_candidates(parsed: dict[str, Any]) -> dict[str, Any]:
    parsed.setdefault("diagnosis", "")
    parsed.setdefault("root_causes", [])
    parsed.setdefault("affected_nodes", [])
    parsed.setdefault("action_candidates", [])
    if not isinstance(parsed["action_candidates"], list):
        parsed["action_candidates"] = []
    return parsed


def node_label_map(nodes_df: pd.DataFrame) -> dict[str, str]:
    labels: dict[str, str] = {}
    for row in nodes_df.fillna("").to_dict("records"):
        node_id = str(row.get("id", ""))
        node_type = str(row.get("type", "Node"))
        name = str(row.get("name", node_id))
        default_label = f"{node_type} {node_id}"
        labels[node_id] = default_label if name == node_id else name if name == default_label else f"{default_label} ({name})"
    return labels


def _build_adjacency(edges_df: pd.DataFrame) -> dict[str, list[tuple[str, int]]]:
    adjacency: dict[str, list[tuple[str, int]]] = {}
    for idx, row in edges_df.reset_index(drop=True).iterrows():
        source = str(row["source"])
        target = str(row["target"])
        adjacency.setdefault(source, []).append((target, idx))
        adjacency.setdefault(target, []).append((source, idx))
    return adjacency


def get_subgraph_edges(edges_df: pd.DataFrame, center_node_id: str, max_hops: int = 4) -> pd.DataFrame:
    if edges_df.empty or not center_node_id:
        return edges_df.iloc[0:0].copy()

    adjacency = _build_adjacency(edges_df)
    visited_nodes = {center_node_id}
    visited_edge_indexes: set[int] = set()
    queue: deque[tuple[str, int]] = deque([(center_node_id, 0)])

    while queue:
        node_id, depth = queue.popleft()
        if depth >= max_hops:
            continue
        for neighbor, edge_index in adjacency.get(node_id, []):
            visited_edge_indexes.add(edge_index)
            if neighbor not in visited_nodes:
                visited_nodes.add(neighbor)
                queue.append((neighbor, depth + 1))

    if not visited_edge_indexes:
        return edges_df.iloc[0:0].copy()
    return edges_df.iloc[sorted(visited_edge_indexes)].copy()


def get_nodes_for_edges(nodes_df: pd.DataFrame, edges_df: pd.DataFrame, extra_node_ids: set[str] | None = None) -> pd.DataFrame:
    node_ids: set[str] = set(extra_node_ids or set())
    if not edges_df.empty:
        node_ids.update(edges_df["source"].astype(str).tolist())
        node_ids.update(edges_df["target"].astype(str).tolist())
    return nodes_df[nodes_df["id"].astype(str).isin(node_ids)].copy()


def describe_edge(row: pd.Series, labels: dict[str, str]) -> str:
    source = labels.get(str(row["source"]), str(row["source"]))
    target = labels.get(str(row["target"]), str(row["target"]))
    relationship = str(row["relationship"])
    template = RELATIONSHIP_PHRASES.get(relationship, "{source} -> {target}")
    return template.format(source=source, target=target)


def build_graph_context_from_csv(
    nodes_df: pd.DataFrame,
    edges_df: pd.DataFrame,
    product_id: str,
    max_hops: int = 4,
) -> list[str]:
    subgraph_edges = get_subgraph_edges(edges_df, product_id, max_hops=max_hops)
    labels = node_label_map(nodes_df)
    context: list[str] = []
    seen: set[str] = set()
    for _, row in subgraph_edges.iterrows():
        text = describe_edge(row, labels)
        if text not in seen:
            seen.add(text)
            context.append(text)
    return context
