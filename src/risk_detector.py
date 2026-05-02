from __future__ import annotations

from typing import Any

import pandas as pd


def _serving_warehouses(edges_df: pd.DataFrame, customer_id: str) -> list[str]:
    if edges_df.empty:
        return []
    mask = (edges_df["relationship"] == "SERVES") & (edges_df["target"].astype(str) == str(customer_id))
    return edges_df.loc[mask, "source"].astype(str).tolist()


def detect_risks(product_id: str, dataframes: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, dict[str, Any]]:
    demand_df = dataframes["demand"]
    inventory_df = dataframes["inventory"]
    safety_stock_df = dataframes["safety_stock"]
    priority_df = dataframes["customer_priority"]
    edges_df = dataframes.get("edges", pd.DataFrame())

    risks: list[dict[str, Any]] = []
    product_inventory = inventory_df[inventory_df["product_id"].astype(str) == product_id].copy()
    product_demand = demand_df[demand_df["product_id"].astype(str) == product_id].copy()

    stock_check = product_inventory.merge(
        safety_stock_df[safety_stock_df["product_id"].astype(str) == product_id],
        on=["product_id", "warehouse_id"],
        how="left",
    )
    for _, row in stock_check.iterrows():
        quantity = float(row.get("quantity", 0) or 0)
        safety_stock = float(row.get("safety_stock", 0) or 0)
        if quantity < safety_stock:
            risks.append(
                {
                    "risk_type": "inventory_below_safety_stock",
                    "severity": "medium",
                    "entity": row["warehouse_id"],
                    "message": f"{product_id} inventory at {row['warehouse_id']} is {quantity:g}, below safety stock {safety_stock:g}.",
                }
            )

    priority_map = dict(zip(priority_df["customer_id"].astype(str), priority_df["priority"].astype(str)))
    inventory_by_wh = product_inventory.groupby("warehouse_id")["quantity"].sum().to_dict()

    for _, row in product_demand.iterrows():
        customer_id = str(row["customer_id"])
        forecast_qty = float(row.get("forecast_qty", 0) or 0)
        warehouses = _serving_warehouses(edges_df, customer_id)
        available_qty = sum(float(inventory_by_wh.get(warehouse, 0) or 0) for warehouse in warehouses)
        if not warehouses:
            available_qty = float(product_inventory["quantity"].sum())
        shortage = max(forecast_qty - available_qty, 0)
        if shortage > 0:
            risks.append(
                {
                    "risk_type": "demand_fulfillment_risk",
                    "severity": "high",
                    "entity": customer_id,
                    "message": f"{customer_id} forecast demand is {forecast_qty:g}, but serving inventory is {available_qty:g}. Shortage risk is {shortage:g}.",
                }
            )
            if priority_map.get(customer_id) == "A":
                risks.append(
                    {
                        "risk_type": "critical_customer_risk",
                        "severity": "critical",
                        "entity": customer_id,
                        "message": f"Priority A customer {customer_id} may be affected by a shortage of {product_id}.",
                    }
                )

    risk_df = pd.DataFrame(risks)
    if risk_df.empty:
        risk_df = pd.DataFrame(columns=["risk_type", "severity", "entity", "message"])

    summary = {
        "product_id": product_id,
        "risk_count": len(risks),
        "total_demand": float(product_demand["forecast_qty"].sum()),
        "total_inventory": float(product_inventory["quantity"].sum()),
        "messages": risk_df["message"].tolist(),
    }
    return risk_df, summary
