"""CLI 端到端测试 —— 走一遍完整招聘流程。"""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from recruit_assistant.cli import main  # noqa: E402


def run_cli(*argv) -> tuple[int, str]:
    """执行 CLI 并捕获输出。"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = main(list(argv))
    return code, buf.getvalue()


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.db = str(self.dir / "test.db")
        self.rate = str(self.dir / "rate.json")
        # 公共参数前缀
        self.base = ["--db", self.db, "--rate-state", self.rate]

    def tearDown(self):
        self._tmp.cleanup()

    def cli(self, *argv) -> tuple[int, str]:
        return run_cli(*self.base, *argv)


class TestInitAndHelp(CliTestCase):
    def test_init_creates_db(self):
        code, out = self.cli("init")
        self.assertEqual(code, 0)
        self.assertTrue(Path(self.db).exists())
        self.assertIn("数据目录已就绪", out)

    def test_no_args_prints_help(self):
        code, out = run_cli()
        self.assertEqual(code, 0)
        self.assertIn("recruit", out.lower())

    def test_init_mentions_no_auto_send(self):
        """init 输出必须明确告知不会自动发消息。"""
        _, out = self.cli("init")
        self.assertIn("不会自动", out)


class TestJobCommands(CliTestCase):
    def test_job_add_parses_jd(self):
        code, out = self.cli(
            "job", "add",
            "--title", "后端工程师",
            "--jd", "3年以上经验,本科以上,熟悉 Python 和 MySQL。有 Kafka 经验者优先。",
        )
        self.assertEqual(code, 0)
        self.assertIn("后端工程师", out)
        self.assertIn("Python", out)
        self.assertIn("Kafka", out)

    def test_job_add_from_file(self):
        jd_file = self.dir / "jd.txt"
        jd_file.write_text("5年以上,熟悉 Go 和 Docker", encoding="utf-8")

        code, out = self.cli(
            "job", "add", "--title", "运维工程师", "--jd-file", str(jd_file)
        )
        self.assertEqual(code, 0)
        self.assertIn("Go", out)

    def test_job_add_without_jd_exits(self):
        with self.assertRaises(SystemExit):
            self.cli("job", "add", "--title", "岗位")

    def test_job_add_missing_file_exits(self):
        with self.assertRaises(SystemExit):
            self.cli("job", "add", "--title", "岗位", "--jd-file", "不存在.txt")

    def test_job_list_empty(self):
        code, out = self.cli("job", "list")
        self.assertEqual(code, 0)
        self.assertIn("暂无岗位", out)

    def test_job_list_after_add(self):
        self.cli("job", "add", "--title", "算法工程师", "--jd", "熟悉 PyTorch")
        code, out = self.cli("job", "list")
        self.assertIn("算法工程师", out)


class TestCandidateCommands(CliTestCase):
    def setUp(self):
        super().setUp()
        self.csv = self.dir / "cands.csv"
        self.csv.write_text(
            "姓名,年限,学历,当前职位,技能,简历正文\n"
            "张三,6,硕士,高级后端工程师,Python|MySQL|Redis,熟悉Python MySQL Redis\n"
            "李四,2,本科,初级工程师,Python,会一点Python\n"
            "王五,8,博士,架构师,Go|Kafka|Docker,精通Go和Kafka\n",
            encoding="utf-8",
        )

    def test_import_csv(self):
        code, out = self.cli("candidate", "import", str(self.csv))
        self.assertEqual(code, 0)
        self.assertIn("已导入 3 名", out)

    def test_import_missing_file_exits(self):
        with self.assertRaises(SystemExit):
            self.cli("candidate", "import", str(self.dir / "无.csv"))

    def test_candidate_list(self):
        self.cli("candidate", "import", str(self.csv))
        code, out = self.cli("candidate", "list")
        self.assertIn("张三", out)
        self.assertIn("王五", out)

    def test_candidate_list_filter_by_status(self):
        self.cli("candidate", "import", str(self.csv))
        _, out = self.cli("candidate", "list", "--status", "INTERVIEW")
        self.assertIn("没有符合条件", out)

    def test_candidate_status_update(self):
        self.cli("candidate", "import", str(self.csv))
        code, out = self.cli("candidate", "status", "张三", "INTERVIEW")
        self.assertEqual(code, 0)
        self.assertIn("面试中", out)

        _, listing = self.cli("candidate", "list", "--status", "INTERVIEW")
        self.assertIn("张三", listing)

    def test_candidate_status_invalid_value(self):
        self.cli("candidate", "import", str(self.csv))
        with self.assertRaises(SystemExit):
            self.cli("candidate", "status", "张三", "不存在的状态")

    def test_candidate_status_unknown_person(self):
        self.cli("candidate", "import", str(self.csv))
        with self.assertRaises(SystemExit):
            self.cli("candidate", "status", "查无此人", "HIRED")


class TestMatchCommands(CliTestCase):
    def setUp(self):
        super().setUp()
        self.cli(
            "job", "add", "--title", "后端工程师",
            "--jd", "3年以上经验,本科及以上,熟悉 Python、MySQL、Redis。",
        )
        csv = self.dir / "c.csv"
        csv.write_text(
            "姓名,年限,学历,技能,简历正文\n"
            "高手,6,硕士,Python|MySQL|Redis,精通Python MySQL Redis\n"
            "新手,1,大专,Python,只学过Python\n",
            encoding="utf-8",
        )
        self.cli("candidate", "import", str(csv))

    def test_match_runs(self):
        code, out = self.cli("match", "--job", "后端工程师")
        self.assertEqual(code, 0)
        self.assertIn("已完成匹配", out)
        self.assertIn("高手", out)

    def test_match_ranks_better_candidate_first(self):
        _, out = self.cli("match", "--job", "后端工程师")
        # 高手应排在新手前面
        self.assertLess(out.index("高手"), out.index("新手"))

    def test_match_show(self):
        self.cli("match", "--job", "后端工程师")
        code, out = self.cli("match", "show", "--job", "后端工程师")
        self.assertEqual(code, 0)
        self.assertIn("匹配详情", out)

    def test_match_show_verbose_includes_reasons(self):
        self.cli("match", "--job", "后端工程师")
        _, out = self.cli("match", "show", "--job", "后端工程师", "--verbose")
        self.assertIn("分项", out)

    def test_match_min_score_filters(self):
        _, out = self.cli("match", "--job", "后端工程师", "--min-score", "80")
        self.assertNotIn("新手", out)

    def test_match_unknown_job_exits(self):
        with self.assertRaises(SystemExit):
            self.cli("match", "--job", "不存在的岗位")

    def test_match_show_before_run(self):
        code, out = self.cli("match", "show", "--job", "后端工程师")
        self.assertEqual(code, 0)
        self.assertIn("暂无匹配记录", out)

    def test_match_no_candidates_exits(self):
        fresh_db = str(self.dir / "empty.db")
        run_cli("--db", fresh_db, "--rate-state", self.rate,
                "job", "add", "--title", "岗位", "--jd", "熟悉 Python")
        with self.assertRaises(SystemExit):
            run_cli("--db", fresh_db, "--rate-state", self.rate,
                    "match", "--job", "岗位")


class TestMessageCommands(CliTestCase):
    def setUp(self):
        super().setUp()
        self.cli(
            "job", "add", "--title", "后端工程师",
            "--jd", "3年以上,本科,熟悉 Python、MySQL、Redis。",
        )
        csv = self.dir / "c.csv"
        csv.write_text(
            "姓名,年限,学历,技能,简历正文\n"
            "张三,6,硕士,Python|MySQL|Redis,精通Python MySQL Redis\n"
            "李四,5,本科,Python|MySQL,熟悉Python和MySQL\n",
            encoding="utf-8",
        )
        self.cli("candidate", "import", str(csv))
        self.cli("match", "--job", "后端工程师")

    def test_draft_generation(self):
        code, out = self.cli(
            "message", "draft", "--job", "后端工程师", "--candidate", "张三",
            "--company", "测试科技",
        )
        self.assertEqual(code, 0)
        self.assertIn("未发送", out)
        self.assertIn("测试科技", out)

    def test_draft_unknown_candidate_exits(self):
        with self.assertRaises(SystemExit):
            self.cli("message", "draft", "--job", "后端工程师", "--candidate", "查无此人")

    def test_batch_generation(self):
        code, out = self.cli(
            "message", "batch", "--job", "后端工程师", "--limit", "2",
            "--min-score", "0",
        )
        self.assertEqual(code, 0)
        self.assertIn("2 条草稿", out)

    def test_message_list_pending(self):
        self.cli("message", "draft", "--job", "后端工程师", "--candidate", "张三")
        code, out = self.cli("message", "list", "--pending")
        self.assertIn("草稿", out)

    def test_full_approve_and_send_flow(self):
        """完整流程:草稿 → 确认 → 登记发送。"""
        _, out = self.cli(
            "message", "draft", "--job", "后端工程师", "--candidate", "张三"
        )
        # 从输出里提取草稿 ID
        draft_id = None
        for token in out.split():
            if token.startswith("msg_"):
                draft_id = token.strip("(),:;")
                break
        self.assertIsNotNone(draft_id, f"未能从输出解析草稿 ID:{out}")

        code, approve_out = self.cli("message", "approve", draft_id)
        self.assertEqual(code, 0)
        self.assertIn("已确认", approve_out)

        code, sent_out = self.cli("message", "sent", draft_id)
        self.assertEqual(code, 0)
        self.assertIn("已登记", sent_out)

    def test_cannot_send_unapproved_draft(self):
        """未确认的草稿不能登记发送 —— 核心合规断言。"""
        _, out = self.cli(
            "message", "draft", "--job", "后端工程师", "--candidate", "张三"
        )
        draft_id = next(t.strip("(),:;") for t in out.split() if t.startswith("msg_"))

        with self.assertRaises(SystemExit) as ctx:
            self.cli("message", "sent", draft_id)
        self.assertIn("尚未人工确认", str(ctx.exception))

    def test_approve_unknown_draft_exits(self):
        with self.assertRaises(SystemExit):
            self.cli("message", "approve", "msg_不存在")

    def test_templates_command(self):
        code, out = self.cli("templates")
        self.assertEqual(code, 0)
        self.assertIn("default", out)
        self.assertIn("warm", out)


class TestReportAndExport(CliTestCase):
    def setUp(self):
        super().setUp()
        self.cli(
            "job", "add", "--title", "后端工程师",
            "--jd", "3年以上,本科,熟悉 Python、MySQL。",
        )
        csv = self.dir / "c.csv"
        csv.write_text(
            "姓名,年限,学历,技能,简历正文\n"
            "张三,6,硕士,Python|MySQL,精通Python MySQL\n"
            "李四,4,本科,Python,熟悉Python\n",
            encoding="utf-8",
        )
        self.cli("candidate", "import", str(csv))
        self.cli("match", "--job", "后端工程师")

    def test_report_empty_db(self):
        fresh = str(self.dir / "empty.db")
        code, out = run_cli("--db", fresh, "--rate-state", self.rate, "report")
        self.assertEqual(code, 0)
        self.assertIn("候选人总数", out)

    def test_report_with_data(self):
        code, out = self.cli("report")
        self.assertEqual(code, 0)
        self.assertIn("招聘日报", out)
        self.assertIn("招聘漏斗", out)
        self.assertIn("待接触", out)

    def test_report_company_name(self):
        _, out = self.cli("report", "--company", "某某科技")
        self.assertIn("某某科技", out)

    def test_report_shows_pending_drafts(self):
        self.cli("message", "draft", "--job", "后端工程师", "--candidate", "张三")
        _, out = self.cli("report")
        self.assertIn("待确认话术", out)

    def test_export_csv(self):
        out_file = self.dir / "export.csv"
        code, out = self.cli(
            "export", "--job", "后端工程师", "--out", str(out_file)
        )
        self.assertEqual(code, 0)
        self.assertTrue(out_file.exists())

        content = out_file.read_text(encoding="utf-8-sig")
        self.assertIn("姓名", content)
        self.assertIn("张三", content)
        self.assertIn("匹配分", content)

    def test_export_unknown_job_exits(self):
        with self.assertRaises(SystemExit):
            self.cli("export", "--job", "不存在", "--out", str(self.dir / "x.csv"))

    def test_export_empty_result(self):
        fresh = str(self.dir / "e2.db")
        run_cli("--db", fresh, "--rate-state", self.rate,
                "job", "add", "--title", "岗位", "--jd", "熟悉 Python")
        code, out = run_cli("--db", fresh, "--rate-state", self.rate,
                            "export", "--job", "岗位", "--out", str(self.dir / "y.csv"))
        self.assertEqual(code, 0)
        self.assertIn("没有可导出", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
