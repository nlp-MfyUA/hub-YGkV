from pydantic import BaseModel


class Relationship(BaseModel):
    source: str
    relation: str
    target: str


class RelationshipResult(BaseModel):
    relationships: list[Relationship]