"""频率控制 —— 本工具最重要的"防封号"护栏。

招聘平台的用户协议普遍禁止高频自动化操作。即使是人工确认后的动作,
单位时间内的操作密度过高依然会触发风控。本模块提供两道限制:

1. **滑动窗口配额**:每小时最多 N 次对外动作(默认 20)。
2. **最小间隔**:两次对外动作之间至少间隔 M 秒(默认 60)。

状态持久化到 JSON 文件,因为 CLI 每次调用都是独立进程,内存计数会失效。

⚠️ 这不是"绕过风控"的工具,而是反过来约束使用者别把账号玩废。
如果你觉得限制太紧,可以调大参数,但请自行评估账号风险。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

# 默认策略:偏保守。真实场景下 20 次/小时已经足够一名 HR 使用。
DEFAULT_MAX_PER_HOUR = 20
DEFAULT_MIN_INTERVAL_SECONDS = 60


@dataclass
class RateLimitDecision:
    """一次配额检查的结论。"""

    allowed: bool
    reason: str = ""
    retry_after_seconds: int = 0
    remaining_quota: int = 0


@dataclass
class RateLimiter:
    """基于本地文件的滑动窗口限流器。"""

    state_path: Path
    max_per_hour: int = DEFAULT_MAX_PER_HOUR
    min_interval_seconds: int = DEFAULT_MIN_INTERVAL_SECONDS
    _state: dict = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.state_path = Path(self.state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state = self._load()

    # ------------------------------------------------------------ 状态读写

    def _load(self) -> dict:
        if not self.state_path.exists():
            return {"events": []}
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or "events" not in data:
                return {"events": []}
            return data
        except (json.JSONDecodeError, OSError):
            # 文件损坏时重置,而不是让整个工具挂掉
            return {"events": []}

    def _save(self) -> None:
        self.state_path.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ------------------------------------------------------------ 核心逻辑

    def _recent_events(self, now: float) -> list[float]:
        """返回最近一小时内的事件时间戳。"""
        cutoff = now - 3600
        return [t for t in self._state.get("events", []) if t >= cutoff]

    def check(self, now: float | None = None) -> RateLimitDecision:
        """检查当前是否允许执行一次对外动作(**不消耗配额**)。"""
        now = time.time() if now is None else now
        recent = self._recent_events(now)

        # 先看最小间隔
        if recent:
            last = max(recent)
            elapsed = now - last
            if elapsed < self.min_interval_seconds:
                wait = int(self.min_interval_seconds - elapsed) + 1
                return RateLimitDecision(
                    allowed=False,
                    reason=(
                        f"距离上次操作仅 {int(elapsed)} 秒,"
                        f"需间隔至少 {self.min_interval_seconds} 秒"
                    ),
                    retry_after_seconds=wait,
                    remaining_quota=max(0, self.max_per_hour - len(recent)),
                )

        # 再看小时配额
        if len(recent) >= self.max_per_hour:
            oldest = min(recent)
            wait = int(oldest + 3600 - now) + 1
            return RateLimitDecision(
                allowed=False,
                reason=f"最近一小时已操作 {len(recent)} 次,达到上限 {self.max_per_hour} 次",
                retry_after_seconds=max(1, wait),
                remaining_quota=0,
            )

        return RateLimitDecision(
            allowed=True,
            reason="配额充足",
            retry_after_seconds=0,
            remaining_quota=self.max_per_hour - len(recent),
        )

    def record(self, now: float | None = None) -> None:
        """记录一次已发生的对外动作,消耗配额。"""
        now = time.time() if now is None else now
        events = self._recent_events(now)
        events.append(now)
        self._state["events"] = events
        self._save()

    def consume(self) -> RateLimitDecision:
        """检查并消耗:允许则记录,不允许则原样返回拒绝原因。

        这是推荐的使用方式 —— 一步完成"能不能发 + 记账"。
        """
        decision = self.check()
        if decision.allowed:
            self.record()
        return decision

    def remaining_quota(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        return max(0, self.max_per_hour - len(self._recent_events(now)))

    def reset(self) -> None:
        """清空历史记录(测试或人工重置时使用)。"""
        self._state = {"events": []}
        self._save()
