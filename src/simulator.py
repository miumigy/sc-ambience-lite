from __future__ import annotations

from typing import Any

import pandas as pd


def _product_frames(dataframes: dict[str, pd.DataFrame], product_id: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    demand_df = dataframes["demand"]
    inventory_df = dataframes["inventory"]
    return (
        demand_df[demand_df["product_id"].astype(str) == product_id].copy(),
        inventory_df[inventory_df["product_id"].astype(str) == product_id].copy(),
    )


def _serving_inventory_by_customer(
    demand_df: pd.DataFrame,
    inventory_df: pd.DataFrame,
    edges_df: pd.DataFrame,
) -> dict[str, float]:
    inventory_by_wh = inventory_df.groupby("warehouse_id")["quantity"].sum().to_dict()
    result: dict[str, float] = {}
    for customer_id in demand_df["customer_id"].astype(str).unique():
        serving_edges = edges_df[(edges_df["relationship"] == "SERVES") & (edges_df["target"].astype(str) == customer_id)]
        warehouses = serving_edges["source"].astype(str).tolist()
        result[customer_id] = sum(float(inventory_by_wh.get(warehouse, 0) or 0) for warehouse in warehouses)
        if not warehouses:
            result[customer_id] = float(inventory_df["quantity"].sum())
    return result


def _metrics(dataframes: dict[str, pd.DataFrame], product_id: str, inventory_override: pd.DataFrame | None = None) -> dict[str, float]:
    demand_df, inventory_df = _product_frames(dataframes, product_id)
    if inventory_override is not None:
        inventory_df = inventory_override[inventory_override["product_id"].astype(str) == product_id].copy()
    serving_inventory = _serving_inventory_by_customer(demand_df, inventory_df, dataframes["edges"])
    total_demand = float(demand_df["forecast_qty"].sum())
    fulfilled = 0.0
    shortage = 0.0
    for _, row in demand_df.iterrows():
        customer_id = str(row["customer_id"])
        demand_qty = float(row.get("forecast_qty", 0) or 0)
        available_qty = serving_inventory.get(customer_id, 0.0)
        fulfilled += min(demand_qty, available_qty)
        shortage += max(demand_qty - available_qty, 0.0)
    service_level = fulfilled / total_demand if total_demand else 1.0
    return {"shortage": shortage, "service_level": service_level}


def _priority_bonus(dataframes: dict[str, pd.DataFrame], action_type: str) -> float:
    priority_df = dataframes["customer_priority"]
    has_a_customer = (priority_df["priority"].astype(str) == "A").any()
    if action_type in {"transfer_inventory", "prioritize_customer"} and has_a_customer:
        return 15.0
    return 0.0


def _scenario_result(
    scenario_name: str,
    action_type: str,
    before: dict[str, float],
    after: dict[str, float],
    additional_cost: float,
    comment: str,
    dataframes: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    shortage_reduction = before["shortage"] - after["shortage"]
    score = shortage_reduction * 5 - additional_cost / 1000 + _priority_bonus(dataframes, action_type)
    return {
        "scenario_name": scenario_name,
        "action_type": action_type,
        "shortage_before": round(before["shortage"], 2),
        "shortage_after": round(after["shortage"], 2),
        "shortage_reduction": round(shortage_reduction, 2),
        "additional_cost": round(additional_cost, 2),
        "service_level_before": round(before["service_level"], 4),
        "service_level_after": round(after["service_level"], 4),
        "recommendation_score": round(score, 2),
        "comment": comment,
    }


def simulate_no_action(dataframes: dict[str, pd.DataFrame], product_id: str) -> dict[str, Any]:
    before = _metrics(dataframes, product_id)
    return _scenario_result(
        "No action",
        "no_action",
        before,
        before,
        0.0,
        "No additional cost, but detected shortage and safety stock risks remain.",
        dataframes,
    )


def simulate_transfer_inventory(
    action: dict[str, Any],
    dataframes: dict[str, pd.DataFrame],
    product_id: str,
) -> dict[str, Any]:
    before = _metrics(dataframes, product_id)
    inventory_df = dataframes["inventory"].copy()
    transport_df = dataframes["transport_options"]

    from_wh = str(action.get("from") or action.get("from_warehouse") or "")
    to_wh = str(action.get("to") or action.get("to_warehouse") or "")
    action_product = str(action.get("product") or product_id)
    requested_qty = pd.to_numeric(action.get("quantity", 0), errors="coerce")
    requested_qty = 0.0 if pd.isna(requested_qty) else max(float(requested_qty), 0.0)

    option = transport_df[
        (transport_df["from_warehouse"].astype(str) == from_wh)
        & (transport_df["to_warehouse"].astype(str) == to_wh)
        & (transport_df["product_id"].astype(str) == action_product)
    ]
    if option.empty or action_product != product_id:
        return _scenario_result(
            f"Invalid transfer {from_wh}->{to_wh}",
            "transfer_inventory",
            before,
            before,
            0.0,
            "Transfer skipped because the route or product is not available in transport_options.csv.",
            dataframes,
        )

    option_row = option.iloc[0]
    max_qty = float(option_row.get("max_qty", 0) or 0)
    cost_per_unit = float(option_row.get("cost_per_unit", 0) or 0)
    source_mask = (
        (inventory_df["product_id"].astype(str) == product_id)
        & (inventory_df["warehouse_id"].astype(str) == from_wh)
    )
    source_qty = float(inventory_df.loc[source_mask, "quantity"].sum())
    transfer_qty = min(requested_qty, max_qty, source_qty)

    if transfer_qty <= 0:
        return _scenario_result(
            f"Transfer {from_wh}->{to_wh}",
            "transfer_inventory",
            before,
            before,
            0.0,
            "Transfer quantity was adjusted to zero because source inventory or requested quantity was unavailable.",
            dataframes,
        )

    target_mask = (
        (inventory_df["product_id"].astype(str) == product_id)
        & (inventory_df["warehouse_id"].astype(str) == to_wh)
    )
    inventory_df.loc[source_mask, "quantity"] = inventory_df.loc[source_mask, "quantity"] - transfer_qty
    if target_mask.any():
        inventory_df.loc[target_mask, "quantity"] = inventory_df.loc[target_mask, "quantity"] + transfer_qty
    else:
        inventory_df = pd.concat(
            [
                inventory_df,
                pd.DataFrame([{"product_id": product_id, "warehouse_id": to_wh, "quantity": transfer_qty}]),
            ],
            ignore_index=True,
        )

    after = _metrics(dataframes, product_id, inventory_override=inventory_df)
    additional_cost = transfer_qty * cost_per_unit
    lead_time = option_row.get("lead_time_days", "")
    return _scenario_result(
        f"Transfer {transfer_qty:g} units {from_wh}->{to_wh}",
        "transfer_inventory",
        before,
        after,
        additional_cost,
        f"Moved {transfer_qty:g} units from {from_wh} to {to_wh}. Estimated lead time is {lead_time} days.",
        dataframes,
    )


def simulate_prioritize_customer(
    action: dict[str, Any],
    dataframes: dict[str, pd.DataFrame],
    product_id: str,
) -> dict[str, Any]:
    before = _metrics(dataframes, product_id)
    after = {"shortage": max(before["shortage"] * 0.5, 0), "service_level": min(before["service_level"] + 0.1, 1.0)}
    return _scenario_result(
        str(action.get("title") or "Prioritize A customers"),
        "prioritize_customer",
        before,
        after,
        1000.0,
        "A-rank customers are protected first. Validate allocation impact on lower-priority customers before execution.",
        dataframes,
    )


def run_simulations(
    action_candidates: list[dict[str, Any]] | None,
    dataframes: dict[str, pd.DataFrame],
    product_id: str,
) -> pd.DataFrame:
    results = [simulate_no_action(dataframes, product_id)]
    for action in action_candidates or []:
        action_type = str(action.get("action_type", ""))
        if action_type == "transfer_inventory":
            results.append(simulate_transfer_inventory(action, dataframes, product_id))
        elif action_type == "prioritize_customer":
            results.append(simulate_prioritize_customer(action, dataframes, product_id))
        elif action_type == "no_action":
            continue
        else:
            before = _metrics(dataframes, product_id)
            results.append(
                _scenario_result(
                    str(action.get("title") or "Unsupported action"),
                    action_type or "unsupported",
                    before,
                    before,
                    0.0,
                    f"Unsupported action_type '{action_type}' was ignored by the simulator.",
                    dataframes,
                )
            )
    return pd.DataFrame(results).sort_values("recommendation_score", ascending=False, ignore_index=True)
