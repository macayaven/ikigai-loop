"""Adapter from deploy-agent output to verify-checker input."""

FIELD_MAP = {
    "november_deploys": "monthly_deploys.november",
}


class MissingProvenance(ValueError):
    pass


def to_verify_input(agent_output: dict, source_data: dict) -> dict:
    ledger = source_data.get("ledger", {})
    monthly = ledger.get("monthly_deploys", {})
    notes = ledger.get("ticket_notes", {})
    metrics = {"monthly_deploys." + k: v for k, v in monthly.items()}
    facts = {k: v for k, v in notes.items()}
    labels = {}
    if "monthly_deploys.november" in metrics:
        labels["monthly_deploys.november"] = ["November", "deploys"]
    if "monthly_deploys.october" in metrics:
        labels["monthly_deploys.october"] = ["deploys"]
    order = []
    if "monthly_deploys.october" in metrics and "monthly_deploys.november" in metrics:
        order = [["monthly_deploys.october", "monthly_deploys.november"]]
    claims = []
    for st in agent_output.get("report", {}).get("statements", []):
        metric_refs = []
        for fig in st.get("figures", []):
            field = fig.get("field")
            if field not in FIELD_MAP:
                raise MissingProvenance(field)
            metric_refs.append(
                {"metric_id": FIELD_MAP[field], "value": fig.get("figure")}
            )
        claims.append(
            {
                "id": st.get("sid"),
                "text": st.get("sentence"),
                "fact_ids": list(st.get("note_refs", [])),
                "metric_refs": metric_refs,
            }
        )
    return {
        "claims": claims,
        "facts": facts,
        "metrics": metrics,
        "labels": labels,
        "order": order,
    }
