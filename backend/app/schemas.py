"""Pydantic request/response models. Keeps the API contract explicit and
separate from the ORM layer."""
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
class CreateFindingRequest(BaseModel):
    project_key: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=30000)


class FindingTicketResponse(BaseModel):
    jira_issue_key: str
    jira_issue_url: str
    title: str
    project_key: str
    source: str
    created_at: datetime


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
