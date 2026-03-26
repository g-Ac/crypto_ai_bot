import json
from datetime import datetime


def export_analysis(results: list):
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "symbols": results
    }

    with open("technical_analysis.json", "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=4, default=str)