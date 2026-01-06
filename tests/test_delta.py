from crane.api_version import ApiVersion, FieldInfo, PathOperation
from crane.delta import (
    OperationAdded,
    OperationModified,
    OperationRemoved,
    SchemaDefinitionAdded,
    SchemaDefinitionModified,
    SchemaDefinitionRemoved,
    apply_delta_backwards,
    apply_delta_forwards,
    create_delta,
)


def _make_operation(
    method: str = "get",
    path: str = "/test",
    query_params: dict | None = None,
    path_params: dict | None = None,
    cookie_params: dict | None = None,
    request_body_schema: list | None = None,
    response_bodies: list | None = None,
    operation_id: str = "test_op",
    openapi_json: dict | None = None,
) -> PathOperation:
    return PathOperation(
        method=method,  # type: ignore
        path=path,
        query_params=query_params or {},
        path_params=path_params or {},
        cookie_params=cookie_params or {},
        request_body_schema=request_body_schema or [],
        response_bodies=response_bodies or [],
        operation_id=operation_id,
        openapi_json=openapi_json or {"operationId": operation_id},
    )


def _make_api_version(
    operations: list[PathOperation] | None = None,
    schemas: dict | None = None,
) -> ApiVersion:
    path_ops: dict[str, list[PathOperation]] = {}
    for op in operations or []:
        if op.path not in path_ops:
            path_ops[op.path] = []
        path_ops[op.path].append(op)
    return ApiVersion(
        path_operations=path_ops,
        schema_definitions=schemas or {},
    )


class TestCreateDeltaEmpty:
    def test_identical_versions_produce_empty_delta(self):
        op = _make_operation()
        v1 = _make_api_version([op])
        v2 = _make_api_version([op])

        delta = create_delta(v1, v2)

        assert delta.actions == []

    def test_empty_versions_produce_empty_delta(self):
        v1 = _make_api_version()
        v2 = _make_api_version()

        delta = create_delta(v1, v2)

        assert delta.actions == []


class TestOperationAdded:
    def test_new_operation_creates_operation_added(self):
        v1 = _make_api_version()
        op = _make_operation(path="/users", method="get", operation_id="get_users")
        v2 = _make_api_version([op])

        delta = create_delta(v1, v2)

        assert len(delta.actions) == 1
        action = delta.actions[0]
        assert isinstance(action, OperationAdded)
        assert action.path == "/users"
        assert action.method == "get"
        assert action.new_operation == op


class TestOperationRemoved:
    def test_removed_operation_creates_operation_removed(self):
        op = _make_operation(path="/users", method="delete", operation_id="delete_user")
        v1 = _make_api_version([op])
        v2 = _make_api_version()

        delta = create_delta(v1, v2)

        assert len(delta.actions) == 1
        action = delta.actions[0]
        assert isinstance(action, OperationRemoved)
        assert action.path == "/users"
        assert action.method == "delete"
        assert action.old_operation == op


