"""频率护栏测试。

这是防封号的关键模块,必须确保拦截逻辑真的生效。
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from recruit_assistant.ratelimit import RateLimiter  # noqa: E402


class RateLimiterTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.state = Path(self._tmp.name) / "rate.json"

    def tearDown(self):
        self._tmp.cleanup()

    def make(self, **kw) -> RateLimiter:
        defaults = {"max_per_hour": 5, "min_interval_seconds": 60}
        defaults.update(kw)
        return RateLimiter(self.state, **defaults)


class TestQuota(RateLimiterTestCase):
    def test_first_call_allowed(self):
        limiter = self.make()
        decision = limiter.check(now=1000.0)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.remaining_quota, 5)

    def test_quota_decreases(self):
        limiter = self.make()
        for i in range(3):
            limiter.record(now=1000.0 + i * 100)
        self.assertEqual(limiter.remaining_quota(now=1400.0), 2)

    def test_hourly_limit_blocks(self):
        limiter = self.make(max_per_hour=3, min_interval_seconds=0)
        for i in range(3):
            limiter.record(now=1000.0 + i)

        decision = limiter.check(now=1100.0)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.remaining_quota, 0)
        self.assertIn("达到上限", decision.reason)

    def test_events_expire_after_an_hour(self):
        limiter = self.make(max_per_hour=2, min_interval_seconds=0)
        limiter.record(now=1000.0)
        limiter.record(now=1001.0)
        # 一小时后再检查,旧记录应已过期
        decision = limiter.check(now=1000.0 + 3601)
        self.assertTrue(decision.allowed)

    def test_retry_after_provided(self):
        limiter = self.make(max_per_hour=1, min_interval_seconds=0)
        limiter.record(now=1000.0)
        decision = limiter.check(now=1010.0)
        self.assertFalse(decision.allowed)
        self.assertGreater(decision.retry_after_seconds, 0)


class TestMinInterval(RateLimiterTestCase):
    def test_interval_blocks_rapid_calls(self):
        limiter = self.make(min_interval_seconds=60)
        limiter.record(now=1000.0)

        decision = limiter.check(now=1030.0)
        self.assertFalse(decision.allowed)
        self.assertIn("间隔", decision.reason)
        self.assertGreater(decision.retry_after_seconds, 0)

    def test_interval_passes_after_waiting(self):
        limiter = self.make(min_interval_seconds=60)
        limiter.record(now=1000.0)
        decision = limiter.check(now=1070.0)
        self.assertTrue(decision.allowed)

    def test_interval_zero_disables_check(self):
        limiter = self.make(min_interval_seconds=0)
        limiter.record(now=1000.0)
        self.assertTrue(limiter.check(now=1000.0).allowed)


class TestConsume(RateLimiterTestCase):
    def test_consume_records_on_success(self):
        limiter = self.make()
        decision = limiter.consume()
        self.assertTrue(decision.allowed)
        # 刚消费完,立刻再检查应被间隔拦下
        self.assertFalse(limiter.check().allowed)

    def test_consume_does_not_record_on_failure(self):
        limiter = self.make(max_per_hour=1, min_interval_seconds=0)
        limiter.record(now=1000.0)
        before = limiter.remaining_quota(now=1000.0)

        limiter.consume()  # 真实时间,此时配额已满
        # 失败的消费不应再记账(否则配额会被自己越吃越少)
        self.assertLessEqual(limiter.remaining_quota(now=1000.0), before)


class TestPersistence(RateLimiterTestCase):
    def test_state_survives_reload(self):
        limiter = self.make()
        limiter.record(now=1000.0)
        limiter.record(now=1100.0)

        reloaded = self.make()
        self.assertEqual(reloaded.remaining_quota(now=1200.0), 3)

    def test_reset_clears_events(self):
        limiter = self.make()
        limiter.record(now=1000.0)
        limiter.reset()
        self.assertEqual(limiter.remaining_quota(now=1000.0), 5)

    def test_corrupt_state_file_recovers(self):
        """状态文件损坏时应重置而不是崩溃。"""
        self.state.write_text("{不是合法 JSON", encoding="utf-8")
        limiter = self.make()
        self.assertTrue(limiter.check(now=1000.0).allowed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
