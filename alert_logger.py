import database as db


def save_alert(data: dict, alert_type: str):
    db.insert_alert(data, alert_type)
