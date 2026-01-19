from typing import Annotated, Literal, Union, cast

from pydantic import BaseModel, Field

from crane.api_version import AnyJson, AnyJsonDict, ApiVersion, FieldInfo, PathOperation

type HttpMethod = Literal["get", "put", "post", "delete", "options", "head", "patch", "trace"]
type ParamLocation = Literal["query", "path", "cookie"]

_MISSING = object()  # Sentinel for distinguishing "key not present" from "value is None"


# === Operation-Level Actions ===


class OperationAdded(BaseModel):
    """Operation exists in new but not in old."""

    action: Literal["operation_added"] = "operation_added"
    path: str
    method: HttpMethod
    new_operation: PathOperation


class OperationRemoved(BaseModel):
    """Operation exists in old but not in new."""

    action: Literal["operation_removed"] = "operation_removed"
    path: str
    method: HttpMethod
    old_operation: PathOperation


class OperationModified(BaseModel):
    """Operation changed between versions.

    For openapi_json, stores:
    - Changed top-level keys (operationId, summary, tags, security, deprecated, etc.)
    - For 'parameters': only individual parameters that differ
    - For 'responses': only individual status codes that differ
    - For 'requestBody': if changed

    For structured fields, stores diffs of:
    - query_params, path_params, cookie_params (with FieldInfo for migration coverage)
    - request_body_schema, response_bodies (schema refs)
    """

    action: Literal["operation_modified"] = "operation_modified"
    path: str
    method: HttpMethod
    # OpenAPI JSON diffs (only changed keys)
    old_openapi_json: AnyJsonDict
    new_openapi_json: AnyJsonDict
    # Structured field diffs (only changed params)
    old_params: dict[ParamLocation, dict[str, FieldInfo]]
    new_params: dict[ParamLocation, dict[str, FieldInfo]]
    # Body/response refs if changed (empty lists if unchanged)
    old_body_refs: list[str]
    new_body_refs: list[str]
    old_response_refs: list[str]
    new_response_refs: list[str]


# === Schema-Level Actions ===


class SchemaDefinitionAdded(BaseModel):
    """Schema definition exists in new but not in old."""

    action: Literal["schema_definition_added"] = "schema_definition_added"
    schema_ref: str
    new_schema: AnyJson


class SchemaDefinitionRemoved(BaseModel):
    """Schema definition exists in old but not in new."""

    action: Literal["schema_definition_removed"] = "schema_definition_removed"
    schema_ref: str
    old_schema: AnyJson


class SchemaDefinitionModified(BaseModel):
    """Schema definition changed between versions.

    Stores:
    - Changed top-level keys (title, type, required, etc.)
    - For 'properties': only the individual properties that differ
    """

    action: Literal["schema_definition_modified"] = "schema_definition_modified"
    schema_ref: str
    old_schema: AnyJson  # Changed keys (properties contains only changed props)
    new_schema: AnyJson  # Changed keys (properties contains only changed props)


# === Union and Container ===

OperationAction = OperationAdded | OperationRemoved | OperationModified

SchemaAction = SchemaDefinitionAdded | SchemaDefinitionRemoved | SchemaDefinitionModified

MigrationAction = Annotated[Union[OperationAction, SchemaAction], Field(discriminator="action")]


class VersionDelta(BaseModel):
    """Describes all changes between old and new versions. Can be applied in either direction."""

    actions: list[MigrationAction]


# === Delta Creation ===


def _build_operation_map(
    api_version: ApiVersion,
) -> dict[tuple[str, HttpMethod], PathOperation]:
    """Build a map of (path, method) -> PathOperation for easier lookup."""
    result: dict[tuple[str, HttpMethod], PathOperation] = {}
    for path, operations in api_version.path_operations.items():
        for op in operations:
            result[(path, op.method)] = op
    return result


