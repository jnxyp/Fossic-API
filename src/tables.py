from functools import cache
from typing import Dict
from sqlalchemy import PrimaryKeyConstraint
from sqlmodel import Field, SQLModel, Session, col, select
from phpserialize import loads

class ForumTypeOption(SQLModel, table=True):
    __tablename__ = 'pre_forum_typeoption'  # type: ignore
    # primary key
    optionid: int = Field(primary_key=True)
    # other fields
    title: str
    identifier: str
    type: str
    rules: str
    
    @classmethod
    def get_options(cls, session:Session, optionid:int) -> Dict[str, str]:
        statement = select(cls).where(col(cls.optionid) == optionid).limit(1)
        result = session.exec(statement).first()
        
        if result is None:
            raise ValueError(f"Option with id {optionid} not found")
        
        return cls.extract_choices_from_rules(result.rules)
    
    @staticmethod
    def extract_choices_from_rules(rules: str) -> Dict[str, str]:
        choices = {}
        if 'choices' in rules:
            obj = loads(rules.encode('utf-8'))
            if isinstance(obj, dict):
                choices_str = obj['choices'.encode('utf-8')].decode('utf-8')
                for row in choices_str.split('\r\n'):
                    key, value = row.split('=')
                    choices[key.strip()] = value.strip()
            else:
                raise ValueError(f"Invalid rules format")
        else:
            raise ValueError(f"No choices found in rules")
        return choices
    
    @classmethod
    def get_game_versions(cls, session:Session) -> Dict[str, str]:
        return cls.get_options(session, 9)
    
    @classmethod
    def get_mod_languages(cls, session:Session) -> Dict[str, str]:
        return cls.get_options(session, 29)
    
    @classmethod
    def get_mod_dependencies(cls, session:Session) -> Dict[str, str]:
        return cls.get_options(session, 19)
    
    @classmethod
    def get_mod_types(cls, session:Session) -> Dict[str, str]:
        return cls.get_options(session, 12)
    
    @classmethod
    def get_mod_safe_rm(cls, session:Session) -> Dict[str, str]:
        return cls.get_options(session, 13)

class ForumTypeOptionVar(SQLModel, table=True):
    __tablename__ = 'pre_forum_typeoptionvar' # type: ignore
    __table_args__ = (
        PrimaryKeyConstraint('sortid', 'tid', 'fid', 'optionid'),
    )
    # primary keys
    sortid:int
    tid:int = Field(foreign_key='pre_forum_thread.tid')
    fid:int
    optionid:int = Field(foreign_key='pre_forum_typeoption.optionid')
    # other fields
    expiration:int
    value:str
    
class ForumThread(SQLModel, table=True):
    __tablename__ = 'pre_forum_thread'  # type: ignore
    # primary key
    tid: int = Field(primary_key=True)
    # other fields
    fid: int
    sortid: int
    author: str
    authorid: int
    subject: str
    digest: int # 是否精华帖 0 否 1-3 精华1-3
    recommends: int # 推荐数
    displayorder: int # 置顶帖 0 否 1-3 置顶1-3 删除 -1 审核 -2

if __name__ == "__main__":
    from db import get_session_sync
    session = get_session_sync()
    # test ForumTypeOption
    options = ForumTypeOption.get_mod_types(session)
    print(options)