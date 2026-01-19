from pydantic.fields import Field
from datetime import datetime
from typing import Literal, Annotated

from ninja import File, Query, Router, Schema
from ninja.files import UploadedFile

from .models import Person

router = Router()


class PersonIn(Schema):
    name: str
    emails: list[str]
    phone: str | None = None
    address: str


class PersonOut(Schema):
    id: int
    name: str
    emails: list[str]
    phone: str | None = None
    created_at: datetime


@router.get("/", response=list[PersonOut])
def list_persons(request):
    return Person.objects.all()


@router.get("/{person_id}", response=PersonOut)
def get_person(request, person_id: int):
    return Person.objects.get(id=person_id)


@router.post("/", response=PersonOut)
def create_person(request, payload: PersonIn):
    return Person.objects.create(**payload.dict())


@router.put("/{person_id}", response=PersonOut)
def update_person(request, person_id: int, payload: PersonIn):
    person = Person.objects.get(id=person_id)
    for attr, value in payload.dict().items():
        setattr(person, attr, value)
    person.save()
    return person


@router.delete("/{person_id}")
def delete_person(request, person_id: int):
    person = Person.objects.get(id=person_id)
    person.delete()
    return {"success": True}


class PersonAddress(Schema):
    street: str
    city: str
    zip_code: str | None = None


class PersonFilter(Schema):
    name: str | None = None
    emails: list[str] | None = None
    address: PersonAddress


class PaginationParams(Schema):
    page: int = 1
    page_size: int = 20


class SimplePerson(PersonIn):
    type: Literal["simple"]


class ComplexPerson(PersonIn):
    type: Literal["complex"]


@router.get("/search/model", response=dict[str, PersonOut])
def search_persons_model(request, filters: Query[PersonFilter]):
    """Query params as a model."""
    qs = Person.objects.all()
    if filters.name:
        qs = qs.filter(name__icontains=filters.name)
    if filters.emails:
        qs = qs.filter(email__in=filters.emails)
    return qs


@router.get("/search/primitive", response=list[PersonOut])
def search_persons_primitive(request, name: str | None = None, limit: int = 10):
    """Query params as primitive annotations."""
    qs = Person.objects.all()
    if name:
        qs = qs.filter(name__icontains=name)
    return qs[:limit]


@router.get("/search/merged", response=list[PersonOut])
def search_persons_merged(
    request, filters: Query[PersonFilter], pagination: Query[PaginationParams]
):
    """Query params from multiple merged Schema models."""
    qs = Person.objects.all()
    if filters.name:
        qs = qs.filter(name__icontains=filters.name)
    offset = (pagination.page - 1) * pagination.page_size
    return qs[offset : offset + pagination.page_size]


@router.post("/upload")
def upload_file(
    request,
    body: Annotated[SimplePerson | ComplexPerson, Field(..., discriminator="type")],
    file_up: UploadedFile = File(...),
):
    """Multipart file upload endpoint."""
    return {
        "name": file_up.name,
        "size": file_up.size,
        "content_type": file_up.content_type,
    }


@router.post("/upload_file")
def upload_single(request, file: UploadedFile = File(...)):
    pass