def _diff_openapi_json(
    old_json: AnyJsonDict, new_json: AnyJsonDict
) -> tuple[AnyJsonDict, AnyJsonDict]:
    """Compute diff of openapi_json, returning only changed keys.

    For 'parameters' and 'responses', computes granular diffs.
    """
    old_diff: AnyJsonDict = {}
    new_diff: AnyJsonDict = {}

    all_keys = set(old_json.keys()) | set(new_json.keys())

    for key in all_keys:
        old_val = old_json.get(key, _MISSING)
        new_val = new_json.get(key, _MISSING)

        if old_val == new_val:
            continue

        if key == "parameters":
            # Diff individual parameters by name
            old_list = cast(
                list[AnyJson],
                old_val if old_val is not _MISSING and isinstance(old_val, list) else [],
            )
            new_list = cast(
                list[AnyJson],
                new_val if new_val is not _MISSING and isinstance(new_val, list) else [],
            )
            old_params = {_param_key(p): p for p in old_list}
            new_params = {_param_key(p): p for p in new_list}
            old_param_diff, new_param_diff = _diff_dict(old_params, new_params)
            if old_param_diff or new_param_diff:
                old_diff["parameters"] = list(old_param_diff.values())
                new_diff["parameters"] = list(new_param_diff.values())

        elif key == "responses":
            # Diff individual response status codes
            old_responses = (old_val if old_val is not _MISSING else {}) or {}
            new_responses = (new_val if new_val is not _MISSING else {}) or {}
            old_resp_diff, new_resp_diff = _diff_dict(
                cast(dict[str, AnyJson], old_responses),
                cast(dict[str, AnyJson], new_responses),
            )
            if old_resp_diff or new_resp_diff:
                old_diff["responses"] = old_resp_diff
                new_diff["responses"] = new_resp_diff

        else:
            # Other keys: include if different (including None values)
            if old_val is not _MISSING:
                old_diff[key] = cast(AnyJson, old_val)
            if new_val is not _MISSING:
                new_diff[key] = cast(AnyJson, new_val)

    return old_diff, new_diff


def _param_key(param: AnyJson) -> str:
    """Create a unique key for a parameter based on name and location."""
    if isinstance(param, dict):
        return f"{param.get('in', '')}:{param.get('name', '')}"
    return str(param)


def _diff_dict(
    old: dict[str, AnyJson], new: dict[str, AnyJson]
) -> tuple[dict[str, AnyJson], dict[str, AnyJson]]:
    """Diff two dicts, returning only keys that differ."""
    old_diff: dict[str, AnyJson] = {}
    new_diff: dict[str, AnyJson] = {}

    all_keys = set(old.keys()) | set(new.keys())
    for key in all_keys:
        old_val: AnyJson | object = old.get(key, _MISSING)
        new_val: AnyJson | object = new.get(key, _MISSING)
        if old_val != new_val:
            if old_val is not _MISSING:
                old_diff[key] = cast(AnyJson, old_val)
            if new_val is not _MISSING:
                new_diff[key] = cast(AnyJson, new_val)

    return old_diff, new_diff


def _diff_params(
    old_op: PathOperation, new_op: PathOperation
) -> tuple[dict[ParamLocation, dict[str, FieldInfo]], dict[ParamLocation, dict[str, FieldInfo]]]:
    """Diff structured params between operations, returning only changed params."""
    old_params: dict[ParamLocation, dict[str, FieldInfo]] = {}
    new_params: dict[ParamLocation, dict[str, FieldInfo]] = {}

    for loc in ("query", "path", "cookie"):
        old_loc_params: dict[str, FieldInfo] = getattr(old_op, f"{loc}_params")
        new_loc_params: dict[str, FieldInfo] = getattr(new_op, f"{loc}_params")

        old_loc_diff: dict[str, FieldInfo] = {}
        new_loc_diff: dict[str, FieldInfo] = {}

        all_names = set(old_loc_params.keys()) | set(new_loc_params.keys())
        for name in all_names:
            old_field = old_loc_params.get(name)
            new_field = new_loc_params.get(name)
            if old_field != new_field:
                if old_field is not None:
                    old_loc_diff[name] = old_field
                if new_field is not None:
                    new_loc_diff[name] = new_field

        if old_loc_diff:
            old_params[loc] = old_loc_diff
        if new_loc_diff:
            new_params[loc] = new_loc_diff

    return old_params, new_params


