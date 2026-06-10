"""Pydantic request/response models. Keeps the API contract explicit and
separate from the ORM layer."""
import re
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


# ---- Auth ----
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserResponse(BaseModel):
    id: str
    email: EmailStr
    jira_connected: bool


# ---- Jira connection ----
class JiraConnectRequest(BaseModel):
    site_url: str = Field(examples=["acme.atlassian.net"])
    jira_email: EmailStr
    api_token: str = Field(min_length=1)

    @field_validator("site_url")
    @classmethod
    def normalize_site(cls, v: str) -> str:
        v = v.strip().removeprefix("https://").removeprefix("http://").rstrip("/")
        if not v:
            raise ValueError("site_url is required")
        return v


class JiraConnectionResponse(BaseModel):
    site_url: str
    jira_email: EmailStr
    connected_at: datetime
    last_verified_at: datetime | None


class JiraProject(BaseModel):
    key: str
    name: str


# ---- Findings ----
# Jira priority names (standard scheme). Severity of an NHI finding maps here.
JIRA_PRIORITIES = ["Highest", "High", "Medium", "Low", "Lowest"]


class CreateFindingRequest(BaseModel):
    project_key: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=30000)

    # User-supplied labels (the 'identityhub' marker is added server-side).
    labels: list[str] = Field(default_factory=list, max_length=20)

    # Best-effort: only applied if the target project exposes a priority field.
    priority: str | None = None

    # NHI-specific context. No native Jira fields map cleanly across projects,
    # so these are rendered into a structured description template instead.
    # last_activity is an ISO date string (YYYY-MM-DD) from a date picker.
    resource: str | None = Field(default=None, max_length=255)
    category: str | None = Field(default=None, max_length=100)
    environment: str | None = Field(default=None, max_length=100)
    last_activity: str | None = Field(default=None, max_length=100)

    @field_validator("labels")
    @classmethod
    def clean_labels(cls, labels: list[str]) -> list[str]:
        # Jira labels cannot contain spaces; normalize to hyphens and drop blanks.
        cleaned = []
        for raw in labels:
            label = re.sub(r"\s+", "-", raw.strip())
            if label:
                cleaned.append(label)
        return cleaned

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        if v not in JIRA_PRIORITIES:
            raise ValueError(f"priority must be one of {JIRA_PRIORITIES}")
        return v


class FindingTicketResponse(BaseModel):
    jira_issue_key: str
    jira_issue_url: str
    title: str
    project_key: str
    labels: list[str] = Field(default_factory=list)
    created_at: datetime


class FindingDetailResponse(BaseModel):
    """Full detail for the in-app finding page, reconstructed from Jira."""

    jira_issue_key: str
    jira_issue_url: str
    title: str
    description: str = ""
    labels: list[str] = Field(default_factory=list)
    priority: str | None = None
    status: str | None = None
    assignee: str | None = None
    created_at: datetime | None = None
    # NHI context (populated from mapped custom fields when configured)
    resource: str | None = None
    category: str | None = None
    environment: str | None = None
    last_activity: str | None = None


# ---- API keys ----
class CreateApiKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ApiKeyResponse(BaseModel):
    id: str
    name: str
    key_prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class CreateApiKeyResponse(ApiKeyResponse):
    # Plaintext key, returned only once at creation time.
    api_key: str


# ---- Errors ----
class ErrorResponse(BaseModel):
    detail: str
