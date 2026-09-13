"""存储层测试。"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from recruit_assistant.models import (  # noqa: E402
    Candidate,
    CandidateStatus,
    JobProfile,
    MatchResult,
    MessageDraft,
)
from recruit_assistant.store import Store  # noqa: E402


class StoreTestCase(unittest.TestCase):
    """每个测试用独立的临时数据库,互不干扰。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test.db"
        self.store = Store(self.db_path)

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()


class TestJobCRUD(StoreTestCase):
    def test_add_and_get(self):
        job = JobProfile(title="后端工程师", skills=["Python"], min_years=3.0)
        self.store.add_job(job)

        fetched = self.store.get_job(job.id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.title, "后端工程师")
        self.assertEqual(fetched.skills, ["Python"])
        self.assertEqual(fetched.min_years, 3.0)

    def test_find_by_title(self):
        job = JobProfile(title="算法工程师")
        self.store.add_job(job)
        self.assertIsNotNone(self.store.find_job_by_title("算法工程师"))
        self.assertIsNone(self.store.find_job_by_title("不存在的岗位"))

    def test_list_jobs(self):
        for title in ["A岗", "B岗", "C岗"]:
            self.store.add_job(JobProfile(title=title))
        self.assertEqual(len(self.store.list_jobs()), 3)

    def test_nullable_max_years(self):
        job = JobProfile(title="岗位", min_years=3.0, max_years=None)
        self.store.add_job(job)
        self.assertIsNone(self.store.get_job(job.id).max_years)


class TestCandidateCRUD(StoreTestCase):
    def test_add_and_get(self):
        cand = Candidate(
            name="李四", skills=["Python", "Go"], years=6.0,
            education="硕士", current_title="高级工程师",
        )
        self.store.add_candidate(cand)

        fetched = self.store.get_candidate(cand.id)
        self.assertEqual(fetched.name, "李四")
        self.assertCountEqual(fetched.skills, ["Python", "Go"])
        self.assertEqual(fetched.status, CandidateStatus.NEW)

    def test_list_by_status(self):
        self.store.add_candidate(Candidate(name="A"))
        b = Candidate(name="B", status=CandidateStatus.INTERVIEW)
        self.store.add_candidate(b)

        new_only = self.store.list_candidates(status=CandidateStatus.NEW)
        self.assertEqual(len(new_only), 1)
        self.assertEqual(new_only[0].name, "A")

        interviewing = self.store.list_candidates(status=CandidateStatus.INTERVIEW)
        self.assertEqual(len(interviewing), 1)

    def test_update_status(self):
        cand = Candidate(name="王五")
        self.store.add_candidate(cand)

        ok = self.store.update_status(cand.id, CandidateStatus.INTERVIEW)
        self.assertTrue(ok)
        self.assertEqual(
            self.store.get_candidate(cand.id).status, CandidateStatus.INTERVIEW
        )

    def test_update_status_missing_returns_false(self):
        self.assertFalse(self.store.update_status("nope", CandidateStatus.HIRED))

    def test_count_by_status(self):
        self.store.add_candidate(Candidate(name="A"))
        self.store.add_candidate(Candidate(name="B"))
        self.store.add_candidate(Candidate(name="C", status=CandidateStatus.HIRED))

        counts = self.store.count_by_status()
        self.assertEqual(counts.get("NEW"), 2)
        self.assertEqual(counts.get("HIRED"), 1)

    def test_upsert_same_id_updates(self):
        cand = Candidate(name="赵六")
        self.store.add_candidate(cand)
        cand.name = "赵六(改名)"
        self.store.add_candidate(cand)

        self.assertEqual(len(self.store.list_candidates()), 1)
        self.assertEqual(self.store.get_candidate(cand.id).name, "赵六(改名)")


