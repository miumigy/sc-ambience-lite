from __future__ import annotations

from pathlib import Path

import pandas as pd


DATA_DIR = Path(__file__).resolve().parents[1] / "data"


REQUIRED_FILES = {
    "nodes": "nodes.csv",
    "edges": "edges.csv",
    "demand": "demand.csv",
    "inventory": "inventory.csv",
    "safety_stock": "safety_stock.csv",
    "transport_options": "transport_options.csv",
    "customer_priority": "customer_priority.csv",
}


def load_csv(filename: str) -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / filename)


def load_all_data() -> dict[str, pd.DataFrame]:
    return {name: load_csv(filename) for name, filename in REQUIRED_FILES.items()}


def get_product_ids(nodes_df: pd.DataFrame, demand_df: pd.DataFrame, inventory_df: pd.DataFrame) -> list[str]:
    product_ids: set[str] = set()
    if {"id", "type"}.issubset(nodes_df.columns):
        product_ids.update(nodes_df.loc[nodes_df["type"] == "Product", "id"].astype(str).tolist())
    if "product_id" in demand_df.columns:
        product_ids.update(demand_df["product_id"].astype(str).tolist())
    if "product_id" in inventory_df.columns:
        product_ids.update(inventory_df["product_id"].astype(str).tolist())
    return sorted(product_ids)