def _diff_refs(old_refs: list[str], new_refs: list[str]) -> tuple[list[str], list[str]]:
    """Return refs that differ (empty lists if identical)."""
    if set(old_refs) == set(new_refs):
        return [], []
    return old_refs, new_refs


def _compare_operations(
    old_op: PathOperation,
    new_op: PathOperation,
    path: str,
    method: HttpMethod,
) -> OperationModified | None:
    """Compare two operations and return OperationModified if they differ."""
    # Check if anything differs
    if old_op == new_op:
        return None

    # Compute openapi_json diff
    old_json_diff, new_json_diff = _diff_openapi_json(old_op.openapi_json, new_op.openapi_json)

    # Compute structured param diffs
    old_params, new_params = _diff_params(old_op, new_op)

    # Compute body/response ref diffs
    old_body_refs, new_body_refs = _diff_refs(
        old_op.request_body_schema, new_op.request_body_schema
    )
    old_response_refs, new_response_refs = _diff_refs(
        old_op.response_bodies, new_op.response_bodies
    )

    # If all diffs are empty, there's no semantic change (e.g., only parameter order differs)
    has_changes = (
        old_json_diff
        or new_json_diff
        or old_params
        or new_params
        or old_body_refs
        or new_body_refs
        or old_response_refs
        or new_response_refs
    )
    if not has_changes:
        return None

    return OperationModified(
        path=path,
        method=method,
        old_openapi_json=old_json_diff,
        new_openapi_json=new_json_diff,
        old_params=old_params,
        new_params=new_params,
        old_body_refs=old_body_refs,
        new_body_refs=new_body_refs,
        old_response_refs=old_response_refs,
        new_response_refs=new_response_refs,
    )


def _diff_schema(
    old_schema: AnyJsonDict, new_schema: AnyJsonDict
) -> tuple[AnyJsonDict, AnyJsonDict]:
    """Compute diff of schema definitions, returning only changed keys.

    For 'properties', computes granular property-level diffs.
    """
    old_diff: AnyJsonDict = {}
    new_diff: AnyJsonDict = {}

    all_keys = set(old_schema.keys()) | set(new_schema.keys())

    for key in all_keys:
        old_val = old_schema.get(key, _MISSING)
        new_val = new_schema.get(key, _MISSING)

        if old_val == new_val:
            continue

        if key == "properties":
            # Diff individual properties
            old_props = cast(dict[str, AnyJson], (old_val if old_val is not _MISSING else {}) or {})
            new_props = cast(dict[str, AnyJson], (new_val if new_val is not _MISSING else {}) or {})
            old_prop_diff, new_prop_diff = _diff_dict(old_props, new_props)
            if old_prop_diff or new_prop_diff:
                old_diff["properties"] = old_prop_diff
                new_diff["properties"] = new_prop_diff

        else:
            # Other keys: include if different (including None values)
            if old_val is not _MISSING:
                old_diff[key] = cast(AnyJson, old_val)
            if new_val is not _MISSING:
                new_diff[key] = cast(AnyJson, new_val)

    return old_diff, new_diff


