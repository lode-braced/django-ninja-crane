import pytest

from crane.api_version import ApiVersion, create_api_version
from test_server.urls import api as test_api


@pytest.fixture
def api_version() -> ApiVersion:
    return create_api_version(test_api)


class TestCreateApiVersion:
    def test_returns_api_version(self, api_version):
        assert isinstance(api_version, ApiVersion)

    def test_has_persons_route(self, api_version):
        assert "/persons" in api_version.path_operations

    def test_list_persons_operation(self, api_version):
        ops = api_version.path_operations["/persons"]
        list_op = next((op for op in ops if op.operation_id == "test_app_api_list_persons"), None)

        assert list_op is not None
        assert list_op.method == "get"
        assert list_op.path == "/persons/"
        assert list_op.query_params == {}
        assert list_op.path_params == {}
        # Response should reference PersonOut in an array
        assert 200 in list_op.response_bodies

    def test_get_person_operation(self, api_version):
        ops = api_version.path_operations["/persons"]
        get_op = next((op for op in ops if op.operation_id == "test_app_api_get_person"), None)

        assert get_op is not None
        assert get_op.method == "get"
        assert get_op.path == "/persons/{person_id}"
        # Should have person_id path param
        assert "person_id" in get_op.path_params
        assert get_op.path_params["person_id"].required is True

    def test_create_person_operation(self, api_version):
        ops = api_version.path_operations["/persons"]
        create_op = next(
            (op for op in ops if op.operation_id == "test_app_api_create_person"), None
        )

        assert create_op is not None
        assert create_op.method == "post"
        assert create_op.path == "/persons/"
        # Should have request body referencing PersonIn
        assert create_op.request_body_schema is not None
        assert any(
            "PersonIn" in ref for ref in create_op.request_body_schema if isinstance(ref, str)
        )

    def test_update_person_operation(self, api_version):
        ops = api_version.path_operations["/persons"]
        update_op = next(
            (op for op in ops if op.operation_id == "test_app_api_update_person"), None
        )

        assert update_op is not None
        assert update_op.method == "put"
        assert update_op.path == "/persons/{person_id}"
        assert "person_id" in update_op.path_params
        # Should have request body referencing PersonIn
        assert update_op.request_body_schema is not None

    def test_delete_person_operation(self, api_version):
        ops = api_version.path_operations["/persons"]
        delete_op = next(
            (op for op in ops if op.operation_id == "test_app_api_delete_person"), None
        )

        assert delete_op is not None
        assert delete_op.method == "delete"
        assert delete_op.path == "/persons/{person_id}"
        assert "person_id" in delete_op.path_params

    def test_search_model_operation_query_params(self, api_version):
        """Query params from a Schema model should be flattened with source tracking."""
        ops = api_version.path_operations["/persons"]
        search_op = next(
            (op for op in ops if op.operation_id == "test_app_api_search_persons_model"), None
        )

        assert search_op is not None
        assert search_op.method == "get"
        assert search_op.path == "/persons/search/model"
        # PersonFilter has: name, email, address (nested PersonAddress with street, city)
        # These should be flattened into query params
        assert "name" in search_op.query_params
        assert "email" in search_op.query_params
        # Nested fields from PersonAddress
        assert "address" in search_op.query_params
        # Check source tracking - fields should reference their source schema
        name_field = search_op.query_params["name"]
        assert name_field.source is not None
        assert "PersonFilter" in name_field.source

    def test_search_primitive_operation_query_params(self, api_version):
        """Primitive query params should not have a source schema."""
        ops = api_version.path_operations["/persons"]
        search_op = next(
            (op for op in ops if op.operation_id == "test_app_api_search_persons_primitive"), None
        )

        assert search_op is not None
        assert search_op.method == "get"
        assert search_op.path == "/persons/search/primitive"
        # Primitive params: name (optional), limit (default 10)
        assert "name" in search_op.query_params
        assert "limit" in search_op.query_params
        # Primitive params should have no source
        assert search_op.query_params["name"].source is None
        assert search_op.query_params["limit"].source is None
        # name is optional, limit has default
        assert search_op.query_params["name"].required is False
        assert search_op.query_params["limit"].required is False

    def test_upload_multipart_operation(self, api_version):
        """Multipart endpoint with body schema and file."""
        ops = api_version.path_operations["/persons"]
        upload_op = next((op for op in ops if op.operation_id == "test_app_api_upload_file"), None)

        assert upload_op is not None
        assert upload_op.method == "post"
        assert upload_op.path == "/persons/upload"
        # Should have request body with union type PersonIn | PersonOut
        assert upload_op.request_body_schema is not None
        refs = [ref for ref in upload_op.request_body_schema if isinstance(ref, str)]
        assert any("PersonIn" in ref for ref in refs)
        assert any("PersonOut" in ref for ref in refs)

    def test_upload_single_file_operation(self, api_version):
        """File-only upload endpoint."""
        ops = api_version.path_operations["/persons"]
        upload_op = next(
            (op for op in ops if op.operation_id == "test_app_api_upload_single"), None
        )

        assert upload_op is not None
        assert upload_op.method == "post"
        assert upload_op.path == "/persons/upload_file"


class TestSchemaDefinitions:
    def test_schema_definitions_contains_person_schemas(self, api_version):
        """Schema definitions should include PersonIn, PersonOut, PersonFilter, PersonAddress."""
        schema_names = list(api_version.schema_definitions.keys())

        assert any("PersonIn" in name for name in schema_names)
        assert any("PersonOut" in name for name in schema_names)
        assert any("PersonFilter" in name for name in schema_names)
        assert any("PersonAddress" in name for name in schema_names)

    def test_person_in_schema_fields(self, api_version):
        """PersonIn should have name and email fields."""
        person_in_key = next(k for k in api_version.schema_definitions if "PersonIn" in k)
        schema = api_version.schema_definitions[person_in_key]

        assert "properties" in schema
        assert "name" in schema["properties"]
        assert "email" in schema["properties"]
        assert schema["properties"]["name"]["type"] == "string"
        assert schema["properties"]["email"]["type"] == "string"

    def test_person_out_schema_fields(self, api_version):
        """PersonOut should have id, name, email, created_at fields."""
        person_out_key = next(k for k in api_version.schema_definitions if "PersonOut" in k)
        schema = api_version.schema_definitions[person_out_key]

        assert "properties" in schema
        assert "id" in schema["properties"]
        assert "name" in schema["properties"]
        assert "email" in schema["properties"]
        assert "created_at" in schema["properties"]
