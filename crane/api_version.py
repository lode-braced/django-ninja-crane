from collections import defaultdict
from typing import Any, Literal, Tuple, cast

from ninja import NinjaAPI
from ninja.constants import NOT_SET
from ninja.openapi.schema import REF_TEMPLATE
from ninja.operation import Operation, PathView
from ninja.params import Body
from ninja.schema import NinjaGenerateJsonSchema
from pydantic import BaseModel

type AnyJson = dict[str, AnyJson] | list[AnyJson] | str | int | float | bool | None
type AnyJsonDict = dict[str, AnyJson]
type SchemaRef = str


class UnexpectedSchemaFormat(Exception):
    pass


type AnyAllOf = list[SchemaRef]


class FieldInfo(BaseModel):
    # the ref to the Pydantic schema that owns this field, if any.
    # Used to determine migration coverage: if defining migration actions for a specific schema, all field changes
    # marked as sourced by this schema will be considered "covered".
    #
    # Can only be set when models are "flattened" into one schema, e.g., with the Query/Path parameter models.
    source: str | None
    json_schema_specification: AnyJson
    required: bool


class PathOperation(BaseModel):
    method: Literal["get", "put", "post", "delete", "options", "head", "patch", "trace"]
    query_params: dict[str, FieldInfo]
    path_params: dict[str, FieldInfo]
    cookie_params: dict[str, FieldInfo]
    # If a request body is multipart, it will have a set of fields and the
    # "body" key with a ref, or anyof with multiple refs, array of refs.
    # We care about two types of changes to a response body:
    #  1. A non-body item (file) is added/changed/removed
    #  2. The request body is otherwise modified.
    # We capture 1. by detecting changes to the openapi schema for this operation, and 2. by detecting changes to
    # the schema referenced.
    request_body_schema: list[str]
    response_bodies: list[str]
    operation_id: str
    path: str


class ApiVersion(BaseModel):
    path_operations: dict[str, list[PathOperation]]
    schema_definitions: dict[SchemaRef, AnyJson] = {}


def _schema_to_refs(schema: dict[str, AnyJson]) -> AnyAllOf:
    if isinstance(ref := schema.get("$ref", None), str):
        return [ref]
    elif isinstance(any_of := schema.get("anyOf"), list):
        return [r for ref_list in any_of for r in _schema_to_refs(ref_list)]
    elif schema.get("type") == "array":
        return _schema_to_refs(cast(AnyJsonDict, schema["items"]))
    elif (
        schema.get("type") == "object"
        and not schema.get("properties", None)
        and schema.get("additionalProperties", None)
    ):
        # dict object with no other properties
        return _schema_to_refs(cast(AnyJsonDict, schema["additionalProperties"]))
    else:
        raise UnexpectedSchemaFormat(
            f"Schema {schema} is not a reference (or union typed to references). "
            f"Cannot detect schemas used for this endpoint."
        )


def _extract_operation_body(operation: Operation) -> tuple[AnyAllOf, dict[str, AnyJson]]:
    body_model: Body[Any] | None = next(
        (m for m in operation.models if m.__ninja_param_source__ == "body"), None
    )
    if not body_model:
        return [], {}
    else:
        # Converting the schema to body puts the body in the nested "body" or "payload" key of the schema object.
        # We then pass that key into the schema to refs.
        schema = body_model.model_json_schema(
            ref_template=REF_TEMPLATE,
            schema_generator=NinjaGenerateJsonSchema,
            mode="validation",
        ).copy()
        assert len(schema["$defs"]) > 0, "Expected schema defs in Body schema"
        body_property = (
            schema["properties"]["body"]
            if "body" in schema["properties"]
            else schema["properties"]["payload"]
        )
        assert body_property is not None, "Expected body property in Body/multipart schema"
        return _schema_to_refs(body_property), schema["$defs"]


def _extract_operation_responses(
    operation: Operation,
) -> Tuple[AnyAllOf, dict[str, AnyJson]]:
    schemas = {}
    schema_refs = []
    for status, model in operation.response_models.items():
        if model not in [None, NOT_SET]:
            schema = model.model_json_schema(
                ref_template=REF_TEMPLATE,
                schema_generator=NinjaGenerateJsonSchema,
                mode="serialization",
                by_alias=operation.by_alias,
            )
            schema_refs.extend(_schema_to_refs(schema["properties"]["response"]))
            schemas.update(schema["$defs"])
    return schema_refs, schemas


def get_openapi_operation_id(operation: "Operation") -> str:
    name = operation.view_func.__name__
    module = operation.view_func.__module__
    return (module + "_" + name).replace(".", "_")


def create_api_version(api: NinjaAPI) -> ApiVersion:
    schema_defs: dict[str, AnyJson] = {}
    path_operations: dict[str, list[PathOperation]] = defaultdict(list)
    for router_prefix, router in api._routers:
        path: PathView
        for path_str, path in router.path_operations.items():
            operation: Operation
            for operation in path.operations:
                op_body_ref, op_body_schemas = _extract_operation_body(operation)
                schema_defs.update(op_body_schemas)
                op_response_ref, op_response_schemas = _extract_operation_responses(operation)
                schema_defs.update(op_response_schemas)
                for method in operation.methods:
                    path_operations[path_str].append(
                        PathOperation(
                            method=method.lower(),
                            query_params={},
                            path_params={},
                            cookie_params={},
                            # pyrefly does
                            request_body_schema=op_body_ref,  # type: ignore
                            response_bodies=op_response_ref,  # type: ignore
                            operation_id=operation.operation_id
                            or get_openapi_operation_id(operation),  # type: ignore
                            path=path_str,
                        )
                    )

    return ApiVersion(
        path_operations=path_operations,  # type: ignore
        schema_definitions=schema_defs,  # type: ignore
    )
