from __future__ import annotations

import os
from pathlib import Path
from tempfile import mkstemp

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import networkx as nx

from src.constants import PRODUCT_CONTEXT_MAX_HOPS
from src.utils import get_nodes_for_edges, get_subgraph_edges


NODE_STYLES = {
    "Supplier": {"color": "#8dd3c7", "shape": "box"},
    "Material": {"color": "#ffffb3", "shape": "diamond"},
    "Factory": {"color": "#bebada", "shape": "database"},
    "Product": {"color": "#fb8072", "shape": "star"},
    "Warehouse": {"color": "#80b1d3", "shape": "triangle"},
    "Customer": {"color": "#fdb462", "shape": "dot"},
}


TYPE_Y_POSITIONS = {
    "Supplier": -280,
    "Material": -150,
    "Product": 0,
    "Factory": 140,
    "Warehouse": 270,
    "Customer": 420,
}


def build_network_from_csv(
    nodes_df: pd.DataFrame,
    edges_df: pd.DataFrame,
    selected_product_id: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    nodes = nodes_df.copy()
    edges = edges_df.copy()
    selected_edges = (
        get_subgraph_edges(edges, selected_product_id, max_hops=PRODUCT_CONTEXT_MAX_HOPS)
        if selected_product_id
        else edges.iloc[0:0]
    )
    selected_node_ids = set(selected_edges["source"].astype(str)).union(set(selected_edges["target"].astype(str)))
    if selected_product_id:
        selected_node_ids.add(selected_product_id)
    nodes["is_selected_context"] = nodes["id"].astype(str).isin(selected_node_ids)
    edges["is_selected_context"] = edges.index.isin(selected_edges.index)
    return nodes, edges


def build_subgraph_from_edges(
    nodes_df: pd.DataFrame,
    edges_df: pd.DataFrame,
    center_node_id: str,
    max_hops: int = PRODUCT_CONTEXT_MAX_HOPS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    sub_edges = get_subgraph_edges(edges_df, center_node_id, max_hops=max_hops)
    sub_nodes = get_nodes_for_edges(nodes_df, sub_edges, extra_node_ids={center_node_id})
    return sub_nodes, sub_edges


def _node_title(row: pd.Series) -> str:
    return f"{row.get('type', 'Node')}: {row.get('name', row.get('id', ''))}"


def _component_layout(nodes_df: pd.DataFrame, edges_df: pd.DataFrame) -> dict[str, dict[str, int | bool]]:
    graph = nx.Graph()
    graph.add_nodes_from(nodes_df["id"].astype(str).tolist())
    graph.add_edges_from((str(row["source"]), str(row["target"])) for _, row in edges_df.iterrows())

    node_type_by_id = dict(zip(nodes_df["id"].astype(str), nodes_df["type"].astype(str)))
    product_order = {"P1": 0, "P2": 1, "P3": 2}
    products = sorted(
        [node_id for node_id in graph.nodes if node_type_by_id.get(node_id) == "Product"],
        key=lambda node_id: (product_order.get(node_id, 99), node_id),
    )

    if len(products) > 1:
        spacing = 780
        start_x = -spacing * (len(products) - 1) / 2
        product_centers = {product_id: start_x + index * spacing for index, product_id in enumerate(products)}
        distances = {
            product_id: nx.single_source_shortest_path_length(graph, product_id)
            for product_id in products
        }
        product_groups: dict[tuple[str, str], list[str]] = {}

        for node_id in sorted(graph.nodes):
            nearest_product = min(
                products,
                key=lambda product_id: (
                    distances[product_id].get(node_id, 999),
                    product_order.get(product_id, 99),
                    product_id,
                ),
            )
            node_type = node_type_by_id.get(node_id, "Node")
            product_groups.setdefault((nearest_product, node_type), []).append(node_id)

        layout: dict[str, dict[str, int | bool]] = {}
        for (product_id, node_type), node_ids in product_groups.items():
            count = len(node_ids)
            for index, node_id in enumerate(sorted(node_ids)):
                x_offset = (index - (count - 1) / 2) * 150
                y = TYPE_Y_POSITIONS.get(node_type, 0)
                layout[node_id] = {"x": int(product_centers[product_id] + x_offset), "y": int(y), "physics": True}
        return layout

    def component_key(component: set[str]) -> tuple[int, str]:
        products = sorted(node_id for node_id in component if node_type_by_id.get(node_id) == "Product")
        if products:
            return (product_order.get(products[0], 99), products[0])
        return (99, sorted(component)[0])

    components = sorted(nx.connected_components(graph), key=component_key)
    layout: dict[str, dict[str, int | bool]] = {}
    spacing = 700
    start_x = -spacing * (len(components) - 1) / 2

    for component_index, component in enumerate(components):
        center_x = start_x + component_index * spacing
        type_counts: dict[str, int] = {}
        for node_id in sorted(component):
            node_type = node_type_by_id.get(node_id, "Node")
            type_counts[node_type] = type_counts.get(node_type, 0) + 1

        type_seen: dict[str, int] = {}
        for node_id in sorted(component):
            node_type = node_type_by_id.get(node_id, "Node")
            index = type_seen.get(node_type, 0)
            type_seen[node_type] = index + 1
            count = type_counts[node_type]
            x_offset = (index - (count - 1) / 2) * 150
            y = TYPE_Y_POSITIONS.get(node_type, 0)
            layout[node_id] = {"x": int(center_x + x_offset), "y": int(y), "physics": True}

    return layout


def _add_nodes(
    network: Network,
    nodes_df: pd.DataFrame,
    selected_product_id: str | None,
    positions: dict[str, dict[str, int | bool]] | None = None,
) -> None:
    for _, row in nodes_df.fillna("").iterrows():
        node_id = str(row["id"])
        node_type = str(row.get("type", "Node"))
        style = NODE_STYLES.get(node_type, {"color": "#d9d9d9", "shape": "dot"})
        is_product = node_type == "Product"
        is_selected = bool(row.get("is_selected_context", False)) or node_id == selected_product_id
        size = 34 if node_id == selected_product_id else 27 if is_product else 18
        border_width = 5 if node_id == selected_product_id else 3 if is_selected else 1
        color = {
            "background": style["color"],
            "border": "#b91c1c" if node_id == selected_product_id else "#2563eb" if is_selected else "#374151",
            "highlight": {"background": "#fecaca", "border": "#991b1b"},
        }
        network.add_node(
            node_id,
            label=f"{node_id}\n{row.get('name', node_id)}",
            title=_node_title(row),
            shape=style["shape"],
            color=color,
            size=size,
            borderWidth=border_width,
            font={"size": 18 if is_product else 14},
            **(positions or {}).get(node_id, {}),
        )


def _add_edges(network: Network, edges_df: pd.DataFrame) -> None:
    for _, row in edges_df.fillna("").iterrows():
        is_selected = bool(row.get("is_selected_context", False))
        network.add_edge(
            str(row["source"]),
            str(row["target"]),
            label=str(row["relationship"]),
            title=str(row.get("description", "")),
            color="#dc2626" if is_selected else "#6b7280",
            width=4 if is_selected else 2,
            arrows="to",
            font={"align": "middle", "size": 12},
        )


def _render_pyvis(nodes_df: pd.DataFrame, edges_df: pd.DataFrame, selected_product_id: str | None, height: int) -> None:
    from pyvis.network import Network

    network = Network(height=f"{height}px", width="100%", directed=True, bgcolor="#ffffff", font_color="#111827")
    network.barnes_hut(gravity=-4500, central_gravity=0.12, spring_length=190, spring_strength=0.015)
    positions = _component_layout(nodes_df, edges_df)
    _add_nodes(network, nodes_df, selected_product_id, positions)
    _add_edges(network, edges_df)
    network.set_options(
        """
        {
          "interaction": {"hover": true, "navigationButtons": true, "keyboard": true},
          "layout": {"improvedLayout": false},
          "physics": {
            "stabilization": {"iterations": 350, "fit": true},
            "barnesHut": {
              "gravitationalConstant": -4500,
              "centralGravity": 0.12,
              "springLength": 190,
              "springConstant": 0.015,
              "avoidOverlap": 0.65
            },
            "minVelocity": 0.75
          },
          "edges": {"smooth": {"type": "dynamic"}}
        }
        """
    )
    fd, tmp_name = mkstemp(suffix=".html")
    os.close(fd)
    html_path = Path(tmp_name)
    try:
        network.write_html(str(html_path), notebook=False, open_browser=False)
        components.html(html_path.read_text(encoding="utf-8"), height=height + 40, scrolling=True)
    finally:
        html_path.unlink(missing_ok=True)


def _fallback_table(nodes_df: pd.DataFrame, edges_df: pd.DataFrame, error: Exception) -> None:
    st.warning(f"Network visualization could not be rendered. Showing tables instead. Details: {error}")
    st.dataframe(nodes_df, use_container_width=True)
    st.dataframe(edges_df, use_container_width=True)


def render_network(
    nodes_df: pd.DataFrame,
    edges_df: pd.DataFrame,
    selected_product_id: str | None = None,
    height: int = 600,
) -> None:
    try:
        nodes, edges = build_network_from_csv(nodes_df, edges_df, selected_product_id)
        _render_pyvis(nodes, edges, selected_product_id, height)
    except Exception as exc:
        _fallback_table(nodes_df, edges_df, exc)


def render_subgraph(
    nodes_df: pd.DataFrame,
    edges_df: pd.DataFrame,
    center_node_id: str,
    height: int = 500,
) -> None:
    try:
        sub_nodes, sub_edges = build_subgraph_from_edges(
            nodes_df,
            edges_df,
            center_node_id,
            max_hops=PRODUCT_CONTEXT_MAX_HOPS,
        )
        sub_nodes = sub_nodes.copy()
        sub_edges = sub_edges.copy()
        sub_nodes["is_selected_context"] = True
        sub_edges["is_selected_context"] = True
        _render_pyvis(sub_nodes, sub_edges, center_node_id, height)
    except Exception as exc:
        _fallback_table(nodes_df, edges_df, exc)
