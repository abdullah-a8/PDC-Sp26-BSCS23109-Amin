from sqlalchemy import Column, Integer, String, Text

from app.database import Base


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False, default="")
    # version is the optimistic-lock token. Every successful write bumps it by 1.
    # Clients must send the version they read; if it no longer matches the row,
    # the write is rejected with HTTP 409 instead of silently overwriting.
    version = Column(Integer, nullable=False, default=1)
