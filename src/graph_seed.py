from __future__ import annotations

import pandas as pd

from src.graph_client import Neo4jClient


def seed_sample_graph(client: Neo4jClient, nodes_df: pd.DataFrame, edges_df: pd.DataFrame) -> None:
    client.clear_database()
    client.seed_graph(nodes_df, edges_df)
