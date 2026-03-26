import database as db


def save_log(data: dict):
    db.insert_analysis_log(data)
