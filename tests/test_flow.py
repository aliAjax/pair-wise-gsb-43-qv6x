import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import DomainError, ProcurementService  # noqa: E402


class ProcurementFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.service = ProcurementService(Path(self.tmp.name) / "test.db")
        self.vendor1 = self.service.create_vendor("proc1", "procurement", "V-001", "启明科技", "vendor1")
        self.vendor2 = self.service.create_vendor("proc1", "procurement", "V-002", "远山系统", "vendor2")
        criteria = [
            {"name": "报价", "weight": 60, "kind": "cost", "max_value": 1000000},
            {"name": "质量", "weight": 40, "kind": "direct", "max_value": 100},
        ]
        self.tender = self.service.create_tender(
            "proc1", "procurement", "T-001", "数据中心设备", (datetime.now(timezone.utc) + timedelta(seconds=2)).isoformat(), criteria
        )
        self.tender = self.service.publish_tender("proc1", "procurement", self.tender["id"], self.tender["version"])
        for vendor, actor in ((self.vendor1, "vendor1"), (self.vendor2, "vendor2")):
            qualification = self.service.submit_qualification(
                actor, "vendor", self.tender["id"], vendor["id"], {"营业执照": "已核验", "纳税证明": "已核验"}
            )
            self.service.review_qualification("proc1", "procurement", qualification["id"], "approved", "材料齐全")

    def tearDown(self):
        self.tmp.cleanup()

    def bid(self, vendor, actor, number, price, quality):
        return self.service.submit_bid(actor, "vendor", self.tender["id"], vendor["id"], {"报价": price, "质量": quality}, price)

    def test_complete_sealed_bid_open_evaluate_and_award_flow(self):
        self.bid(self.vendor1, "vendor1", "B1", 800000, 90)
        self.bid(self.vendor2, "vendor2", "B2", 700000, 80)
        before = self.service.get_tender("vendor1", "vendor", self.tender["id"])
        self.assertEqual("sealed", before["bids"][0]["status"])
        self.assertNotIn("payload", before["bids"][0])
        time.sleep(2.1)
        opened = self.service.open_bids("proc1", "procurement", self.tender["id"], self.tender["version"])
        self.assertEqual(2, len(opened["bids"]))
        self.service.evaluate_bid("eval1", "evaluator", opened["bids"][0]["id"], {"报价": 800000, "质量": 90})
        self.service.evaluate_bid("eval2", "evaluator", opened["bids"][0]["id"], {"报价": 800000, "质量": 90})
        self.service.evaluate_bid("eval1", "evaluator", opened["bids"][1]["id"], {"报价": 700000, "质量": 80})
        current = self.service.get_tender("sup1", "supervisor", self.tender["id"])
        self.assertEqual("opened", current["tender"]["status"])
        award = self.service.award_tender("sup1", "supervisor", self.tender["id"], current["tender"]["version"])
        self.assertEqual("awarded", award["tender"]["status"])
        self.assertEqual(opened["bids"][0]["id"], award["award"]["winner"]["bid_id"])

    def test_conflict_and_duplicate_evaluation_are_rejected(self):
        bid = self.bid(self.vendor1, "vendor1", "B3", 800000, 90)
        time.sleep(2.1)
        self.service.open_bids("proc1", "procurement", self.tender["id"], self.tender["version"])
        self.service.declare_conflict("eval1", "evaluator", self.tender["id"], "eval1", self.vendor1["id"], "曾受雇于供应商")
        with self.assertRaises(DomainError) as ctx:
            self.service.evaluate_bid("eval1", "evaluator", bid["id"], {"报价": 800000, "质量": 90})
        self.assertEqual(403, ctx.exception.status)
        self.service.evaluate_bid("eval2", "evaluator", bid["id"], {"报价": 800000, "质量": 90})
        with self.assertRaises(DomainError) as ctx2:
            self.service.evaluate_bid("eval2", "evaluator", bid["id"], {"报价": 800000, "质量": 90})
        self.assertEqual(409, ctx2.exception.status)

    def test_complaint_reevaluation_award_block_and_permissions(self):
        bid = self.bid(self.vendor1, "vendor1", "B4", 800000, 90)
        time.sleep(2.1)
        self.service.open_bids("proc1", "procurement", self.tender["id"], self.tender["version"])
        self.service.evaluate_bid("eval1", "evaluator", bid["id"], {"报价": 800000, "质量": 90})
        complaint = self.service.submit_complaint("vendor1", "vendor", self.tender["id"], "评分标准理解有误")
        current = self.service.get_tender("sup1", "supervisor", self.tender["id"])
        with self.assertRaises(DomainError):
            self.service.award_tender("sup1", "supervisor", self.tender["id"], current["tender"]["version"])
        resolved = self.service.resolve_complaint("sup1", "supervisor", complaint["id"], "accepted", "按新规则重评")
        self.assertEqual("accepted", resolved["status"])
        updated = self.service.get_tender("sup1", "supervisor", self.tender["id"])["tender"]
        self.assertEqual("reevaluation", updated["status"])
        self.assertEqual(2, updated["evaluation_round"])
        with self.assertRaises(DomainError) as ctx:
            self.service.open_bids("vendor1", "vendor", self.tender["id"], updated["version"])
        self.assertEqual(403, ctx.exception.status)


class QualificationFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.service = ProcurementService(Path(self.tmp.name) / "qualification.db")
        self.vendor1 = self.service.create_vendor("proc1", "procurement", "V-001", "启明科技", "vendor1")
        self.vendor2 = self.service.create_vendor("proc1", "procurement", "V-002", "远山系统", "vendor2")
        criteria = [
            {"name": "报价", "weight": 60, "kind": "cost", "max_value": 1000000},
            {"name": "质量", "weight": 40, "kind": "direct", "max_value": 100},
        ]
        self.tender = self.service.create_tender(
            "proc1", "procurement", "T-002", "园区网络设备", (datetime.now(timezone.utc) + timedelta(seconds=2)).isoformat(), criteria
        )
        self.tender = self.service.publish_tender("proc1", "procurement", self.tender["id"], self.tender["version"])

    def tearDown(self):
        self.tmp.cleanup()

    def submit_qual(self, vendor, actor, materials=None):
        if materials is None:
            materials = {"营业执照": "已核验", "纳税证明": "已核验"}
        return self.service.submit_qualification(
            actor, "vendor", self.tender["id"], vendor["id"], materials
        )

    def approve(self, vendor, actor, comment="材料齐全"):
        qualification = self.submit_qual(vendor, actor)
        return self.service.review_qualification("proc1", "procurement", qualification["id"], "approved", comment)

    def bid(self, vendor, actor, price, quality):
        return self.service.submit_bid(
            actor, "vendor", self.tender["id"], vendor["id"], {"报价": price, "质量": quality}, price
        )

    def test_bid_requires_approved_qualification(self):
        with self.assertRaises(DomainError) as ctx:
            self.bid(self.vendor1, "vendor1", 800000, 90)
        self.assertEqual(409, ctx.exception.status)
        qualification = self.submit_qual(self.vendor1, "vendor1")
        self.assertEqual("pending", qualification["status"])
        with self.assertRaises(DomainError):
            self.bid(self.vendor1, "vendor1", 800000, 90)
        reviewed = self.service.review_qualification("proc1", "procurement", qualification["id"], "approved", "通过")
        self.assertEqual("approved", reviewed["status"])
        self.assertEqual("sealed", self.bid(self.vendor1, "vendor1", 800000, 90)["status"])

    def test_rejection_blocks_bid_and_resubmission_reopens_gate(self):
        qualification = self.submit_qual(self.vendor1, "vendor1", {"营业执照": "已核验"})
        self.service.review_qualification("proc1", "procurement", qualification["id"], "rejected", "缺少纳税证明")
        with self.assertRaises(DomainError):
            self.bid(self.vendor1, "vendor1", 800000, 90)
        resubmitted = self.submit_qual(self.vendor1, "vendor1", {"营业执照": "已核验", "纳税证明": "已补齐"})
        self.assertEqual("pending", resubmitted["status"])
        self.assertEqual("", resubmitted["review_comment"])
        self.service.review_qualification("proc1", "procurement", resubmitted["id"], "approved", "补齐后通过")
        self.assertEqual("sealed", self.bid(self.vendor1, "vendor1", 800000, 90)["status"])

    def test_revoke_keeps_sealed_bid_and_marks_failure_at_opening(self):
        self.approve(self.vendor1, "vendor1")
        qualified2 = self.approve(self.vendor2, "vendor2")
        bid1 = self.bid(self.vendor1, "vendor1", 800000, 90)
        bid2 = self.bid(self.vendor2, "vendor2", 700000, 85)
        revoked = self.service.revoke_qualification("proc1", "procurement", qualified2["id"], "资质证书过期")
        self.assertEqual("revoked", revoked["status"])
        # 撤销后不能再修改原投标，原投标仍然保留为密封状态
        with self.assertRaises(DomainError):
            self.bid(self.vendor2, "vendor2", 650000, 85)
        own = self.service.get_tender("vendor2", "vendor", self.tender["id"])
        self.assertEqual("sealed", own["bids"][0]["status"])
        time.sleep(2.1)
        opened = self.service.open_bids("proc1", "procurement", self.tender["id"], self.tender["version"])
        statuses = {b["id"]: b for b in opened["bids"]}
        self.assertEqual("opened", statuses[bid1["id"]]["status"])
        self.assertEqual("qualification_failed", statuses[bid2["id"]]["status"])
        self.assertIn("资格审查未通过", statuses[bid2["id"]]["status_reason"])
        self.assertIn("资质证书过期", statuses[bid2["id"]]["status_reason"])
        # 资格未通过的投标不能评分
        with self.assertRaises(DomainError) as ctx:
            self.service.evaluate_bid("eval1", "evaluator", bid2["id"], {"报价": 700000, "质量": 85})
        self.assertEqual(409, ctx.exception.status)
        self.service.evaluate_bid("eval1", "evaluator", bid1["id"], {"报价": 800000, "质量": 90})
        detail = self.service.get_tender("sup1", "supervisor", self.tender["id"])
        # 原投标仍保留在投标列表中
        self.assertIn("qualification_failed", {b["status"] for b in detail["bids"]})
        award = self.service.award_tender("sup1", "supervisor", self.tender["id"], detail["tender"]["version"])
        self.assertEqual(bid1["id"], award["award"]["winner"]["bid_id"])
        self.assertEqual([bid1["id"]], [item["bid_id"] for item in award["award"]["ranking"]])
        # 详情页展示资格状态、审核意见与每次变更的冻结记录
        quals = {q["vendor_id"]: q for q in detail["qualifications"]}
        self.assertEqual("revoked", quals[self.vendor2["id"]]["status"])
        self.assertEqual("资质证书过期", quals[self.vendor2["id"]]["review_comment"])
        self.assertEqual(
            [("submitted", "pending"), ("approved", "approved"), ("revoked", "revoked")],
            [(e["action"], e["status"]) for e in quals[self.vendor2["id"]]["events"]],
        )
        self.assertEqual("资质证书过期", quals[self.vendor2["id"]]["events"][-1]["comment"])

    def test_resubmit_after_revoke_can_restore_bid_before_opening(self):
        self.approve(self.vendor1, "vendor1")
        qualified2 = self.approve(self.vendor2, "vendor2")
        bid1 = self.bid(self.vendor1, "vendor1", 800000, 90)
        bid2 = self.bid(self.vendor2, "vendor2", 700000, 85)
        self.service.revoke_qualification("proc1", "procurement", qualified2["id"], "材料存疑")
        resubmitted = self.submit_qual(self.vendor2, "vendor2")
        self.service.review_qualification("proc1", "procurement", resubmitted["id"], "approved", "复核通过")
        time.sleep(2.1)
        opened = self.service.open_bids("proc1", "procurement", self.tender["id"], self.tender["version"])
        statuses = {b["id"]: b["status"] for b in opened["bids"]}
        self.assertEqual("opened", statuses[bid1["id"]])
        self.assertEqual("opened", statuses[bid2["id"]])

    def test_revoke_after_opening_is_rejected(self):
        qualified = self.approve(self.vendor1, "vendor1")
        self.bid(self.vendor1, "vendor1", 800000, 90)
        time.sleep(2.1)
        self.service.open_bids("proc1", "procurement", self.tender["id"], self.tender["version"])
        with self.assertRaises(DomainError) as ctx:
            self.service.revoke_qualification("proc1", "procurement", qualified["id"], "事后发现造假")
        self.assertEqual(409, ctx.exception.status)

    def test_qualification_permissions_and_validation(self):
        qualification = self.submit_qual(self.vendor1, "vendor1")
        with self.assertRaises(DomainError) as ctx:
            self.service.review_qualification("vendor1", "vendor", qualification["id"], "approved")
        self.assertEqual(403, ctx.exception.status)
        with self.assertRaises(DomainError) as ctx:
            self.service.submit_qualification("proc1", "procurement", self.tender["id"], self.vendor2["id"], {"a": 1})
        self.assertEqual(403, ctx.exception.status)
        with self.assertRaises(DomainError) as ctx:
            self.service.review_qualification("proc1", "procurement", qualification["id"], "rejected")
        self.assertEqual(400, ctx.exception.status)
        with self.assertRaises(DomainError) as ctx:
            self.submit_qual(self.vendor2, "vendor2", {})
        self.assertEqual(400, ctx.exception.status)
        with self.assertRaises(DomainError) as ctx:
            self.service.revoke_qualification("proc1", "procurement", qualification["id"], "测试")
        self.assertEqual(409, ctx.exception.status)
        self.service.review_qualification("proc1", "procurement", qualification["id"], "approved")
        with self.assertRaises(DomainError) as ctx:
            self.service.review_qualification("proc1", "procurement", qualification["id"], "rejected", "再判")
        self.assertEqual(409, ctx.exception.status)
        # 供应商只能看到自己的资格记录
        own = self.service.get_tender("vendor1", "vendor", self.tender["id"])
        self.assertEqual([self.vendor1["id"]], [q["vendor_id"] for q in own["qualifications"]])
        self.assertEqual([], self.service.get_tender("anon", "public", self.tender["id"])["qualifications"])


if __name__ == "__main__":
    unittest.main()
