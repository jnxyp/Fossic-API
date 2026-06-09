from config import CONFIG


fossic_url = CONFIG["fossic"]["url"]

def get_thread_url(tid: int) -> str:
    return f"{fossic_url}/thread-{tid}-1-1.html"

def date_string_to_timestamp(date_string: str) -> int:
    from datetime import datetime, timezone, timedelta
    # modUpdateDate 是用户在中文论坛手动填写的日期，按 CST (UTC+8) 解释
    cst = timezone(timedelta(hours=8))
    dt = datetime.strptime(date_string, '%Y-%m-%d').replace(tzinfo=cst)
    return int(dt.timestamp())