class TestOperationModified:
    def test_changed_openapi_json_creates_operation_modified(self):
        op1 = _make_operation(openapi_json={"operationId": "test", "summary": "Old summary"})
        op2 = _make_operation(openapi_json={"operationId": "test", "summary": "New summary"})
        v1 = _make_api_version([op1])
        v2 = _make_api_version([op2])

        delta = create_delta(v1, v2)

        assert len(delta.actions) == 1
        action = delta.actions[0]
        assert isinstance(action, OperationModified)
        assert action.old_openapi_json == {"summary": "Old summary"}
        assert action.new_openapi_json == {"summary": "New summary"}

    def test_changed_query_params_creates_operation_modified(self):
        field1 = FieldInfo(source=None, json_schema_specification={"type": "string"}, required=True)
        field2 = FieldInfo(
            source=None, json_schema_specification={"type": "integer"}, required=True
        )

        op1 = _make_operation(query_params={"name": field1})
        op2 = _make_operation(query_params={"name": field2})
        v1 = _make_api_version([op1])
        v2 = _make_api_version([op2])

        delta = create_delta(v1, v2)

        assert len(delta.actions) == 1
        action = delta.actions[0]
        assert isinstance(action, OperationModified)
        assert "query" in action.old_params
        assert action.old_params["query"]["name"] == field1
        assert action.new_params["query"]["name"] == field2

    def test_added_query_param_in_modified(self):
        field = FieldInfo(source=None, json_schema_specification={"type": "string"}, required=True)

        op1 = _make_operation(query_params={})
        op2 = _make_operation(query_params={"name": field})
        v1 = _make_api_version([op1])
        v2 = _make_api_version([op2])

        delta = create_delta(v1, v2)

        assert len(delta.actions) == 1
        action = delta.actions[0]
        assert isinstance(action, OperationModified)
        assert "query" not in action.old_params
        assert action.new_params["query"]["name"] == field

    def test_changed_response_refs(self):
        op1 = _make_operation(response_bodies=["#/components/schemas/OldResponse"])
        op2 = _make_operation(response_bodies=["#/components/schemas/NewResponse"])
        v1 = _make_api_version([op1])
        v2 = _make_api_version([op2])

        delta = create_delta(v1, v2)

        assert len(delta.actions) == 1
        action = delta.actions[0]
        assert isinstance(action, OperationModified)
        assert action.old_response_refs == ["#/components/schemas/OldResponse"]
        assert action.new_response_refs == ["#/components/schemas/NewResponse"]


class TestSchemaDefinitionAdded:
    def test_new_schema_creates_schema_added(self):
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        v1 = _make_api_version(schemas={})
        v2 = _make_api_version(schemas={"#/components/schemas/User": schema})

        delta = create_delta(v1, v2)

        assert len(delta.actions) == 1
        action = delta.actions[0]
        assert isinstance(action, SchemaDefinitionAdded)
        assert action.schema_ref == "#/components/schemas/User"
        assert action.new_schema == schema


class TestSchemaDefinitionRemoved:
    def test_removed_schema_creates_schema_removed(self):
        schema = {"type": "object", "properties": {"id": {"type": "integer"}}}
        v1 = _make_api_version(schemas={"#/components/schemas/User": schema})
        v2 = _make_api_version(schemas={})

        delta = create_delta(v1, v2)

        assert len(delta.actions) == 1
        action = delta.actions[0]
        assert isinstance(action, SchemaDefinitionRemoved)
        assert action.schema_ref == "#/components/schemas/User"
        assert action.old_schema == schema


