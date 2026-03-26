import json
import os
import tempfile


FILE_PATH = "last_alert.json"


def load_last_alert():
    if not os.path.exists(FILE_PATH):
        return {}

    try:
        with open(FILE_PATH, "r") as file:
            return json.load(file)
    except (json.JSONDecodeError, ValueError):
        return {}


def save_last_alert(data):
    content = json.dumps(data, indent=4, default=str)
    dir_name = os.path.dirname(os.path.abspath(FILE_PATH))
    with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, suffix=".tmp") as f:
        f.write(content)
        tmp_path = f.name
    os.replace(tmp_path, FILE_PATH)


def should_send_alert(current):
    last = load_last_alert()

    if not last:
        save_last_alert(current)
        return True

    # compara pontos importantes
    if (
        current["symbol"] != last.get("symbol")
        or current["opportunity_type"] != last.get("opportunity_type")
        or current["priority_score"] > last.get("priority_score", 0)
    ):
        save_last_alert(current)
        return True

    return False