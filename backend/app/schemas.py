"""通用接口契约；模块字段由领域服务持有，不再为每个模块复制一份模型类。"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageResult(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    size: int = 20


class ActionResult(BaseModel):
    ok: bool
    message: str
    entry: dict[str, Any] | None = None


class EntryPayload(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    remark: str | None = None


class ActionPayload(BaseModel):
    action: str
    remark: str | None = None


class GrantPayload(BaseModel):
    cohort_id: int
    recipient_team: str
    owner: str
    scope: str = "仅群组人数（授权实验汇总）"


class RevokePayload(BaseModel):
    revoked_by: str
    reason: str = ""


class EvaluationPayload(BaseModel):
    experiment_name: str
    control_grant_id: int
    treatment_grant_id: int
    analyst: str


class ConfirmGroupPayload(BaseModel):
    group_role: str = Field(pattern="^(control|treatment)$")


class MemberRosterPayload(BaseModel):
    requesting_team: str
