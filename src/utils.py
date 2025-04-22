from config import CONFIG


fossic_url = CONFIG["fossic"]["url"]

def get_thread_url(tid: int) -> str:
    return f"{fossic_url}/thread-{tid}-1-1.html"

def date_string_to_timestamp(date_string: str) -> int:
    from datetime import datetime
    dt = datetime.strptime(date_string, '%Y-%m-%d')
    return int(dt.timestamp())