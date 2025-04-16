from typing import Generator
from sqlmodel import Session, create_engine
from config import CONFIG

user = CONFIG["db"]["user"]
password = CONFIG["db"]["password"]
host = CONFIG["db"]["host"]
port = CONFIG["db"]["port"]
db = CONFIG["db"]["db"]

engine = create_engine(f"mysql+pymysql://{user}:{password}@{host}:{port}/{db}")

def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session