def create_delta(old: ApiVersion, new: ApiVersion) -> VersionDelta:
    """
    Create a delta describing all changes between two API versions.

    The delta can be applied in either direction:
    - Forwards (old -> new): to rebuild ApiVersion from deltas only
    - Backwards (new -> old): for runtime migrations to older API versions
    """
    actions: list[MigrationAction] = []

    # Build operation maps for easier lookup
    old_ops = _build_operation_map(old)
    new_ops = _build_operation_map(new)

    type OpKey = tuple[str, HttpMethod]
    old_keys: set[OpKey] = set(old_ops.keys())
    new_keys: set[OpKey] = set(new_ops.keys())

    # Operations added in new
    for key in new_keys - old_keys:
        actions.append(
            OperationAdded(
                path=key[0],
                method=key[1],
                new_operation=new_ops[key],
            )
        )

    # Operations removed in new
    for key in old_keys - new_keys:
        actions.append(
            OperationRemoved(
                path=key[0],
                method=key[1],
                old_operation=old_ops[key],
            )
        )

    # Operations that exist in both - compare their contents
    for key in old_keys & new_keys:
        modified = _compare_operations(old_ops[key], new_ops[key], key[0], key[1])
        if modified:
            actions.append(modified)

    # Compare schema definitions
    old_schemas = old.schema_definitions
    new_schemas = new.schema_definitions

    old_schema_refs = set(old_schemas.keys())
    new_schema_refs = set(new_schemas.keys())

    # Schemas added in new
    for ref in new_schema_refs - old_schema_refs:
        actions.append(
            SchemaDefinitionAdded(
                schema_ref=ref,
                new_schema=new_schemas[ref],
            )
        )

    # Schemas removed in new
    for ref in old_schema_refs - new_schema_refs:
        actions.append(
            SchemaDefinitionRemoved(
                schema_ref=ref,
                old_schema=old_schemas[ref],
            )
        )

    # Schemas that exist in both - compare their contents
    for ref in old_schema_refs & new_schema_refs:
        old_schema = old_schemas[ref]
        new_schema = new_schemas[ref]

        if old_schema != new_schema:
            old_diff, new_diff = _diff_schema(
                cast(AnyJsonDict, old_schema),
                cast(AnyJsonDict, new_schema),
            )
            actions.append(
                SchemaDefinitionModified(
                    schema_ref=ref,
                    old_schema=old_diff,
                    new_schema=new_diff,
                )
            )

    return VersionDelta(actions=actions)


# === Delta Application ===


def _apply_dict_diff(
    target: AnyJsonDict,
    old_diff: AnyJsonDict,
    new_diff: AnyJsonDict,
    forwards: bool,
) -> AnyJsonDict:
    """Apply a diff to a target dict. Returns a new dict with changes applied.

    For forwards (old → new):
    - Keys only in new_diff: add them
    - Keys only in old_diff: remove them
    - Keys in both: update to new value

    For backwards (new → old):
    - Keys only in old_diff: add them
    - Keys only in new_diff: remove them
    - Keys in both: update to old value
    """
    result = dict(target)

    if forwards:
        add_from, remove_from = new_diff, old_diff
    else:
        add_from, remove_from = old_diff, new_diff

    all_keys = set(old_diff.keys()) | set(new_diff.keys())

    for key in all_keys:
        in_old = key in old_diff
        in_new = key in new_diff

        if in_old and in_new:
            # Key was modified - update to target value
            result[key] = add_from[key]
        elif key in add_from:
            # Key was added in target direction
            result[key] = add_from[key]
        elif key in remove_from:
            # Key was removed in target direction
            result.pop(key, None)

    return result


def _apply_properties_diff(
    target_schema: AnyJsonDict,
    old_diff: AnyJsonDict,
    new_diff: AnyJsonDict,
    forwards: bool,
) -> AnyJsonDict:
    """Apply a schema diff, handling 'properties' specially for granular updates."""
    result = dict(target_schema)

    # Handle properties separately
    old_props = cast(dict[str, AnyJson], old_diff.get("properties", {}))
    new_props = cast(dict[str, AnyJson], new_diff.get("properties", {}))

    if old_props or new_props:
        current_props = dict(cast(dict[str, AnyJson], result.get("properties", {})))
        result["properties"] = _apply_dict_diff(
            cast(AnyJsonDict, current_props),
            cast(AnyJsonDict, old_props),
            cast(AnyJsonDict, new_props),
            forwards,
        )

    # Handle other keys normally
    old_other = {k: v for k, v in old_diff.items() if k != "properties"}
    new_other = {k: v for k, v in new_diff.items() if k != "properties"}

    if old_other or new_other:
        result = _apply_dict_diff(result, old_other, new_other, forwards)

    return result


