"""话术生成测试。

核心断言:生成的草稿**必须**是未确认状态 —— 这是工具的合规底线。
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from recruit_assistant.message import (  # noqa: E402
    TEMPLATES,
    build_batch,
    build_message,
    list_templates,
)
from recruit_assistant.models import Candidate, JobProfile, MatchResult  # noqa: E402


def make_job() -> JobProfile:
    return JobProfile(title="后端工程师", skills=["Python", "MySQL"])


def make_candidate() -> Candidate:
    return Candidate(
        name="张三", skills=["Python", "MySQL", "Redis"],
        years=5.0, education="本科", current_title="高级后端工程师",
    )


class TestDraftGeneration(unittest.TestCase):
    def test_draft_is_never_auto_approved(self):
        """最关键的一条:草稿生成后必须是未确认状态。"""
        draft = build_message(make_candidate(), make_job())
        self.assertFalse(draft.approved)
        self.assertIsNone(draft.sent_at)

    def test_content_not_empty(self):
        draft = build_message(make_candidate(), make_job())
        self.assertTrue(len(draft.content) > 10)

    def test_placeholders_filled(self):
        draft = build_message(
            make_candidate(), make_job(), company="某某科技"
        )
        self.assertIn("张三", draft.content)
        self.assertIn("某某科技", draft.content)
        self.assertIn("后端工程师", draft.content)
        # 占位符必须被全部替换
        self.assertNotIn("{", draft.content)
        self.assertNotIn("}", draft.content)

    def test_default_company_used(self):
        draft = build_message(make_candidate(), make_job())
        self.assertIn("我们公司", draft.content)

    def test_template_recorded(self):
        draft = build_message(make_candidate(), make_job(), template="warm")
        self.assertEqual(draft.template, "warm")


class TestSkillHighlight(unittest.TestCase):
    def test_match_skill_hits_used(self):
        match = MatchResult(
            candidate_id="c", job_id="j", score=90,
            skill_hits=["Python", "MySQL"],
        )
        draft = build_message(make_candidate(), make_job(), match=match)
        self.assertIn("Python", draft.content)
        self.assertIn("MySQL", draft.content)

    def test_fallback_to_candidate_skills(self):
        """没有匹配结果时,退回用候选人自己的技能。"""
        cand = make_candidate()
        draft = build_message(cand, make_job(), match=None)
        self.assertTrue(any(s in draft.content for s in cand.skills))

    def test_no_skills_at_all_still_works(self):
        cand = Candidate(name="无名", skills=[], resume_text="")
        draft = build_message(cand, make_job())
        self.assertIn("相关技术", draft.content)

    def test_only_two_skills_picked(self):
        match = MatchResult(
            candidate_id="c", job_id="j", score=90,
            skill_hits=["Python", "MySQL", "Redis", "Go"],
        )
        draft = build_message(make_candidate(), make_job(), match=match)
        self.assertIn("Python、MySQL", draft.content)
        self.assertNotIn("Go", draft.content)


class TestTemplates(unittest.TestCase):
    def test_all_templates_render(self):
        """每个内置模板都必须能正常填充,不留占位符。"""
        for name in TEMPLATES:
            with self.subTest(template=name):
                draft = build_message(
                    make_candidate(), make_job(), template=name, company="测试公司"
                )
                self.assertNotIn("{", draft.content)

    def test_unknown_template_raises(self):
        with self.assertRaises(ValueError):
            build_message(make_candidate(), make_job(), template="不存在")

    def test_custom_template(self):
        draft = build_message(
            make_candidate(), make_job(),
            custom_template="{name}你好,我们在招{title}",
        )
        self.assertEqual(draft.content, "张三你好,我们在招后端工程师")
        self.assertEqual(draft.template, "custom")

    def test_list_templates(self):
        templates = list_templates()
        self.assertIn("default", templates)
        self.assertIn("warm", templates)


class TestBatch(unittest.TestCase):
    def test_batch_generates_all_unapproved(self):
        job = make_job()
        pairs = [
            (Candidate(name=f"候选人{i}", skills=["Python"]),
             MatchResult(candidate_id=f"c{i}", job_id=job.id, score=80 - i))
            for i in range(3)
        ]
        drafts = build_batch(pairs, job)
        self.assertEqual(len(drafts), 3)
        self.assertTrue(all(not d.approved for d in drafts))

    def test_batch_respects_limit(self):
        job = make_job()
        pairs = [
            (Candidate(name=f"候选人{i}", skills=["Python"]),
             MatchResult(candidate_id=f"c{i}", job_id=job.id, score=80))
            for i in range(10)
        ]
        self.assertEqual(len(build_batch(pairs, job, limit=4)), 4)

    def test_batch_empty(self):
        self.assertEqual(build_batch([], make_job()), [])


class TestFormatting(unittest.TestCase):
    def test_years_formatted_without_decimal(self):
        cand = make_candidate()
        cand.years = 3.0
        draft = build_message(cand, make_job(), template="senior")
        self.assertIn("3年", draft.content)
        self.assertNotIn("3.0", draft.content)

    def test_zero_years_shows_generic(self):
        cand = make_candidate()
        cand.years = 0
        draft = build_message(cand, make_job(), template="senior")
        self.assertIn("相关", draft.content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
