"""受控共享领域服务：把用户分群的成员数据以授权实验汇总的形式交给实验团队。

安全边界
--------
- 分群团队保存完整成员明细（cohort snapshot），接收团队经本服务只能拿到
  聚合后的「授权实验汇总」，其中仅包含群组人数，不含任何个人资料或成员明细。
- 共享授权可由分群负责人撤回；撤回后授权与汇总立即失效，进行中的实验评估
  级联失去资格，新的试验不得复用过期权限。
- 一次对照的对照组与实验组必须在同一个有效授权边界内确认，缺一不可。

跨模块数据流: user_cohort（成员明细，分群团队持有）
              -> controlled_sharing（授权 + 授权实验汇总）
              -> experiment_group（实验评估只消费汇总人数）
"""
from __future__ import annotations

import time
from typing import Any

from app.store import store


class SharingError(Exception):
    """受控共享业务规则被违反时抛出，由路由层转成 400 响应。"""


class ControlledSharingService:
    """受控共享：授权、授权实验汇总、实验评估与撤回边界的统一领域入口。"""

    GRANT_ACTIVE = "有效"
    GRANT_REVOKED = "已撤回"
    SUMMARY_ACTIVE = "有效"
    SUMMARY_INVALID = "已失效"

    EVAL_PENDING = "待确认"
    EVAL_READY = "可生成"
    EVAL_BLOCKED = "失去资格"

    # ── 内部工具 ──

    @staticmethod
    def _now() -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S")

    def _require_cohort(self, cohort_id: int) -> dict[str, Any]:
        cohort = store.find("user_cohort", cohort_id)
        if cohort is None:
            raise SharingError(f"用户分群 {cohort_id} 不存在，无法发起受控共享")
        return cohort

    def _cohort_headcount(self, cohort_id: int) -> int:
        """群组人数只由成员明细聚合得到；尚无成员快照时回退到分群登记人数。"""
        members = store.get_cohort_snapshot(cohort_id)
        if members:
            return len(members)
        cohort = store.find("user_cohort", cohort_id)
        try:
            return int((cohort or {}).get("群组大小", 0))
        except (ValueError, TypeError):
            return 0

    def _require_grant(self, grant_id: int) -> dict[str, Any]:
        grant = store.find_sharing_grant(grant_id)
        if grant is None:
            raise SharingError(f"共享授权 {grant_id} 不存在")
        return grant

    def _require_active_grant(self, grant_id: int) -> dict[str, Any]:
        grant = self._require_grant(grant_id)
        if grant.get("status") != self.GRANT_ACTIVE:
            raise SharingError(
                f"共享授权 {grant_id} 当前状态为「{grant.get('status')}」，过期权限不得继续使用"
            )
        return grant

    def _require_evaluation(self, evaluation_id: int) -> dict[str, Any]:
        evaluation = store.find_evaluation(evaluation_id)
        if evaluation is None:
            raise SharingError(f"实验评估 {evaluation_id} 不存在")
        return evaluation

    def _group_slot(self, evaluation: dict[str, Any], group_role: str) -> dict[str, Any]:
        slot = next(
            (item for item in evaluation["groups"] if item["group_role"] == group_role),
            None,
        )
        if slot is None:
            raise SharingError(f"评估不存在 {group_role} 分组，分组角色只能是 control 或 treatment")
        return slot

    # ── 授权与授权实验汇总 ──

    def create_grant(
        self,
        cohort_id: int,
        recipient_team: str,
        owner: str,
        scope: str = "仅群组人数（授权实验汇总）",
    ) -> dict[str, Any]:
        """分群团队把指定分群受控共享给实验团队，并同步生成授权实验汇总。

        汇总只保存聚合人数，成员明细始终留在分群团队的 cohort snapshot 中。
        """
        cohort = self._require_cohort(cohort_id)
        recipient_team = (recipient_team or "").strip()
        owner = (owner or "").strip()
        if not recipient_team:
            raise SharingError("接收团队不能为空")
        if not owner:
            raise SharingError("分群负责人不能为空")
        existing = store.find_active_grant(cohort_id, recipient_team)
        if existing is not None:
            raise SharingError(
                f"分群「{cohort.get('分群名称')}」对团队「{recipient_team}」已有有效授权"
                f"（授权 {existing['id']}），不得重复授权"
            )

        headcount = self._cohort_headcount(cohort_id)
        grant = store.append_sharing_grant({
            "cohort_id": cohort_id,
            "cohort_name": cohort.get("分群名称"),
            "owner_team": "分群团队",
            "owner": owner,
            "recipient_team": recipient_team,
            "scope": scope,
            "status": self.GRANT_ACTIVE,
            "granted_at": self._now(),
            "revoked_at": None,
            "revoked_by": None,
            "revoke_reason": None,
        })
        summary = store.append_summary({
            "grant_id": grant["id"],
            "cohort_id": cohort_id,
            "cohort_name": cohort.get("分群名称"),
            "recipient_team": recipient_team,
            "headcount": headcount,
            "data_scope": "仅群组人数，不含成员明细与个人资料",
            "status": self.SUMMARY_ACTIVE,
            "generated_at": self._now(),
            "invalidated_at": None,
        })
        grant["summary_id"] = summary["id"]
        return {"grant": grant, "summary": summary}

    def revoke_grant(self, grant_id: int, revoked_by: str, reason: str = "") -> dict[str, Any]:
        """分群负责人撤回共享权限。

        撤回后：授权标记为已撤回、授权实验汇总失效；引用该授权且尚未完成确认的
        实验评估级联标记为失去资格。已经可生成的评估保留其确认时的汇总快照留档。
        """
        grant = self._require_grant(grant_id)
        if grant.get("status") == self.GRANT_REVOKED:
            raise SharingError(f"共享授权 {grant_id} 已撤回，无需重复操作")
        grant["status"] = self.GRANT_REVOKED
        grant["revoked_at"] = self._now()
        grant["revoked_by"] = (revoked_by or "").strip() or "分群负责人"
        grant["revoke_reason"] = reason.strip()

        summary = store.find_summary(int(grant.get("summary_id", 0)))
        if summary is not None:
            summary["status"] = self.SUMMARY_INVALID
            summary["invalidated_at"] = grant["revoked_at"]

        affected_evaluations: list[dict[str, Any]] = []
        for evaluation in store.experiment_evaluations():
            touched = any(
                int(item.get("grant_id", 0)) == grant_id for item in evaluation["groups"]
            )
            if not touched:
                continue
            before_status = evaluation["status"]
            self._recompute_evaluation(evaluation)
            if evaluation["status"] != before_status:
                evaluation.setdefault("events", []).append({
                    "time": grant["revoked_at"],
                    "event": "授权撤回级联",
                    "detail": f"授权 {grant_id} 被{grant['revoked_by']}撤回，评估状态转为{evaluation['status']}",
                })
            affected_evaluations.append(evaluation)

        return {
            "grant": grant,
            "summary": summary,
            "affected_evaluation_ids": [item["id"] for item in affected_evaluations],
        }

    # ── 实验评估：两组必须在同一有效授权边界内确认 ──

    def create_evaluation(
        self,
        experiment_name: str,
        control_grant_id: int,
        treatment_grant_id: int,
        analyst: str,
    ) -> dict[str, Any]:
        """实验团队发起一轮对照评估，分别绑定对照组/实验组的共享授权。

        发起即校验两个授权都处于有效状态；过期权限不得用于新试验。
        """
        experiment_name = (experiment_name or "").strip()
        analyst = (analyst or "").strip()
        if not experiment_name:
            raise SharingError("实验名称不能为空")
        if not analyst:
            raise SharingError("分析员不能为空")
        if int(control_grant_id) == int(treatment_grant_id):
            raise SharingError("对照组与实验组不能使用同一个共享授权")

        control_grant = self._require_active_grant(control_grant_id)
        treatment_grant = self._require_active_grant(treatment_grant_id)

        def make_group(role: str, grant: dict[str, Any]) -> dict[str, Any]:
            return {
                "group_role": role,
                "grant_id": grant["id"],
                "summary_id": grant.get("summary_id"),
                "cohort_id": grant.get("cohort_id"),
                "cohort_name": grant.get("cohort_name"),
                "confirmed": False,
                "confirmed_at": None,
                "confirmed_headcount": None,
                "summary_status_at_confirmation": None,
            }

        evaluation = store.append_evaluation({
            "experiment_name": experiment_name,
            "analyst": analyst,
            "recipient_team": control_grant.get("recipient_team"),
            "status": self.EVAL_PENDING,
            "boundary_grant_ids": sorted(
                [int(control_grant["id"]), int(treatment_grant["id"])]
            ),
            "groups": [
                make_group("control", control_grant),
                make_group("treatment", treatment_grant),
            ],
            "control_treatment_ratio": None,
            "confirmed_summary_ranges": [],
            "block_reasons": [],
            "eligible_to_generate": False,
            "can_start_new_round": True,
            "created_at": self._now(),
            "events": [{
                "time": self._now(),
                "event": "发起评估",
                "detail": (
                    f"分析员 {analyst} 发起评估，绑定授权 {control_grant['id']}"
                    f"（对照）/ {treatment_grant['id']}（实验）"
                ),
            }],
        })
        return self.eligibility_report(evaluation["id"])

    def confirm_group(self, evaluation_id: int, group_role: str) -> dict[str, Any]:
        """在有效授权边界内确认一个分组实际获得的授权实验汇总范围。"""
        evaluation = self._require_evaluation(evaluation_id)
        if evaluation["status"] == self.EVAL_READY:
            raise SharingError("两组汇总均已确认，评估已具备生成资格，无需重复确认")
        slot = self._group_slot(evaluation, group_role)
        if slot.get("confirmed"):
            raise SharingError(f"{group_role} 分组已确认，请勿重复确认")

        grant = self._require_active_grant(int(slot["grant_id"]))
        summary = store.find_summary(int(grant["summary_id"]))
        if summary is None or summary.get("status") != self.SUMMARY_ACTIVE:
            raise SharingError(
                f"授权 {grant['id']} 的授权实验汇总不可用，无法确认 {group_role} 分组"
            )

        slot["confirmed"] = True
        slot["confirmed_at"] = self._now()
        slot["confirmed_headcount"] = summary["headcount"]
        slot["summary_status_at_confirmation"] = summary["status"]
        evaluation.setdefault("events", []).append({
            "time": slot["confirmed_at"],
            "event": "确认分组",
            "detail": (
                f"{group_role} 分组在授权 {grant['id']} 的有效边界内确认，"
                f"实际获得汇总范围：群组人数 {summary['headcount']}"
            ),
        })
        self._recompute_evaluation(evaluation)
        return self.eligibility_report(evaluation_id)

    def _recompute_evaluation(self, evaluation: dict[str, Any]) -> dict[str, Any]:
        """按当前授权边界重算评估资格、比例和实际获得的汇总范围。"""
        block_reasons: list[str] = []
        ranges: list[dict[str, Any]] = []
        confirmed_count = 0

        for slot in evaluation["groups"]:
            grant = store.find_sharing_grant(int(slot["grant_id"]))
            grant_active = grant is not None and grant.get("status") == self.GRANT_ACTIVE
            summary = (
                store.find_summary(int(slot["summary_id"]))
                if slot.get("summary_id") else None
            )
            summary_active = summary is not None and summary.get("status") == self.SUMMARY_ACTIVE

            if not grant_active:
                block_reasons.append(
                    f"{slot['group_role']} 分组授权 {slot['grant_id']} 已失效（撤回后不得复用）"
                )
            elif not summary_active:
                block_reasons.append(
                    f"{slot['group_role']} 分组的授权实验汇总已失效"
                )
            if slot.get("confirmed"):
                confirmed_count += 1
                ranges.append({
                    "group_role": slot["group_role"],
                    "cohort_name": slot.get("cohort_name"),
                    "grant_id": slot["grant_id"],
                    "summary_id": slot.get("summary_id"),
                    "headcount": slot.get("confirmed_headcount"),
                    "confirmed_at": slot.get("confirmed_at"),
                    "grant_valid_now": grant_active,
                })

        both_confirmed = confirmed_count == len(evaluation["groups"])
        same_boundary = sorted(
            int(item["grant_id"]) for item in evaluation["groups"]
        ) == list(evaluation["boundary_grant_ids"])
        if not same_boundary:
            block_reasons.append("两组数据未落在同一授权边界内")

        evaluation["block_reasons"] = block_reasons
        evaluation["confirmed_summary_ranges"] = ranges
        evaluation["eligible_to_generate"] = both_confirmed and not block_reasons

        if evaluation["eligible_to_generate"]:
            control = self._group_slot(evaluation, "control")
            treatment = self._group_slot(evaluation, "treatment")
            control_size = max(1, int(control.get("confirmed_headcount") or 0))
            treatment_size = int(treatment.get("confirmed_headcount") or 0)
            evaluation["control_treatment_ratio"] = round(treatment_size / control_size, 4)
            evaluation["status"] = self.EVAL_READY
            evaluation["can_start_new_round"] = not block_reasons
        elif block_reasons:
            evaluation["status"] = self.EVAL_BLOCKED
            evaluation["control_treatment_ratio"] = None
            evaluation["can_start_new_round"] = False
        else:
            evaluation["status"] = self.EVAL_PENDING
            evaluation["can_start_new_round"] = True
        return evaluation

    def eligibility_report(self, evaluation_id: int) -> dict[str, Any]:
        """给分析员看的资格视图：本次对照能否生成、能否发起新一轮评估。"""
        evaluation = self._recompute_evaluation(self._require_evaluation(evaluation_id))
        return {
            "evaluation_id": evaluation["id"],
            "experiment_name": evaluation["experiment_name"],
            "status": evaluation["status"],
            "eligible_to_generate": evaluation["eligible_to_generate"],
            "can_start_new_round": evaluation["can_start_new_round"],
            "boundary_grant_ids": evaluation["boundary_grant_ids"],
            "groups": [
                {
                    "group_role": item["group_role"],
                    "cohort_name": item.get("cohort_name"),
                    "grant_id": item["grant_id"],
                    "summary_id": item.get("summary_id"),
                    "confirmed": item["confirmed"],
                    "confirmed_headcount": item.get("confirmed_headcount"),
                    "confirmed_at": item.get("confirmed_at"),
                    "grant_status": (
                        store.find_sharing_grant(int(item["grant_id"])) or {}
                    ).get("status"),
                }
                for item in evaluation["groups"]
            ],
            "control_treatment_ratio": evaluation["control_treatment_ratio"],
            "confirmed_summary_ranges": evaluation["confirmed_summary_ranges"],
            "block_reasons": evaluation["block_reasons"],
            "events": evaluation.get("events", []),
        }

    # ── 只读视图与成员保护 ──

    def list_grants(self) -> list[dict[str, Any]]:
        return store.sharing_grants()

    def list_summaries(self, recipient_team: str | None = None) -> list[dict[str, Any]]:
        rows = store.experiment_summaries()
        if recipient_team:
            rows = [row for row in rows if row.get("recipient_team") == recipient_team]
        return rows

    def list_evaluations(self) -> list[dict[str, Any]]:
        for row in store.experiment_evaluations():
            self._recompute_evaluation(row)
        return store.experiment_evaluations()

    def get_member_roster(self, cohort_id: int, requesting_team: str) -> dict[str, Any]:
        """成员名单保护：接收团队（实验团队）不得读取分群成员明细。

        个人资料与成员明细始终留在分群团队；接收方只能通过授权实验汇总
        获得聚合人数。本方法对任何非分群团队的请求一律拒绝。
        """
        self._require_cohort(cohort_id)
        if requesting_team != "分群团队":
            raise SharingError(
                "受控共享边界拒绝：接收团队只能查看获准的群组人数汇总，成员名单与个人资料"
                "留在分群团队，不对外提供"
            )
        members = store.get_cohort_snapshot(cohort_id) or []
        return {
            "cohort_id": cohort_id,
            "member_count": len(members),
            "members": members,
            "note": "仅分群团队可读取成员明细",
        }

    def domain_snapshot(self) -> dict[str, Any]:
        grants = store.sharing_grants()
        summaries = store.experiment_summaries()
        evaluations = store.experiment_evaluations()
        return {
            "module": "controlled_sharing",
            "entity": "共享授权",
            "artifact": "授权实验汇总与实验评估",
            "grant_count": len(grants),
            "active_grants": sum(1 for row in grants if row.get("status") == self.GRANT_ACTIVE),
            "revoked_grants": sum(1 for row in grants if row.get("status") == self.GRANT_REVOKED),
            "summary_count": len(summaries),
            "evaluation_count": len(evaluations),
            "blocked_evaluations": sum(
                1 for row in evaluations if row.get("status") == self.EVAL_BLOCKED
            ),
        }
