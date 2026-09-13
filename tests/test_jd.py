"""JD 解析测试。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from recruit_assistant.jd import parse_jd  # noqa: E402


class TestSkillExtraction(unittest.TestCase):
    def test_basic_skills(self):
        jd = "熟悉 Python 和 MySQL,有 Redis 使用经验。"
        job = parse_jd("后端工程师", jd)
        self.assertIn("Python", job.skills)
        self.assertIn("MySQL", job.skills)
        self.assertIn("Redis", job.skills)

    def test_case_insensitive(self):
        job = parse_jd("工程师", "熟悉 PYTHON、javaScript 和 DOCKER")
        self.assertIn("Python", job.skills)
        self.assertIn("JavaScript", job.skills)
        self.assertIn("Docker", job.skills)

    def test_word_boundary_avoids_false_positive(self):
        """'javascript' 里不该被识别出 'java'。"""
        job = parse_jd("前端工程师", "精通 JavaScript 与 TypeScript")
        self.assertIn("JavaScript", job.skills)
        self.assertNotIn("Java", job.skills)

    def test_no_duplicate_skills(self):
        job = parse_jd("工程师", "Python Python python")
        self.assertEqual(job.skills.count("Python"), 1)

    def test_chinese_skill_alias(self):
        job = parse_jd("产品经理", "需要有产品经理经验,熟悉 PRD 撰写")
        self.assertIn("产品设计", job.skills)

    def test_empty_jd(self):
        job = parse_jd("岗位", "")
        self.assertEqual(job.skills, [])
        self.assertEqual(job.min_years, 0.0)


class TestYearParsing(unittest.TestCase):
    def test_min_years(self):
        for text, expected in [
            ("3年以上工作经验", 3.0),
            ("至少 5 年经验", 5.0),
            ("3年及以上", 3.0),
            ("不低于4年", 4.0),
        ]:
            with self.subTest(text=text):
                job = parse_jd("岗位", text)
                self.assertEqual(job.min_years, expected)

    def test_year_range(self):
        for text, lo, hi in [
            ("3-5年经验", 3.0, 5.0),
            ("3~5年", 3.0, 5.0),
            ("3到5年", 3.0, 5.0),
            ("5-3年", 3.0, 5.0),  # 写反了也要能兜住
        ]:
            with self.subTest(text=text):
                job = parse_jd("岗位", text)
                self.assertEqual(job.min_years, lo)
                self.assertEqual(job.max_years, hi)

    def test_no_year_requirement(self):
        job = parse_jd("岗位", "熟悉 Python 即可")
        self.assertEqual(job.min_years, 0.0)
        self.assertIsNone(job.max_years)


class TestEducationParsing(unittest.TestCase):
    def test_education_levels(self):
        for text, expected in [
            ("本科及以上学历", "本科"),
            ("硕士以上学历", "硕士"),
            ("博士学历", "博士"),
            ("大专以上", "大专"),
        ]:
            with self.subTest(text=text):
                job = parse_jd("岗位", text)
                self.assertEqual(job.education, expected)

    def test_highest_education_wins(self):
        job = parse_jd("岗位", "本科优先,硕士更佳")
        self.assertEqual(job.education, "硕士")

    def test_no_education(self):
        job = parse_jd("岗位", "熟悉 Python")
        self.assertEqual(job.education, "")


class TestBonusSeparation(unittest.TestCase):
    def test_bonus_skills_split_out(self):
        jd = "熟悉 Python 和 MySQL。有大模型经验者优先。"
        job = parse_jd("后端工程师", jd)
        self.assertIn("Python", job.skills)
        self.assertIn("MySQL", job.skills)
        self.assertIn("大模型", job.nice_to_have)
        # 加分技能不应出现在必需技能里
        self.assertNotIn("大模型", job.skills)

    def test_no_bonus_marker(self):
        job = parse_jd("工程师", "熟悉 Python 和 Go")
        self.assertEqual(job.nice_to_have, [])

    def test_keywords_from_title(self):
        job = parse_jd("高级后端工程师", "熟悉 Python")
        self.assertTrue(any("后端" in k for k in job.keywords))


if __name__ == "__main__":
    unittest.main(verbosity=2)