class TestSchemaDefinitionModified:
    def test_changed_property_creates_schema_modified(self):
        old_schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        }
        new_schema = {
            "type": "object",
            "properties": {"name": {"type": "string", "maxLength": 100}},
        }
        v1 = _make_api_version(schemas={"#/components/schemas/User": old_schema})
        v2 = _make_api_version(schemas={"#/components/schemas/User": new_schema})

        delta = create_delta(v1, v2)

        assert len(delta.actions) == 1
        action = delta.actions[0]
        assert isinstance(action, SchemaDefinitionModified)
        assert action.schema_ref == "#/components/schemas/User"
        # Only changed properties should be in the diff
        assert action.old_schema == {"properties": {"name": {"type": "string"}}}
        assert action.new_schema == {"properties": {"name": {"type": "string", "maxLength": 100}}}

    def test_added_property_in_modified(self):
        old_schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        }
        new_schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "email": {"type": "string"},
            },
        }
        v1 = _make_api_version(schemas={"#/components/schemas/User": old_schema})
        v2 = _make_api_version(schemas={"#/components/schemas/User": new_schema})

        delta = create_delta(v1, v2)

        assert len(delta.actions) == 1
        action = delta.actions[0]
        assert isinstance(action, SchemaDefinitionModified)
        # Old should not have email, new should
        assert "email" not in action.old_schema.get("properties", {})
        assert action.new_schema["properties"]["email"] == {"type": "string"}

    def test_changed_required_fields(self):
        old_schema = {"type": "object", "required": ["name"]}
        new_schema = {"type": "object", "required": ["name", "email"]}
        v1 = _make_api_version(schemas={"#/components/schemas/User": old_schema})
        v2 = _make_api_version(schemas={"#/components/schemas/User": new_schema})

        delta = create_delta(v1, v2)

        assert len(delta.actions) == 1
        action = delta.actions[0]
        assert isinstance(action, SchemaDefinitionModified)
        assert action.old_schema == {"required": ["name"]}
        assert action.new_schema == {"required": ["name", "email"]}

    def test_none_values_preserved_in_diff(self):
        """Ensure None/null values are stored in diffs, not dropped."""
        old_schema = {"type": "object", "description": "A user"}
        new_schema = {"type": "object", "description": None}  # Explicitly set to None
        v1 = _make_api_version(schemas={"#/components/schemas/User": old_schema})
        v2 = _make_api_version(schemas={"#/components/schemas/User": new_schema})

        delta = create_delta(v1, v2)

        assert len(delta.actions) == 1
        action = delta.actions[0]
        assert isinstance(action, SchemaDefinitionModified)
        assert action.old_schema == {"description": "A user"}
        assert action.new_schema == {"description": None}  # None should be preserved

    def test_none_to_value_change(self):
        """Ensure change from None to a value is captured."""
        old_schema = {"type": "object", "default": None}
        new_schema = {"type": "object", "default": "foo"}
        v1 = _make_api_version(schemas={"#/components/schemas/User": old_schema})
        v2 = _make_api_version(schemas={"#/components/schemas/User": new_schema})

        delta = create_delta(v1, v2)

        assert len(delta.actions) == 1
        action = delta.actions[0]
        assert isinstance(action, SchemaDefinitionModified)
        assert action.old_schema == {"default": None}  # None should be preserved
        assert action.new_schema == {"default": "foo"}


class TestForwardsDerivation:
    """Tests for rebuilding ApiVersion from deltas only."""

    def test_first_delta_from_empty_captures_all_operations(self):
        """First delta from empty should have all ops as OperationAdded."""
        op1 = _make_operation(path="/users", method="get", operation_id="list_users")
        op2 = _make_operation(path="/users", method="post", operation_id="create_user")
        v1 = _make_api_version([op1, op2])

        delta = create_delta(_make_api_version(), v1)

        # Should have 2 OperationAdded actions
        added_actions = [a for a in delta.actions if isinstance(a, OperationAdded)]
        assert len(added_actions) == 2

    def test_first_delta_from_empty_captures_all_schemas(self):
        """First delta from empty should have all schemas as SchemaDefinitionAdded."""
        schemas = {
            "#/components/schemas/User": {"type": "object"},
            "#/components/schemas/Post": {"type": "object"},
        }
        v1 = _make_api_version(schemas=schemas)

        delta = create_delta(_make_api_version(), v1)

        added_actions = [a for a in delta.actions if isinstance(a, SchemaDefinitionAdded)]
        assert len(added_actions) == 2


