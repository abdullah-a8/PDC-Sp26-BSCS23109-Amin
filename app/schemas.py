from pydantic import BaseModel, ConfigDict, Field


class DocumentCreate(BaseModel):
    title: str = Field(..., min_length=1)
    content: str = ""


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    content: str
    version: int


class DocumentUpdate(BaseModel):
    """Body for the optimistic-locked PUT.

    The client must echo back the version it last read. If that version
    no longer matches the database row, another writer got there first and
    we reject the request with 409 Conflict.
    """

    content: str
    version: int = Field(..., ge=1)


class DocumentNaiveUpdate(BaseModel):
    """Body for the deliberately broken endpoint used to demonstrate the bug."""

    content: str
