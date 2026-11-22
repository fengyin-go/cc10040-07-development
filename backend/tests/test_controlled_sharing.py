"""受控共享业务行为测试。

覆盖题设场景：
1. 把两个用户分群授权给实验团队，授权时聚合出只含群组人数的授权实验汇总；
2. 实验评估用两个汇总计算对照组/实验组比例，保存两边实际获得的汇总范围；
3. 两组人数尚未全部确认时撤回一方，当前评估失去资格、且不能再发起新一轮；
4. 撤回后新的试验不得复用过期权限；
5. 一次对照的两组数据必须在同一有效授权边界内确认；
6. 接收团队（实验团队）尝试读取成员名单时被拒绝，个人资料不出分群团队。
"""
from __future__ import annotations

import pytest

from app.services.controlled_sharing import (
    ControlledSharingService,
    SharingError,
)
from app.store import store


@pytest.fixture
def svc() -> ControlledSharingService:
    """每个用例使用全新的受控共享数据，避免授权/评估互相串扰。"""
    store._sharing_grants.clear()
    store._experiment_summaries.clear()
    store._experiment_evaluations.clear()
    return ControlledSharingService()


@pytest.fixture
def two_grants(svc: ControlledSharingService):
    """把种子分群 4、5 授权给实验团队，返回 (对照授权, 实验授权)。"""
    control = svc.create_grant(4, "实验团队", "分群负责人A")
    treatment = svc.create_grant(5, "实验团队", "分群负责人B")
    return control["grant"], treatment["grant"]


class TestGrantAndSummary:
    def test_grant_generates_headcount_only_summary(self, svc):
        result = svc.create_grant(4, "实验团队", "分群负责人A")
        grant, summary = result["grant"], result["summary"]

        assert grant["status"] == "有效"
        assert grant["recipient_team"] == "实验团队"
        # 汇总只包含聚合人数，不允许出现任何成员字段
        assert summary["headcount"] == 1200
        assert summary["status"] == "有效"
        assert "members" not in summary
        assert "user_id" not in str(summary)
        assert "仅群组人数" in summary["data_scope"]

    def test_duplicate_active_grant_rejected(self, svc):
        svc.create_grant(4, "实验团队", "分群负责人A")
        with pytest.raises(SharingError):
            svc.create_grant(4, "实验团队", "分群负责人A")

    def test_grant_on_unknown_cohort_rejected(self, svc):
        with pytest.raises(SharingError):
            svc.create_grant(9999, "实验团队", "分群负责人A")

    def test_member_roster_stays_with_cohort_team(self, svc):
        # 实验团队（接收方）拿成员名单必须被拒绝
        with pytest.raises(SharingError):
            svc.get_member_roster(4, "实验团队")
        # 分群团队自己仍可读取完整明细
        roster = svc.get_member_roster(4, "分群团队")
        assert roster["member_count"] == 1200
        assert roster["members"][0]["user_id"]


