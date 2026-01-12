from collections import defaultdict
from typing import TYPE_CHECKING, Any, Generator, Literal, Tuple, Type, cast

if TYPE_CHECKING:
    from crane.delta import HttpMethod

from ninja import NinjaAPI
from ninja.constants import NOT_SET
from ninja.openapi.schema import OpenAPISchema, REF_TEMPLATE
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
    openapi_json: AnyJsonDict


class ApiVersion(BaseModel):
    path_operations: dict[str, list[PathOperation]]
    schema_definitions: dict[SchemaRef, AnyJson] = {}


def _schema_to_refs(schema: dict[str, AnyJson]) -> AnyAllOf:
    if isinstance(ref := schema.get("$ref", None), str):
        return [ref]
    elif isinstance(any_of := schema.get("anyOf"), list):
        return [
            r
            for ref_list in any_of
            if isinstance(ref_list, dict)
            for r in _schema_to_refs(ref_list)
        ]
    elif isinstance(one_of := schema.get("oneOf"), list):
        return [
            r
            for ref_list in one_of
            if isinstance(ref_list, dict)
            for r in _schema_to_refs(ref_list)
        ]
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
    view_func = operation.view_func
    name = getattr(view_func, "__name__", "unknown")
    module = getattr(view_func, "__module__", "unknown")
    return (module + "_" + name).replace(".", "_")


def _is_ninja_generated_model(model: type) -> bool:
    """Check if a model is dynamically generated by Django Ninja."""
    module = getattr(model, "__module__", None)
    # Ninja generates models in its own modules
    if module and module.startswith("ninja."):
        return True
    # Ninja-generated models have names like "endpoint_name_QueryParams"
    name = getattr(model, "__name__", "")
    if name.endswith("Params") and "_" in name:
        return True
    return False


def _get_model_qualname(model: type) -> str | None:
    """Get the Python qualname for a Pydantic model, or None if dynamically generated."""
    if _is_ninja_generated_model(model):
        return None
    module = getattr(model, "__module__", None)
    qualname = getattr(model, "__qualname__", None)
    if module and qualname:
        return f"{module}.{qualname}"
    return None


def _is_user_pydantic_model(cls: Any) -> bool:
    """Check if cls is a user-defined Pydantic model (not dynamically generated)."""
    try:
        if not issubclass(cls, BaseModel):
            return False
        return not _is_ninja_generated_model(cls)
    except TypeError:
        return False


def _trace_to_source_model(model: type[BaseModel], path: tuple[str, ...]) -> type | None:
    """
    Given a model and a path of field names, return the model that owns the final field.

    For PersonFilter with path ("address", "street"):
    - PersonFilter has field "address" of type PersonAddress
    - PersonAddress owns "street" -> return PersonAddress
    """
    if not path or not _is_user_pydantic_model(model):
        return None

    current_model = model
    for field_name in path[:-1]:
        field_info = current_model.model_fields.get(field_name)
        if not field_info:
            return None
        field_type = field_info.annotation
        if not _is_user_pydantic_model(field_type):
            return None
        current_model = cast(Type[BaseModel], field_type)

    return current_model


def _build_field_source_map(model: Type[BaseModel]) -> dict[str, str | None]:
    """
    Build a mapping from flattened field names to their source model qualnames.

    For PersonFilter with nested PersonAddress:
    - "name" -> "test_app.api.PersonFilter"
    - "email" -> "test_app.api.PersonFilter"
    - "street" -> "test_app.api.PersonAddress"
    - "city" -> "test_app.api.PersonAddress"

    For primitives (dynamically generated):
    - "name" -> None
    - "limit" -> None
    """
    flatten_map: dict[str, tuple[str, ...]] = getattr(model, "__ninja_flatten_map__", {})
    if not flatten_map:
        return {}

    result: dict[str, str | None] = {}

    for flat_name, path in flatten_map.items():
        if len(path) == 1:
            # Single-level param - check if it's from a Pydantic model field
            param_name = path[0]
            field_info = model.model_fields.get(param_name)
            if field_info and _is_user_pydantic_model(field_info.annotation):
                result[flat_name] = _get_model_qualname(cast(type[Any], field_info.annotation))
            else:
                result[flat_name] = None
        else:
            # Nested field - trace through the model hierarchy
            param_name = path[0]
            field_info = model.model_fields.get(param_name)
            if not field_info:
                result[flat_name] = None
                continue

            annotation = field_info.annotation
            if _is_user_pydantic_model(annotation):
                source_model = _trace_to_source_model(annotation, path[1:])
                result[flat_name] = _get_model_qualname(source_model) if source_model else None
            else:
                result[flat_name] = None

    return result