class TestApplyDeltaForwards:
    """Tests for applying deltas forwards (old -> new)."""

    def test_apply_operation_added(self):
        """Applying OperationAdded forwards should add the operation."""
        op = _make_operation(path="/users", method="get", operation_id="list_users")
        v1 = _make_api_version()
        v2 = _make_api_version([op])

        delta = create_delta(v1, v2)
        result = apply_delta_forwards(v1, delta)

        assert "/users" in result.path_operations
        assert len(result.path_operations["/users"]) == 1
        assert result.path_operations["/users"][0].operation_id == "list_users"

    def test_apply_operation_removed(self):
        """Applying OperationRemoved forwards should remove the operation."""
        op = _make_operation(path="/users", method="delete", operation_id="delete_user")
        v1 = _make_api_version([op])
        v2 = _make_api_version()

        delta = create_delta(v1, v2)
        result = apply_delta_forwards(v1, delta)

        assert "/users" not in result.path_operations

    def test_apply_schema_property_added(self):
        """Applying schema with added property forwards should add the property."""
        old_schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        }
        new_schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "email": {"type": "string"},
            },
        }
        v1 = _make_api_version(schemas={"#/components/schemas/User": old_schema})
        v2 = _make_api_version(schemas={"#/components/schemas/User": new_schema})

        delta = create_delta(v1, v2)
        result = apply_delta_forwards(v1, delta)

        user_schema = result.schema_definitions["#/components/schemas/User"]
        assert "email" in user_schema["properties"]
        assert user_schema["properties"]["email"] == {"type": "string"}
        assert user_schema["properties"]["name"] == {"type": "string"}

    def test_apply_schema_property_removed(self):
        """Applying schema with removed property forwards should remove the property."""
        old_schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "email": {"type": "string"},
            },
        }
        new_schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        }
        v1 = _make_api_version(schemas={"#/components/schemas/User": old_schema})
        v2 = _make_api_version(schemas={"#/components/schemas/User": new_schema})

        delta = create_delta(v1, v2)
        result = apply_delta_forwards(v1, delta)

        user_schema = result.schema_definitions["#/components/schemas/User"]
        assert "email" not in user_schema["properties"]
        assert user_schema["properties"]["name"] == {"type": "string"}

    def test_apply_query_param_added(self):
        """Applying operation with added query param forwards should add the param."""
        field = FieldInfo(source=None, json_schema_specification={"type": "string"}, required=True)

        op1 = _make_operation(query_params={})
        op2 = _make_operation(query_params={"name": field})
        v1 = _make_api_version([op1])
        v2 = _make_api_version([op2])

        delta = create_delta(v1, v2)
        result = apply_delta_forwards(v1, delta)

        result_op = result.path_operations["/test"][0]
        assert "name" in result_op.query_params
        assert result_op.query_params["name"] == field

    def test_apply_query_param_removed(self):
        """Applying operation with removed query param forwards should remove the param."""
        field = FieldInfo(source=None, json_schema_specification={"type": "string"}, required=True)

        op1 = _make_operation(query_params={"name": field})
        op2 = _make_operation(query_params={})
        v1 = _make_api_version([op1])
        v2 = _make_api_version([op2])

        delta = create_delta(v1, v2)
        result = apply_delta_forwards(v1, delta)

        result_op = result.path_operations["/test"][0]
        assert "name" not in result_op.query_params

    def test_roundtrip_forwards(self):
        """Applying delta forwards should produce the new version."""
        op1 = _make_operation(path="/users", method="get", operation_id="list")
        op2 = _make_operation(path="/users", method="post", operation_id="create")
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}

        v1 = _make_api_version([op1], schemas={"#/components/schemas/User": schema})
        v2 = _make_api_version(
            [op2],
            schemas={
                "#/components/schemas/User": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}, "email": {"type": "string"}},
                }
            },
        )

        delta = create_delta(v1, v2)
        result = apply_delta_forwards(v1, delta)

        # Operation changes
        assert "/users" in result.path_operations
        ops = result.path_operations["/users"]
        op_ids = {op.operation_id for op in ops}
        assert "create" in op_ids
        assert "list" not in op_ids

        # Schema changes
        user_schema = result.schema_definitions["#/components/schemas/User"]
        assert "email" in user_schema["properties"]


