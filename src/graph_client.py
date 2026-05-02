from __future__ import annotations

from typing import Any

import pandas as pd

from src.constants import PRODUCT_CONTEXT_MAX_HOPS


ALLOWED_NODE_TYPES = {"Supplier", "Material", "Factory", "Product", "Warehouse", "Customer"}
ALLOWED_RELATIONSHIPS = {
    "SUPPLIES",
    "CONSUMED_BY",
    "PRODUCED_AT",
    "STORED_AT",
    "SERVES",
    "CAN_TRANSFER_TO",
    "CAN_SUBSTITUTE",
}


class Neo4jClient:
    def __init__(self, uri: str | None, username: str | None, password: str | None, database: str | None = None) -> None:
        if not uri or not username or not password:
            raise ValueError("Neo4j credentials are not configured.")
        from neo4j import GraphDatabase

        self.database = database
        self.driver = GraphDatabase.driver(uri, auth=(username, password))

    def _session(self):
        if self.database:
            return self.driver.session(database=self.database)
        return self.driver.session()

    @staticmethod
    def _is_database_not_found_error(exc: Exception) -> bool:
        text = str(exc)
        return "DatabaseNotFound" in text or "Database does not exist" in text or "DatabaseNotFound" in exc.__class__.__name__

    def _run_with_home_database_retry(self, operation):
        try:
            with self._session() as session:
                return operation(session)
        except Exception as exc:
            if not self._is_database_not_found_error(exc):
                raise

            discovered_database = self._discover_home_database()
            if not discovered_database:
                raise

            self.database = discovered_database
            with self.driver.session(database=discovered_database) as session:
                return operation(session)

    def _discover_home_database(self) -> str | None:
        """Find the writable Aura database when the configured name is wrong."""
        try:
            with self.driver.session(database="system") as session:
                rows = session.run(
                    """
                    SHOW DATABASES
                    YIELD name, currentStatus, home
                    RETURN name, currentStatus, home
                    ORDER BY home DESC, name
                    """
                ).data()
        except Exception:
            return None

        online_rows = [row for row in rows if row.get("currentStatus") == "online" and row.get("name") != "system"]
        for row in online_rows:
            if row.get("home"):
                return str(row["name"])
        if online_rows:
            return str(online_rows[0]["name"])
        return None

    def close(self) -> None:
        self.driver.close()

    def verify_connectivity(self) -> bool:
        self.driver.verify_connectivity()
        return True

    def clear_database(self) -> None:
        def operation(session):
            session.run("MATCH (n) DETACH DELETE n").consume()

        self._run_with_home_database_retry(operation)

    def seed_graph(self, nodes_df: pd.DataFrame, edges_df: pd.DataFrame) -> None:
        def operation(session):
            for row in nodes_df.fillna("").to_dict("records"):
                node_type = str(row["type"])
                if node_type not in ALLOWED_NODE_TYPES:
                    raise ValueError(f"Unsupported node type: {node_type}")
                query = f"MERGE (n:{node_type} {{id: $id}}) SET n.name = $name, n.type = $type"
                session.run(query, id=str(row["id"]), name=str(row["name"]), type=node_type).consume()

            for row in edges_df.fillna("").to_dict("records"):
                relationship = str(row["relationship"])
                if relationship not in ALLOWED_RELATIONSHIPS:
                    raise ValueError(f"Unsupported relationship: {relationship}")
                query = (
                    "MATCH (source {id: $source_id}) "
                    "MATCH (target {id: $target_id}) "
                    f"MERGE (source)-[r:{relationship}]->(target) "
                    "SET r.description = $description"
                )
                session.run(
                    query,
                    source_id=str(row["source"]),
                    target_id=str(row["target"]),
                    description=str(row.get("description", "")),
                ).consume()

        self._run_with_home_database_retry(operation)

    def get_product_context(self, product_id: str, max_hops: int = PRODUCT_CONTEXT_MAX_HOPS) -> list[str]:
        safe_max_hops = max(1, min(int(max_hops), 6))
        query = f"""
        MATCH path = (p:Product {{id: $product_id}})-[*1..{safe_max_hops}]-(n)
        RETURN relationships(path) AS rels
        """
        context: list[str] = []
        seen: set[str] = set()

        def operation(session):
            result = session.run(query, product_id=product_id)
            for record in result:
                for rel in record["rels"]:
                    text = self._relationship_to_text(rel)
                    if text not in seen:
                        seen.add(text)
                        context.append(text)

        self._run_with_home_database_retry(operation)
        return context

    @staticmethod
    def _node_label(node: Any) -> str:
        node_type = node.get("type", "Node")
        node_id = node.get("id", "")
        name = node.get("name", node_id)
        return f"{node_type} {node_id}" if name == node_id else f"{node_type} {node_id} ({name})"

    def _relationship_to_text(self, rel: Any) -> str:
        source = self._node_label(rel.start_node)
        target = self._node_label(rel.end_node)
        description = rel.get("description")
        if description:
            return f"{description} [{source} -> {target}]"
        return f"{source} -{rel.type}-> {target}"