def _apply_openapi_json_diff(
    target: AnyJsonDict,
    old_diff: AnyJsonDict,
    new_diff: AnyJsonDict,
    forwards: bool,
) -> AnyJsonDict:
    """Apply an openapi_json diff, handling 'parameters' and 'responses' specially."""
    result = dict(target)

    # Handle parameters separately (list of param objects keyed by name+location)
    old_params = cast(list[AnyJson], old_diff.get("parameters", []))
    new_params = cast(list[AnyJson], new_diff.get("parameters", []))

    if old_params or new_params:
        current_params = cast(list[AnyJson], result.get("parameters", []))
        current_by_key = {_param_key(p): p for p in current_params}

        old_by_key = {_param_key(p): p for p in old_params}
        new_by_key = {_param_key(p): p for p in new_params}

        updated = _apply_dict_diff(
            cast(AnyJsonDict, current_by_key),
            cast(AnyJsonDict, old_by_key),
            cast(AnyJsonDict, new_by_key),
            forwards,
        )
        result["parameters"] = list(updated.values())

    # Handle responses separately (dict keyed by status code)
    old_responses = cast(dict[str, AnyJson], old_diff.get("responses", {}))
    new_responses = cast(dict[str, AnyJson], new_diff.get("responses", {}))

    if old_responses or new_responses:
        current_responses = dict(cast(dict[str, AnyJson], result.get("responses", {})))
        result["responses"] = _apply_dict_diff(
            cast(AnyJsonDict, current_responses),
            cast(AnyJsonDict, old_responses),
            cast(AnyJsonDict, new_responses),
            forwards,
        )

    # Handle other keys normally
    old_other = {k: v for k, v in old_diff.items() if k not in ("parameters", "responses")}
    new_other = {k: v for k, v in new_diff.items() if k not in ("parameters", "responses")}

    if old_other or new_other:
        result = _apply_dict_diff(result, old_other, new_other, forwards)

    return result


def _apply_params_diff(
    target_op: PathOperation,
    old_params: dict[ParamLocation, dict[str, FieldInfo]],
    new_params: dict[ParamLocation, dict[str, FieldInfo]],
    forwards: bool,
) -> PathOperation:
    """Apply param diffs to an operation, returning a new PathOperation."""
    updates: dict[str, dict[str, FieldInfo]] = {}

    for loc in ("query", "path", "cookie"):
        old_loc = old_params.get(loc, {})
        new_loc = new_params.get(loc, {})

        if not old_loc and not new_loc:
            continue

        current = dict(getattr(target_op, f"{loc}_params"))

        if forwards:
            add_from, remove_from = new_loc, old_loc
        else:
            add_from, remove_from = old_loc, new_loc

        all_names = set(old_loc.keys()) | set(new_loc.keys())

        for name in all_names:
            in_old = name in old_loc
            in_new = name in new_loc

            if in_old and in_new:
                current[name] = add_from[name]
            elif name in add_from:
                current[name] = add_from[name]
            elif name in remove_from:
                current.pop(name, None)

        updates[f"{loc}_params"] = current

    if updates:
        return target_op.model_copy(update=updates)
    return target_op


def _apply_refs_diff(
    current: list[str],
    old_refs: list[str],
    new_refs: list[str],
    forwards: bool,
) -> list[str]:
    """Apply ref list diff."""
    if not old_refs and not new_refs:
        return current
    return new_refs if forwards else old_refs


