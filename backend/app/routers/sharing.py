"""受控共享 API 路由：授权、授权实验汇总、实验评估资格与成员名单保护。

路由层只做参数接收和异常转换，授权边界、撤回级联等业务判断全部在
ControlledSharingService 内完成。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas import (
    ConfirmGroupPayload,
    EvaluationPayload,
    GrantPayload,
    MemberRosterPayload,
    RevokePayload,
)
from app.services.controlled_sharing import ControlledSharingService, SharingError

router = APIRouter(prefix="/api/sharing", tags=["受控共享"])


def _service() -> ControlledSharingService:
    return ControlledSharingService()


def _guard(call):
    """把领域规则异常统一转成 400，路由层不重复写业务判断。"""
    try:
        return call()
    except SharingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/snapshot")
def sharing_snapshot():
    """受控共享整体快照：授权/汇总/评估数量。"""
    return _service().domain_snapshot()


# ── 共享授权与授权实验汇总 ──

@router.get("/grants")
def list_grants():
    return {"items": _service().list_grants(), "total": len(_service().list_grants())}


@router.post("/grants")
def create_grant(payload: GrantPayload):
    return _guard(lambda: _service().create_grant(
        cohort_id=payload.cohort_id,
        recipient_team=payload.recipient_team,
        owner=payload.owner,
        scope=payload.scope,
    ))


@router.post("/grants/{grant_id}/revoke")
def revoke_grant(grant_id: int, payload: RevokePayload):
    return _guard(lambda: _service().revoke_grant(
        grant_id=grant_id,
        revoked_by=payload.revoked_by,
        reason=payload.reason,
    ))


@router.get("/summaries")
def list_summaries(recipient_team: str | None = None):
    items = _service().list_summaries(recipient_team)
    return {"items": items, "total": len(items)}


# ── 实验评估 ──

@router.get("/evaluations")
def list_evaluations():
    items = _service().list_evaluations()
    return {"items": items, "total": len(items)}


@router.post("/evaluations")
def create_evaluation(payload: EvaluationPayload):
    return _guard(lambda: _service().create_evaluation(
        experiment_name=payload.experiment_name,
        control_grant_id=payload.control_grant_id,
        treatment_grant_id=payload.treatment_grant_id,
        analyst=payload.analyst,
    ))


@router.post("/evaluations/{evaluation_id}/confirm")
def confirm_group(evaluation_id: int, payload: ConfirmGroupPayload):
    return _guard(lambda: _service().confirm_group(
        evaluation_id=evaluation_id,
        group_role=payload.group_role,
    ))


@router.get("/evaluations/{evaluation_id}/eligibility")
def evaluation_eligibility(evaluation_id: int):
    return _guard(lambda: _service().eligibility_report(evaluation_id))


# ── 成员名单保护 ──

@router.post("/cohorts/{cohort_id}/member-roster")
def get_member_roster(cohort_id: int, payload: MemberRosterPayload):
    """接收团队尝试获取成员名单时应被拒绝；仅分群团队可读取明细。"""
    return _guard(lambda: _service().get_member_roster(
        cohort_id=cohort_id,
        requesting_team=payload.requesting_team,
    ))
