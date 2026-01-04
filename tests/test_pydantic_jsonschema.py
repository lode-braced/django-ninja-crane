from ninja import Schema
from pydantic import BaseModel


class Child(BaseModel):
    foo: str
    bar: int


class Child2(BaseModel):
    child: Child
    foo: str
    bar: str


class Parent(Schema):
    children: list[Child2]


def test_generate_schema():
    _json_schema = Parent.json_schema()
    pass
