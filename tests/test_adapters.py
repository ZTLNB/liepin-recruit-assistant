"""数据导入适配器测试。"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from recruit_assistant.adapters import ADAPTERS, ManualImportSource  # noqa: E402
from recruit_assistant.models import CandidateStatus  # noqa: E402


class AdapterTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name: str, content: str, encoding: str = "utf-8") -> Path:
        path = self.dir / name
        path.write_text(content, encoding=encoding)
        return path


class TestCsvImport(AdapterTestCase):
    def test_chinese_headers(self):
        path = self.write(
            "c.csv",
            "姓名,年限,学历,当前职位,技能,简历正文\n"
            "张三,5,本科,后端工程师,Python|MySQL,熟悉Python和MySQL开发\n",
        )
        candidates = ManualImportSource(path).load()
        self.assertEqual(len(candidates), 1)

        cand = candidates[0]
        self.assertEqual(cand.name, "张三")
        self.assertEqual(cand.years, 5.0)
        self.assertEqual(cand.education, "本科")
        self.assertEqual(cand.current_title, "后端工程师")
        self.assertCountEqual(cand.skills, ["Python", "MySQL"])
        self.assertIn("MySQL", cand.resume_text)

    def test_english_headers(self):
        path = self.write(
            "c.csv",
            "name,years,education,current_title,skills\n"
            "Li Si,3,硕士,算法工程师,Go;Docker\n",
        )
        candidates = ManualImportSource(path).load()
        self.assertEqual(candidates[0].name, "Li Si")
        self.assertEqual(candidates[0].years, 3.0)
        self.assertCountEqual(candidates[0].skills, ["Go", "Docker"])

    def test_multiple_skill_separators(self):
        # 技能里含逗号时必须用引号包住,否则会和 CSV 的列分隔符冲突
        path = self.write(
            "c.csv",
            '姓名,技能\n王五,"Python|Go;Docker、Redis,MySQL"\n',
        )
        cand = ManualImportSource(path).load()[0]
        for skill in ["Python", "Go", "Docker", "Redis", "MySQL"]:
            self.assertIn(skill, cand.skills)

    def test_rows_without_name_skipped(self):
        path = self.write(
            "c.csv",
            "姓名,年限\n张三,5\n,3\n李四,4\n",
        )
        candidates = ManualImportSource(path).load()
        self.assertEqual(len(candidates), 2)
        self.assertEqual([c.name for c in candidates], ["张三", "李四"])

    def test_year_with_suffix_parsed(self):
        path = self.write("c.csv", "姓名,年限\n张三,3年\n")
        self.assertEqual(ManualImportSource(path).load()[0].years, 3.0)

    def test_empty_year_defaults_to_zero(self):
        path = self.write("c.csv", "姓名,年限\n张三,\n")
        self.assertEqual(ManualImportSource(path).load()[0].years, 0.0)

    def test_gbk_encoded_file(self):
        """Windows 导出的 CSV 常是 GBK,必须能读。"""
        path = self.write("c.csv", "姓名,年限\n张三,5\n", encoding="gbk")
        candidates = ManualImportSource(path).load()
        self.assertEqual(candidates[0].name, "张三")

    def test_utf8_bom_handled(self):
        path = self.dir / "bom.csv"
        path.write_bytes("姓名,年限\n张三,5\n".encode("utf-8-sig"))
        self.assertEqual(ManualImportSource(path).load()[0].name, "张三")

    def test_tab_separated(self):
        path = self.write("c.tsv", "姓名\t年限\n张三\t5\n")
        candidates = ManualImportSource(path).load()
        self.assertEqual(candidates[0].name, "张三")

    def test_unknown_columns_ignored(self):
        path = self.write(
            "c.csv",
            "姓名,莫名其妙列,年限\n张三,xxx,5\n",
        )
        cand = ManualImportSource(path).load()[0]
        self.assertEqual(cand.name, "张三")
        self.assertEqual(cand.years, 5.0)

    def test_status_column_parsed(self):
        path = self.write("c.csv", "姓名,状态\n张三,已入职\n")
        cand = ManualImportSource(path).load()[0]
        self.assertEqual(cand.status, CandidateStatus.HIRED)

    def test_invalid_status_falls_back_to_new(self):
        path = self.write("c.csv", "姓名,状态\n张三,乱七八糟\n")
        self.assertEqual(
            ManualImportSource(path).load()[0].status, CandidateStatus.NEW
        )


class TestJsonImport(AdapterTestCase):
    def test_list_of_objects(self):
        path = self.write(
            "c.json",
            '[{"name":"张三","years":5,"skills":["Python","MySQL"],'
            '"education":"本科","resume_text":"熟悉Python"}]',
        )
        candidates = ManualImportSource(path).load()
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].name, "张三")
        self.assertCountEqual(candidates[0].skills, ["Python", "MySQL"])

    def test_wrapped_in_candidates_key(self):
        path = self.write(
            "c.json",
            '{"candidates":[{"name":"李四","years":3}]}',
        )
        self.assertEqual(ManualImportSource(path).load()[0].name, "李四")

    def test_wrapped_in_data_key(self):
        path = self.write("c.json", '{"data":[{"name":"王五"}]}')
        self.assertEqual(ManualImportSource(path).load()[0].name, "王五")

    def test_chinese_keys(self):
        path = self.write(
            "c.json",
            '[{"姓名":"赵六","年限":4,"学历":"硕士","技能":["Java","Spring"]}]',
        )
        cand = ManualImportSource(path).load()[0]
        self.assertEqual(cand.name, "赵六")
        self.assertEqual(cand.years, 4.0)
        self.assertCountEqual(cand.skills, ["Java", "Spring"])

    def test_invalid_json_raises_valueerror(self):
        path = self.write("c.json", "{这不是合法JSON")
        with self.assertRaises(ValueError):
            ManualImportSource(path).load()

    def test_entries_without_name_skipped(self):
        path = self.write("c.json", '[{"years":3},{"name":"张三"}]')
        self.assertEqual(len(ManualImportSource(path).load()), 1)


class TestErrorHandling(AdapterTestCase):
    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            ManualImportSource(self.dir / "不存在.csv").load()

    def test_unsupported_format_raises(self):
        path = self.write("c.xlsx", "whatever")
        with self.assertRaises(ValueError):
            ManualImportSource(path).load()

    def test_empty_csv_returns_empty_list(self):
        path = self.write("c.csv", "")
        self.assertEqual(ManualImportSource(path).load(), [])


class TestRegistry(unittest.TestCase):
    def test_manual_adapter_registered(self):
        self.assertIn("manual", ADAPTERS)
        self.assertIs(ADAPTERS["manual"], ManualImportSource)


if __name__ == "__main__":
    unittest.main(verbosity=2)
