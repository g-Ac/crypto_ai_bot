import json
from datetime import datetime
from runtime_config import RELEVANT_OPPORTUNITIES_FILE


def export_relevant_opportunities(results: list):
    relevant = [
        item for item in results
        if item["opportunity_type"] in ["pre_sinal", "sinal"]
    ]

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(relevant),
        "opportunities": relevant
    }

    with open(RELEVANT_OPPORTUNITIES_FILE, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=4, default=str)