def _apply_operation_action(
    api_version: ApiVersion,
    action: OperationAction,
    forwards: bool,
) -> ApiVersion:
    """Apply a single operation action to an ApiVersion."""
    path_ops = {k: list(v) for k, v in api_version.path_operations.items()}

    if isinstance(action, OperationAdded):
        if forwards:
            # Add the operation
            if action.path not in path_ops:
                path_ops[action.path] = []
            path_ops[action.path].append(action.new_operation)
        else:
            # Remove the operation (backwards = undo add)
            if action.path in path_ops:
                path_ops[action.path] = [
                    op for op in path_ops[action.path] if op.method != action.method
                ]
                if not path_ops[action.path]:
                    del path_ops[action.path]

    elif isinstance(action, OperationRemoved):
        if forwards:
            # Remove the operation
            if action.path in path_ops:
                path_ops[action.path] = [
                    op for op in path_ops[action.path] if op.method != action.method
                ]
                if not path_ops[action.path]:
                    del path_ops[action.path]
        else:
            # Add the operation back (backwards = undo remove)
            if action.path not in path_ops:
                path_ops[action.path] = []
            path_ops[action.path].append(action.old_operation)

    elif isinstance(action, OperationModified):
        if action.path in path_ops:
            new_ops = []
            for op in path_ops[action.path]:
                if op.method == action.method:
                    # Apply the modifications
                    new_json = _apply_openapi_json_diff(
                        op.openapi_json,
                        action.old_openapi_json,
                        action.new_openapi_json,
                        forwards,
                    )
                    new_op = op.model_copy(update={"openapi_json": new_json})

                    # Apply param diffs
                    new_op = _apply_params_diff(
                        new_op, action.old_params, action.new_params, forwards
                    )

                    # Apply body/response ref diffs
                    new_body = _apply_refs_diff(
                        op.request_body_schema,
                        action.old_body_refs,
                        action.new_body_refs,
                        forwards,
                    )
                    new_response = _apply_refs_diff(
                        op.response_bodies,
                        action.old_response_refs,
                        action.new_response_refs,
                        forwards,
                    )
                    new_op = new_op.model_copy(
                        update={
                            "request_body_schema": new_body,
                            "response_bodies": new_response,
                        }
                    )

                    new_ops.append(new_op)
                else:
                    new_ops.append(op)
            path_ops[action.path] = new_ops

    return api_version.model_copy(update={"path_operations": path_ops})


def _apply_schema_action(
    api_version: ApiVersion,
    action: SchemaAction,
    forwards: bool,
) -> ApiVersion:
    """Apply a single schema action to an ApiVersion."""
    schemas = dict(api_version.schema_definitions)

    if isinstance(action, SchemaDefinitionAdded):
        if forwards:
            schemas[action.schema_ref] = action.new_schema
        else:
            schemas.pop(action.schema_ref, None)

    elif isinstance(action, SchemaDefinitionRemoved):
        if forwards:
            schemas.pop(action.schema_ref, None)
        else:
            schemas[action.schema_ref] = action.old_schema

    elif isinstance(action, SchemaDefinitionModified):
        if action.schema_ref in schemas:
            current = cast(AnyJsonDict, schemas[action.schema_ref])
            schemas[action.schema_ref] = _apply_properties_diff(
                current,
                cast(AnyJsonDict, action.old_schema),
                cast(AnyJsonDict, action.new_schema),
                forwards,
            )

    return api_version.model_copy(update={"schema_definitions": schemas})


def apply_delta_forwards(api_version: ApiVersion, delta: VersionDelta) -> ApiVersion:
    """Apply a delta forwards (old → new) to transform an ApiVersion.

    Use this to rebuild any ApiVersion from deltas only, starting from empty.
    """
    result = api_version
    for action in delta.actions:
        if isinstance(action, (OperationAdded, OperationRemoved, OperationModified)):
            result = _apply_operation_action(result, action, forwards=True)
        else:
            result = _apply_schema_action(result, action, forwards=True)
    return result


def apply_delta_backwards(api_version: ApiVersion, delta: VersionDelta) -> ApiVersion:
    """Apply a delta backwards (new → old) to transform an ApiVersion.

    Use this for runtime migrations to downgrade responses for older API version clients.
    """
    result = api_version
    for action in delta.actions:
        if isinstance(action, (OperationAdded, OperationRemoved, OperationModified)):
            result = _apply_operation_action(result, action, forwards=False)
        else:
            result = _apply_schema_action(result, action, forwards=False)
    return result