class TestEvaluationBoundary:
    def test_full_confirmation_generates_ratio_and_ranges(self, svc, two_grants):
        control_grant, treatment_grant = two_grants
        report = svc.create_evaluation(
            "推送文案对照实验", control_grant["id"], treatment_grant["id"], "分析员小王"
        )
        evaluation_id = report["evaluation_id"]
        assert report["status"] == "待确认"
        assert report["eligible_to_generate"] is False

        svc.confirm_group(evaluation_id, "control")
        mid = svc.eligibility_report(evaluation_id)
        # 只确认一组时还不能生成
        assert mid["status"] == "待确认"
        assert mid["eligible_to_generate"] is False
        assert len(mid["confirmed_summary_ranges"]) == 1

        svc.confirm_group(evaluation_id, "treatment")
        done = svc.eligibility_report(evaluation_id)

        assert done["status"] == "可生成"
        assert done["eligible_to_generate"] is True
        # 比例 = 实验组 800 / 对照组 1200
        assert done["control_treatment_ratio"] == round(800 / 1200, 4)
        # 两边实际获得的汇总范围都留档，且只有人数、没有明细
        ranges = done["confirmed_summary_ranges"]
        assert {item["group_role"] for item in ranges} == {"control", "treatment"}
        assert sorted(item["headcount"] for item in ranges) == [800, 1200]
        assert all("members" not in item for item in ranges)

    def test_revoke_before_both_confirmed_blocks_current_evaluation(
        self, svc, two_grants
    ):
        control_grant, treatment_grant = two_grants
        report = svc.create_evaluation(
            "首页改版对照实验", control_grant["id"], treatment_grant["id"], "分析员小李"
        )
        evaluation_id = report["evaluation_id"]
        svc.confirm_group(evaluation_id, "control")

        # 两组人数尚未全部确认，实验组负责人撤回共享
        revoke_result = svc.revoke_grant(treatment_grant["id"], "分群负责人B", "策略调整")
        assert evaluation_id in revoke_result["affected_evaluation_ids"]
        assert revoke_result["summary"]["status"] == "已失效"

        current = svc.eligibility_report(evaluation_id)
        # 当前评估失去生成资格，也不能基于该边界发起新一轮
        assert current["status"] == "失去资格"
        assert current["eligible_to_generate"] is False
        assert current["can_start_new_round"] is False
        assert any("已失效" in reason for reason in current["block_reasons"])
        # 对照组已确认的汇总范围仍留档可审计
        assert len(current["confirmed_summary_ranges"]) == 1

        # 撤回后继续确认该分组被拒绝
        with pytest.raises(SharingError):
            svc.confirm_group(evaluation_id, "treatment")

    def test_new_trial_cannot_reuse_revoked_grant(self, svc, two_grants):
        control_grant, treatment_grant = two_grants
        svc.revoke_grant(treatment_grant["id"], "分群负责人B")

        # 新评估直接绑定已撤回授权 → 发起即被拒绝
        with pytest.raises(SharingError):
            svc.create_evaluation(
                "新一轮实验", control_grant["id"], treatment_grant["id"], "分析员小李"
            )
        # 重新授权后（新授权 id 不同）才能发起新试验，旧权限不会被复用
        new_grant = svc.create_grant(5, "实验团队", "分群负责人B")
        new_report = svc.create_evaluation(
            "新一轮实验", control_grant["id"], new_grant["grant"]["id"], "分析员小李"
        )
        assert new_report["status"] == "待确认"
        assert treatment_grant["id"] not in new_report["boundary_grant_ids"]

    def test_same_grant_for_both_groups_rejected(self, svc, two_grants):
        control_grant, _ = two_grants
        with pytest.raises(SharingError):
            svc.create_evaluation(
                "错误对照", control_grant["id"], control_grant["id"], "分析员小赵"
            )

    def test_revoke_after_generation_keeps_confirmed_snapshot(self, svc, two_grants):
        """已经可生成的评估在撤回后保留确认时的汇总快照，结果可追溯。"""
        control_grant, treatment_grant = two_grants
        report = svc.create_evaluation(
            "已完成对照实验", control_grant["id"], treatment_grant["id"], "分析员小钱"
        )
        evaluation_id = report["evaluation_id"]
        svc.confirm_group(evaluation_id, "control")
        svc.confirm_group(evaluation_id, "treatment")
        ready = svc.eligibility_report(evaluation_id)
        assert ready["eligible_to_generate"] is True

        svc.revoke_grant(control_grant["id"], "分群负责人A")
        after = svc.eligibility_report(evaluation_id)
        assert after["status"] == "失去资格"
        # 确认时拿到的两组人数仍留档
        assert len(after["confirmed_summary_ranges"]) == 2
        assert after["control_treatment_ratio"] is None

    def test_evaluation_list_reflects_latest_boundary(self, svc, two_grants):
        control_grant, treatment_grant = two_grants
        report = svc.create_evaluation(
            "列表状态实验", control_grant["id"], treatment_grant["id"], "分析员小孙"
        )
        svc.confirm_group(report["evaluation_id"], "control")
        svc.revoke_grant(treatment_grant["id"], "分群负责人B")

        evaluations = svc.list_evaluations()
        target = next(item for item in evaluations if item["id"] == report["evaluation_id"])
        assert target["status"] == "失去资格"

    def test_unknown_evaluation_and_role_guarded(self, svc, two_grants):
        control_grant, treatment_grant = two_grants
        with pytest.raises(SharingError):
            svc.eligibility_report(9999)
        report = svc.create_evaluation(
            "角色校验实验", control_grant["id"], treatment_grant["id"], "分析员小周"
        )
        with pytest.raises(SharingError):
            svc.confirm_group(report["evaluation_id"], "unknown_role")

    def test_revoke_idempotent_guard(self, svc, two_grants):
        control_grant, _ = two_grants
        svc.revoke_grant(control_grant["id"], "分群负责人A")
        with pytest.raises(SharingError):
            svc.revoke_grant(control_grant["id"], "分群负责人A")