class TestApplyDeltaBackwards:
    """Tests for applying deltas backwards (new -> old)."""

    def test_apply_operation_added_backwards(self):
        """Applying OperationAdded backwards should remove the operation."""
        op = _make_operation(path="/users", method="get", operation_id="list_users")
        v1 = _make_api_version()
        v2 = _make_api_version([op])

        delta = create_delta(v1, v2)
        result = apply_delta_backwards(v2, delta)

        assert "/users" not in result.path_operations

    def test_apply_operation_removed_backwards(self):
        """Applying OperationRemoved backwards should add the operation back."""
        op = _make_operation(path="/users", method="delete", operation_id="delete_user")
        v1 = _make_api_version([op])
        v2 = _make_api_version()

        delta = create_delta(v1, v2)
        result = apply_delta_backwards(v2, delta)

        assert "/users" in result.path_operations
        assert result.path_operations["/users"][0].operation_id == "delete_user"

    def test_apply_schema_property_added_backwards(self):
        """Applying schema with added property backwards should remove the property."""
        old_schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        }
        new_schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "email": {"type": "string"},
            },
        }
        v1 = _make_api_version(schemas={"#/components/schemas/User": old_schema})
        v2 = _make_api_version(schemas={"#/components/schemas/User": new_schema})

        delta = create_delta(v1, v2)
        result = apply_delta_backwards(v2, delta)

        user_schema = result.schema_definitions["#/components/schemas/User"]
        assert "email" not in user_schema["properties"]
        assert user_schema["properties"]["name"] == {"type": "string"}

    def test_apply_schema_property_removed_backwards(self):
        """Applying schema with removed property backwards should add the property back."""
        old_schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "email": {"type": "string"},
            },
        }
        new_schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        }
        v1 = _make_api_version(schemas={"#/components/schemas/User": old_schema})
        v2 = _make_api_version(schemas={"#/components/schemas/User": new_schema})

        delta = create_delta(v1, v2)
        result = apply_delta_backwards(v2, delta)

        user_schema = result.schema_definitions["#/components/schemas/User"]
        assert "email" in user_schema["properties"]
        assert user_schema["properties"]["email"] == {"type": "string"}

    def test_roundtrip_backwards(self):
        """Applying delta backwards should produce the old version."""
        op1 = _make_operation(path="/users", method="get", operation_id="list")
        op2 = _make_operation(path="/users", method="post", operation_id="create")
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}

        v1 = _make_api_version([op1], schemas={"#/components/schemas/User": schema})
        v2 = _make_api_version(
            [op2],
            schemas={
                "#/components/schemas/User": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}, "email": {"type": "string"}},
                }
            },
        )

        delta = create_delta(v1, v2)
        result = apply_delta_backwards(v2, delta)

        # Operation changes - should have "list" back, not "create"
        assert "/users" in result.path_operations
        ops = result.path_operations["/users"]
        op_ids = {op.operation_id for op in ops}
        assert "list" in op_ids
        assert "create" not in op_ids

        # Schema changes - email should be removed
        user_schema = result.schema_definitions["#/components/schemas/User"]
        assert "email" not in user_schema["properties"]


class TestDeltaRebuildFromEmpty:
    """Tests for rebuilding ApiVersion from deltas only, starting from empty."""

    def test_rebuild_single_version_from_empty(self):
        """Can rebuild v1 by applying first delta to empty."""
        op = _make_operation(path="/users", method="get", operation_id="list_users")
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        v1 = _make_api_version([op], schemas={"#/components/schemas/User": schema})

        empty = _make_api_version()
        delta = create_delta(empty, v1)
        result = apply_delta_forwards(empty, delta)

        assert "/users" in result.path_operations
        assert "#/components/schemas/User" in result.schema_definitions

    def test_rebuild_multiple_versions_sequentially(self):
        """Can rebuild v2 by applying deltas sequentially from empty."""
        # v1: has GET /users
        op1 = _make_operation(path="/users", method="get", operation_id="list_users")
        v1 = _make_api_version([op1])

        # v2: adds POST /users, removes GET /users
        op2 = _make_operation(path="/users", method="post", operation_id="create_user")
        v2 = _make_api_version([op2])

        empty = _make_api_version()
        delta1 = create_delta(empty, v1)
        delta2 = create_delta(v1, v2)

        # Rebuild v2 from empty by applying both deltas
        result = apply_delta_forwards(empty, delta1)
        result = apply_delta_forwards(result, delta2)

        ops = result.path_operations["/users"]
        op_ids = {op.operation_id for op in ops}
        assert "create_user" in op_ids
        assert "list_users" not in op_ids
