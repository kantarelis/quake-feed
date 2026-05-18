"""Response models for the main API module."""

from __future__ import annotations

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class EnvResponse(BaseModel):
    environment: str
    application_name: str
    version: str
