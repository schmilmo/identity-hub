"""Unit tests for the NHI-context → Jira custom-field mapping (NHI_FIELD_MAP).

These exercise the pure mapping/formatting logic directly, independent of the
HTTP layer or a configured Jira."""
from app.schemas import CreateFindingRequest
from app.services.findings_service import (
    _compose_description,
    build_custom_fields,
)


def _req(**kw):
    base = {"project_key": "SAM1", "title": "t"}
    base.update(kw)
    return CreateFindingRequest(**base)


def test_no_mapping_everything_in_description():
    req = _req(resource="svc-x", last_activity="2026-03-01")
    extra, mapped = build_custom_fields(req, {})
    assert extra == {} and mapped == set()
    desc = _compose_description(req, exclude=mapped)
    assert "Affected resource: svc-x" in desc
    assert "Last activity: 2026-03-01" in desc


def test_mapped_fields_become_custom_fields_and_leave_description():
    field_map = {
        "resource": {"id": "customfield_10042", "type": "text"},
        "last_activity": {"id": "customfield_10045", "type": "date"},
        "category": {"id": "customfield_10043", "type": "option"},
    }
    req = _req(
        description="Base.",
        resource="svc-x",
        category="Stale service account",
        environment="aws-prod",  # NOT mapped → stays in description
        last_activity="2026-03-01",
    )
    extra, mapped = build_custom_fields(req, field_map)

    assert extra["customfield_10042"] == "svc-x"  # text → scalar
    assert extra["customfield_10045"] == "2026-03-01"  # date → scalar
    assert extra["customfield_10043"] == {"value": "Stale service account"}  # option
    assert mapped == {"resource", "last_activity", "category"}

    desc = _compose_description(req, exclude=mapped)
    # Mapped fields are NOT duplicated into the description...
    assert "Affected resource" not in desc
    assert "Last activity" not in desc
    # ...but the unmapped one still is.
    assert "Environment: aws-prod" in desc


def test_array_type_wraps_values():
    field_map = {"environment": {"id": "customfield_10044", "type": "array"}}
    extra, _ = build_custom_fields(_req(environment="aws-prod"), field_map)
    assert extra["customfield_10044"] == [{"value": "aws-prod"}]


def test_mapping_without_value_is_skipped():
    field_map = {"resource": {"id": "customfield_10042", "type": "text"}}
    extra, mapped = build_custom_fields(_req(), field_map)  # no resource value
    assert extra == {} and mapped == set()