def _flatten_field_properties(
    prop_name: str,
    prop_details: dict[str, Any],
    prop_required: bool,
    definitions: dict[str, Any],
) -> Generator[tuple[str, dict[str, Any], bool], None, None]:
    """
    Flatten nested model properties into individual field schemas.
    Adapted from ninja.openapi.schema.flatten_properties.
    """
    if "$ref" in prop_details:
        def_name = prop_details["$ref"].split("/")[-1]
        definition = definitions.get(def_name, {})
        yield from _flatten_field_properties(prop_name, definition, prop_required, definitions)

    elif "properties" in prop_details:
        required = set(prop_details.get("required", []))
        for k, v in prop_details["properties"].items():
            is_required = k in required
            yield from _flatten_field_properties(k, v, is_required, definitions)

    elif "allOf" in prop_details:
        for item in prop_details["allOf"]:
            if "$ref" in item:
                def_name = item["$ref"].rsplit("/", 1)[-1]
                item = definitions.get(def_name, item)
            yield from _flatten_field_properties(prop_name, item, prop_required, definitions)

    else:
        yield prop_name, prop_details, prop_required


def _extract_param_fields(
    operation: Operation,
    param_source: str,
) -> tuple[dict[str, FieldInfo], dict[str, AnyJson]]:
    """
    Extract parameters for a given source type and return FieldInfo dict and schema definitions.

    Handles multiple merged param models (e.g., multiple Query[Model] annotations on one endpoint).
    """
    models = [m for m in operation.models if m.__ninja_param_source__ == param_source]

    if not models:
        return {}, {}

    result: dict[str, FieldInfo] = {}
    all_definitions: dict[str, AnyJson] = {}

    for model in models:
        schema = model.model_json_schema(
            ref_template=REF_TEMPLATE,
            schema_generator=NinjaGenerateJsonSchema,
            mode="validation",
        )

        required_fields = set(schema.get("required", []))
        properties = schema.get("properties", {})
        definitions = schema.get("$defs", {})
        all_definitions.update(definitions)

        source_map = _build_field_source_map(model)

        for field_name, field_schema in properties.items():
            for flat_name, flat_schema, is_required in _flatten_field_properties(
                field_name, field_schema, field_name in required_fields, definitions
            ):
                result[flat_name] = FieldInfo(
                    source=source_map.get(flat_name),
                    json_schema_specification=flat_schema,
                    required=is_required,
                )

    return result, all_definitions


def _convert_defs_to_component_keys(defs: dict[str, AnyJson]) -> dict[str, AnyJson]:
    """Convert $defs keys to OpenAPI component schema ref format."""
    return {REF_TEMPLATE.format(model=name): schema for name, schema in defs.items()}


def _normalize_json_keys(obj: Any) -> AnyJson:
    """Recursively convert all dict keys to strings for JSON compatibility."""
    if isinstance(obj, dict):
        return {str(k): _normalize_json_keys(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_normalize_json_keys(item) for item in obj]
    else:
        return obj


class _OperationSchemaExtractor(OpenAPISchema):
    """Helper to extract OpenAPI JSON for individual operations without triggering full schema generation."""

    def __init__(self, api: NinjaAPI) -> None:
        # Initialize without calling parent __init__ to avoid triggering get_paths()
        self.api = api
        self.path_prefix = ""
        self.schemas: dict[str, Any] = {}
        self.securitySchemes: dict[str, Any] = {}
        self.all_operation_ids: set[str] = set()

    def get_operation_json(self, operation: Operation) -> AnyJsonDict:
        """Get the full OpenAPI JSON for a single operation."""
        raw = self.operation_details(operation)
        return cast(AnyJsonDict, _normalize_json_keys(raw))


def create_api_version(api: NinjaAPI) -> ApiVersion:
    schema_defs: dict[str, AnyJson] = {}
    path_operations: dict[str, list[PathOperation]] = defaultdict(list)
    schema_extractor = _OperationSchemaExtractor(api)

    for router_prefix, router in api._routers:
        path: PathView
        for path_str, path in router.path_operations.items():
            operation: Operation
            for operation in path.operations:
                op_body_ref, op_body_schemas = _extract_operation_body(operation)
                schema_defs.update(op_body_schemas)
                op_response_ref, op_response_schemas = _extract_operation_responses(operation)
                schema_defs.update(op_response_schemas)

                query_params, query_schemas = _extract_param_fields(operation, "query")
                schema_defs.update(query_schemas)
                path_params, path_schemas = _extract_param_fields(operation, "path")
                schema_defs.update(path_schemas)
                cookie_params, cookie_schemas = _extract_param_fields(operation, "cookie")
                schema_defs.update(cookie_schemas)

                openapi_json = schema_extractor.get_operation_json(operation)

                for method in operation.methods:
                    path_operations[router_prefix + path_str].append(
                        PathOperation(
                            method=cast("HttpMethod", method.lower()),
                            query_params=query_params,  # type: ignore
                            path_params=path_params,  # type: ignore
                            cookie_params=cookie_params,  # type: ignore
                            request_body_schema=op_body_ref,  # type: ignore
                            response_bodies=op_response_ref,  # type: ignore
                            operation_id=operation.operation_id
                            or get_openapi_operation_id(operation),  # type: ignore
                            path=router_prefix + path_str,
                            openapi_json=openapi_json,
                        )
                    )

    return ApiVersion(
        path_operations=path_operations,  # type: ignore
        schema_definitions=_convert_defs_to_component_keys(schema_defs),  # type: ignore
    )
