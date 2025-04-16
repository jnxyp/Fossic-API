from sqlalchemy import PrimaryKeyConstraint
from sqlmodel import Field, SQLModel

class ForumTypeOption(SQLModel, table=True):
    __tablename__ = 'pre_forum_typeoption'  # type: ignore
    # primary key
    optionid: int = Field(primary_key=True)
    # other fields
    title: str
    identifier: str
    type: str
    rules: str

class ForumTypeOptionVar(SQLModel, table=True):
    __tablename__ = 'pre_forum_typeoptionvar' # type: ignore
    __table_args__ = (
        PrimaryKeyConstraint('sortid', 'tid', 'fid', 'optionid'),
    )
    # primary keys
    sortid:str
    tid:int = Field(foreign_key='pre_forum_thread.tid')
    fid:int
    optionid:int = Field(foreign_key='pre_forum_typeoption.optionid')
    # other fields
    expiration:int
    value:str
    
class Thread(SQLModel, table=True):
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

