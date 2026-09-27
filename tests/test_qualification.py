import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import DomainError, ProcurementService  # noqa: E402


class QualificationFlowTest(unittest.TestCase):
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
            "proc1", "procurement", "T-002", "网络设备", (datetime.now(timezone.utc) + timedelta(seconds=2)).isoformat(), criteria
        )
        self.tender = self.service.publish_tender("proc1", "procurement", self.tender["id"], self.tender["version"])

    def tearDown(self):
        self.tmp.cleanup()

    def qualify(self, vendor, actor, comment="材料齐全"):
        qualification = self.service.submit_qualification(actor, "vendor", self.tender["id"], vendor["id"], {"资质": "齐全"})
        return self.service.review_qualification(
            "proc1", "procurement", self.tender["id"], vendor["id"], "approved", comment, qualification["version"]
        )

    def bid(self, vendor, actor, price, quality):
        return self.service.submit_bid(actor, "vendor", self.tender["id"], vendor["id"], {"报价": price, "质量": quality}, price)

    def test_bid_requires_approved_qualification(self):
        with self.assertRaises(DomainError) as ctx:
            self.bid(self.vendor1, "vendor1", 800000, 90)
        self.assertEqual(409, ctx.exception.status)
        qualification = self.service.submit_qualification("vendor1", "vendor", self.tender["id"], self.vendor1["id"], {"资质": "齐全"})
        self.assertEqual("pending", qualification["status"])
        with self.assertRaises(DomainError):
            self.bid(self.vendor1, "vendor1", 800000, 90)
        self.service.review_qualification(
            "proc1", "procurement", self.tender["id"], self.vendor1["id"], "approved", "通过", qualification["version"]
        )
        self.assertEqual("sealed", self.bid(self.vendor1, "vendor1", 800000, 90)["status"])

    def test_rejection_requires_comment_and_allows_resubmit(self):
        qualification = self.service.submit_qualification("vendor1", "vendor", self.tender["id"], self.vendor1["id"], {"资质": "齐全"})
        with self.assertRaises(DomainError):
            self.service.review_qualification(
                "proc1", "procurement", self.tender["id"], self.vendor1["id"], "rejected", "", qualification["version"]
            )
        rejected = self.service.review_qualification(
            "proc1", "procurement", self.tender["id"], self.vendor1["id"], "rejected", "缺少纳税证明", qualification["version"]
        )
        self.assertEqual("rejected", rejected["status"])
        with self.assertRaises(DomainError):
            self.bid(self.vendor1, "vendor1", 800000, 90)
        resubmitted = self.service.submit_qualification(
            "vendor1", "vendor", self.tender["id"], self.vendor1["id"], {"资质": "补齐"}, expected_version=rejected["version"]
        )
        self.assertEqual("pending", resubmitted["status"])
        self.service.review_qualification(
            "proc1", "procurement", self.tender["id"], self.vendor1["id"], "approved", "通过", resubmitted["version"]
        )
        self.assertEqual("sealed", self.bid(self.vendor1, "vendor1", 800000, 90)["status"])

    def test_revoke_keeps_sealed_bid_and_opening_marks_failed(self):
        self.qualify(self.vendor1, "vendor1")
        self.qualify(self.vendor2, "vendor2")
        bid1 = self.bid(self.vendor1, "vendor1", 800000, 90)
        bid2 = self.bid(self.vendor2, "vendor2", 700000, 80)
        detail = self.service.get_tender("proc1", "procurement", self.tender["id"])
        qualification = next(q for q in detail["qualifications"] if q["vendor_id"] == self.vendor1["id"])
        revoked = self.service.revoke_qualification(
            "proc1", "procurement", self.tender["id"], self.vendor1["id"], "资质文件造假", qualification["version"]
        )
        self.assertEqual("revoked", revoked["status"])
        # 未开标投标仍保留为密封状态
        retained = [b for b in self.service.state("proc1", "procurement")["bids"] if b["id"] == bid1["id"]]
        self.assertEqual("sealed", retained[0]["status"])
        # 撤销时生成冻结记录
        events = self.service.get_tender("proc1", "procurement", self.tender["id"])["qualification_events"]
        revoke_event = next(e for e in events if e["action"] == "revoked")
        self.assertEqual([bid1["id"]], revoke_event["bid_ids"])
        self.assertEqual("资质文件造假", revoke_event["comment"])
        time.sleep(2.1)
        opened = self.service.open_bids("proc1", "procurement", self.tender["id"], self.tender["version"])
        self.assertEqual([bid2["id"]], [b["id"] for b in opened["bids"]])
        self.assertEqual(1, len(opened["failed"]))
        failed = opened["failed"][0]
        self.assertEqual(bid1["id"], failed["id"])
        self.assertEqual("qualification_failed", failed["status"])
        self.assertIn("资质文件造假", failed["status_reason"])
        # 资格审查未通过的投标不能评分
        with self.assertRaises(DomainError) as ctx:
            self.service.evaluate_bid("eval1", "evaluator", bid1["id"], {"报价": 800000, "质量": 90})
        self.assertEqual(409, ctx.exception.status)
        # 授标排名只含合格投标
        self.service.evaluate_bid("eval1", "evaluator", bid2["id"], {"报价": 700000, "质量": 80})
        current = self.service.get_tender("sup1", "supervisor", self.tender["id"])
        award = self.service.award_tender("sup1", "supervisor", self.tender["id"], current["tender"]["version"])
        self.assertEqual(bid2["id"], award["award"]["winner"]["bid_id"])
        self.assertEqual([bid2["id"]], [item["bid_id"] for item in award["award"]["ranking"]])

    def test_revoke_rules_and_permissions(self):
        self.qualify(self.vendor1, "vendor1")
        qualification = self.service.get_tender("proc1", "procurement", self.tender["id"])["qualifications"][0]
        with self.assertRaises(DomainError) as ctx:
            self.service.revoke_qualification("vendor1", "vendor", self.tender["id"], self.vendor1["id"], "越权", qualification["version"])
        self.assertEqual(403, ctx.exception.status)
        with self.assertRaises(DomainError):
            self.service.revoke_qualification("proc1", "procurement", self.tender["id"], self.vendor1["id"], "", qualification["version"])
        with self.assertRaises(DomainError) as ctx2:
            self.service.revoke_qualification("proc1", "procurement", self.tender["id"], self.vendor2["id"], "无记录", 1)
        self.assertEqual(404, ctx2.exception.status)
        with self.assertRaises(DomainError) as ctx3:
            self.service.submit_qualification(
                "vendor1", "vendor", self.tender["id"], self.vendor1["id"], {"资质": "新"}, expected_version=qualification["version"]
            )
        self.assertEqual(409, ctx3.exception.status)

    def test_detail_exposes_status_comment_and_events_by_role(self):
        self.qualify(self.vendor1, "vendor1")
        as_proc = self.service.get_tender("proc1", "procurement", self.tender["id"])
        self.assertEqual("approved", as_proc["qualifications"][0]["status"])
        self.assertEqual("材料齐全", as_proc["qualifications"][0]["review_comment"])
        self.assertTrue(any(e["action"] == "approved" for e in as_proc["qualification_events"]))
        as_vendor = self.service.get_tender("vendor1", "vendor", self.tender["id"])
        self.assertEqual(1, len(as_vendor["qualifications"]))
        self.assertTrue(any(e["action"] == "approved" for e in as_vendor["qualification_events"]))
        as_public = self.service.get_tender("", "public", self.tender["id"])
        self.assertNotIn("review_comment", as_public["qualifications"][0])
        self.assertEqual([], as_public["qualification_events"])


if __name__ == "__main__":
    unittest.main()