class TestMatchStorage(StoreTestCase):
    def test_save_and_get_sorted(self):
        job = JobProfile(title="岗位")
        self.store.add_job(job)

        for score in [60.0, 95.0, 75.0]:
            self.store.save_match(
                MatchResult(candidate_id=f"c{int(score)}", job_id=job.id, score=score)
            )

        results = self.store.get_matches(job.id)
        self.assertEqual([r.score for r in results], [95.0, 75.0, 60.0])

    def test_min_score_filter(self):
        job = JobProfile(title="岗位")
        self.store.add_job(job)
        self.store.save_match(MatchResult(candidate_id="a", job_id=job.id, score=90))
        self.store.save_match(MatchResult(candidate_id="b", job_id=job.id, score=40))

        self.assertEqual(len(self.store.get_matches(job.id, min_score=80)), 1)

    def test_rescoring_overwrites(self):
        job = JobProfile(title="岗位")
        self.store.add_job(job)
        self.store.save_match(MatchResult(candidate_id="a", job_id=job.id, score=50))
        self.store.save_match(MatchResult(candidate_id="a", job_id=job.id, score=88))

        results = self.store.get_matches(job.id)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].score, 88)

    def test_get_single_match(self):
        job = JobProfile(title="岗位")
        self.store.add_job(job)
        self.store.save_match(
            MatchResult(candidate_id="a", job_id=job.id, score=70, skill_hits=["Python"])
        )
        found = self.store.get_match("a", job.id)
        self.assertEqual(found.score, 70)
        self.assertEqual(found.skill_hits, ["Python"])
        self.assertIsNone(self.store.get_match("zzz", job.id))


class TestMessageWorkflow(StoreTestCase):
    """草稿审批流程 —— 这是本工具的核心合规设计,必须严格。"""

    def setUp(self):
        super().setUp()
        self.job = JobProfile(title="岗位")
        self.store.add_job(self.job)
        self.cand = Candidate(name="候选人")
        self.store.add_candidate(self.cand)
        self.draft = MessageDraft(
            candidate_id=self.cand.id, job_id=self.job.id, content="您好"
        )
        self.store.save_draft(self.draft)

    def test_draft_starts_unapproved(self):
        fetched = self.store.get_draft(self.draft.id)
        self.assertFalse(fetched.approved)
        self.assertIsNone(fetched.sent_at)

    def test_cannot_mark_sent_before_approval(self):
        """未确认的草稿不能登记为已发送 —— 这是关键防线。"""
        self.assertFalse(self.store.mark_sent(self.draft.id))
        self.assertIsNone(self.store.get_draft(self.draft.id).sent_at)

    def test_approve_then_send(self):
        self.assertTrue(self.store.approve_draft(self.draft.id))
        self.assertTrue(self.store.mark_sent(self.draft.id))

        fetched = self.store.get_draft(self.draft.id)
        self.assertTrue(fetched.approved)
        self.assertIsNotNone(fetched.sent_at)

    def test_pending_list_excludes_sent(self):
        self.assertEqual(len(self.store.list_drafts(only_pending=True)), 1)
        self.store.approve_draft(self.draft.id)
        self.store.mark_sent(self.draft.id)
        self.assertEqual(len(self.store.list_drafts(only_pending=True)), 0)

    def test_approve_missing_returns_false(self):
        self.assertFalse(self.store.approve_draft("nope"))

    def test_get_missing_draft(self):
        self.assertIsNone(self.store.get_draft("nope"))


class TestPersistence(StoreTestCase):
    def test_data_survives_reopen(self):
        cand = Candidate(name="持久化测试")
        self.store.add_candidate(cand)
        self.store.close()

        reopened = Store(self.db_path)
        try:
            self.assertEqual(len(reopened.list_candidates()), 1)
            self.assertEqual(reopened.get_candidate(cand.id).name, "持久化测试")
        finally:
            reopened.close()

    def test_corrupt_json_field_does_not_crash(self):
        """手工写入坏数据时,读取应返回空列表而不是崩溃。"""
        self.store.add_candidate(Candidate(name="A"))
        self.store.conn.execute("UPDATE candidates SET skills = ?", ("{坏数据",))
        self.store.conn.commit()

        cands = self.store.list_candidates()
        self.assertEqual(cands[0].skills, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
