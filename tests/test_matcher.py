"""匹配打分测试。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from recruit_assistant.matcher import (  # noqa: E402
    candidate_skill_set,
    rank_candidates,
    score_candidate,
)
from recruit_assistant.models import Candidate, JobProfile  # noqa: E402


def make_job(**kw) -> JobProfile:
    """构造一个可控的岗位画像,避免依赖 JD 解析结果。"""
    defaults = dict(
        title="后端工程师",
        skills=["Python", "MySQL", "Redis"],
        nice_to_have=[],
        min_years=3.0,
        max_years=None,
        education="本科",
        keywords=[],
    )
    defaults.update(kw)
    return JobProfile(**defaults)


def make_candidate(**kw) -> Candidate:
    defaults = dict(
        name="张三",
        skills=["Python", "MySQL", "Redis"],
        years=5.0,
        education="本科",
        resume_text="Python MySQL Redis",
    )
    defaults.update(kw)
    return Candidate(**defaults)


class TestScoreRange(unittest.TestCase):
    def test_perfect_match_scores_high(self):
        result = score_candidate(make_candidate(), make_job())
        self.assertGreaterEqual(result.score, 95)
        self.assertEqual(result.grade, "A")

    def test_score_never_exceeds_100(self):
        result = score_candidate(make_candidate(), make_job())
        self.assertLessEqual(result.score, 100.0)

    def test_score_never_below_zero(self):
        cand = make_candidate(
            skills=[], resume_text="", years=0.0, education="大专"
        )
        job = make_job(min_years=10.0, nice_to_have=["Go", "Kafka"])
        result = score_candidate(cand, job)
        self.assertGreaterEqual(result.score, 0.0)

    def test_no_skill_match_scores_low(self):
        cand = make_candidate(skills=["Photoshop"], resume_text="Photoshop")
        result = score_candidate(cand, make_job())
        self.assertLess(result.score, 50)
        self.assertEqual(len(result.skill_hits), 0)
        self.assertEqual(len(result.skill_misses), 3)


class TestSkillScoring(unittest.TestCase):
    def test_skills_recognized_from_resume_text(self):
        """技能散落在简历正文里也要能识别出来。"""
        cand = make_candidate(skills=[], resume_text="精通 Python、MySQL 与 Redis")
        result = score_candidate(cand, make_job())
        self.assertCountEqual(result.skill_hits, ["Python", "MySQL", "Redis"])

    def test_partial_skill_match(self):
        cand = make_candidate(skills=["Python"], resume_text="Python")
        result = score_candidate(cand, make_job())
        self.assertEqual(result.skill_hits, ["Python"])
        self.assertCountEqual(result.skill_misses, ["MySQL", "Redis"])

    def test_skill_alias_normalized(self):
        """'vue.js' 应被归一到 'Vue'。"""
        job = make_job(skills=["Vue"], education="", min_years=0)
        cand = make_candidate(skills=["vue.js"], resume_text="")
        result = score_candidate(cand, job)
        self.assertIn("Vue", result.skill_hits)

    def test_no_required_skills_gives_full_marks(self):
        job = make_job(skills=[], education="", min_years=0)
        result = score_candidate(make_candidate(), job)
        self.assertGreaterEqual(result.score, 95)


class TestExperienceScoring(unittest.TestCase):
    def test_insufficient_experience_penalized(self):
        job = make_job(min_years=10.0)
        cand = make_candidate(years=2.0)
        result = score_candidate(cand, job)
        self.assertTrue(any("低于要求下限" in r for r in result.reasons))

    def test_overqualified_penalized(self):
        job = make_job(min_years=3.0, max_years=5.0)
        cand = make_candidate(years=15.0)
        result = score_candidate(cand, job)
        self.assertTrue(any("资历过高" in r for r in result.reasons))

    def test_within_range_full_marks(self):
        job = make_job(min_years=3.0, max_years=5.0)
        cand = make_candidate(years=4.0)
        result = score_candidate(cand, job)
        self.assertTrue(any("符合要求" in r for r in result.reasons))

    def test_worse_experience_scores_lower(self):
        job = make_job(min_years=8.0)
        close = score_candidate(make_candidate(years=6.0), job)
        far = score_candidate(make_candidate(years=1.0), job)
        self.assertGreater(close.score, far.score)


class TestEducationScoring(unittest.TestCase):
    def test_higher_education_ok(self):
        job = make_job(education="本科")
        result = score_candidate(make_candidate(education="硕士"), job)
        self.assertTrue(any("满足要求" in r for r in result.reasons))

    def test_one_level_lower_gets_half(self):
        job = make_job(education="本科")
        result = score_candidate(make_candidate(education="大专"), job)
        self.assertTrue(any("给一半分" in r for r in result.reasons))

    def test_two_levels_lower_gets_zero(self):
        job = make_job(education="博士")
        result = score_candidate(make_candidate(education="大专"), job)
        self.assertTrue(any("明显低于要求" in r for r in result.reasons))

    def test_unknown_education_gets_half(self):
        job = make_job(education="本科")
        result = score_candidate(make_candidate(education=""), job)
        self.assertTrue(any("学历未知" in r for r in result.reasons))


class TestBonusSkills(unittest.TestCase):
    def test_bonus_hits_recorded(self):
        job = make_job(nice_to_have=["Go", "Kafka"])
        cand = make_candidate(skills=["Python", "MySQL", "Redis", "Go"])
        result = score_candidate(cand, job)
        self.assertIn("Go", result.bonus_hits)


class TestReasonsAndGrade(unittest.TestCase):
    def test_reasons_always_present(self):
        result = score_candidate(make_candidate(), make_job())
        self.assertTrue(len(result.reasons) >= 4)
        self.assertTrue(any("分项" in r for r in result.reasons))

    def test_grade_thresholds(self):
        from recruit_assistant.models import MatchResult

        cases = [(95, "A"), (85, "A"), (75, "B"), (60, "C"), (30, "D")]
        for score, expected in cases:
            with self.subTest(score=score):
                result = MatchResult(candidate_id="c", job_id="j", score=score)
                self.assertEqual(result.grade, expected)


class TestRanking(unittest.TestCase):
    def test_ranked_descending(self):
        job = make_job()
        candidates = [
            make_candidate(name="差", skills=["Python"], resume_text="Python"),
            make_candidate(name="好", skills=["Python", "MySQL", "Redis"]),
            make_candidate(name="中", skills=["Python", "MySQL"], resume_text="Python MySQL"),
        ]
        results = rank_candidates(candidates, job)
        scores = [r.score for r in results]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_min_score_filter(self):
        job = make_job()
        candidates = [
            make_candidate(name="好"),
            make_candidate(name="差", skills=["Excel"], resume_text="Excel"),
        ]
        results = rank_candidates(candidates, job, min_score=80)
        self.assertEqual(len(results), 1)

    def test_candidate_skill_set_merges_sources(self):
        cand = make_candidate(skills=["Python"], resume_text="熟悉 Kafka 和 Docker")
        merged = candidate_skill_set(cand)
        self.assertIn("Python", merged)
        self.assertIn("Kafka", merged)
        self.assertIn("Docker", merged)


if __name__ == "__main__":
    unittest.main(verbosity=2)
