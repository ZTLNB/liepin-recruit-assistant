"""招聘数据统计与日报。

把库里的候选人、匹配、消息汇总成一份可以直接贴进工作群的文本日报。
不依赖任何图表库,纯文本排版,复制到哪儿都不会乱。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .models import FUNNEL_ORDER, CandidateStatus
from .store import Store

# 漏斗里每个阶段的推进率基准(仅用于提示,不做强判断)
BAR_WIDTH = 24


def _bar(count: int, total: int, width: int = BAR_WIDTH) -> str:
    """用字符画一个简易占比条。"""
    if total <= 0:
        return ""
    filled = int(round(count / total * width))
    return "█" * filled + "·" * (width - filled)


def funnel_stats(store: Store) -> list[tuple[CandidateStatus, int]]:
    """按招聘漏斗顺序返回各阶段人数。"""
    counts = store.count_by_status()
    return [(status, counts.get(status.value, 0)) for status in FUNNEL_ORDER]


def stale_candidates(store: Store, days: int = 3) -> list:
    """找出"已打招呼但超过 N 天没有进展"的候选人,提醒跟进。"""
    cutoff = datetime.now() - timedelta(days=days)
    result = []
    for cand in store.list_candidates(status=CandidateStatus.CONTACTED):
        try:
            updated = datetime.strptime(cand.updated_at, "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            continue
        if updated < cutoff:
            result.append((cand, (datetime.now() - updated).days))
    return sorted(result, key=lambda pair: pair[1], reverse=True)


def job_summary(store: Store, top_n: int = 3) -> list[dict]:
    """每个岗位的候选池概况:匹配人数、平均分、最高分。"""
    summaries: list[dict] = []
    for job in store.list_jobs():
        matches = store.get_matches(job.id)
        if not matches:
            summaries.append({
                "job": job, "count": 0, "avg": 0.0, "best": 0.0, "top": [],
            })
            continue
        scores = [m.score for m in matches]
        top = matches[:top_n]
        summaries.append({
            "job": job,
            "count": len(matches),
            "avg": sum(scores) / len(scores),
            "best": max(scores),
            "top": top,
        })
    return sorted(summaries, key=lambda s: s["count"], reverse=True)


def build_report(store: Store, stale_days: int = 3, company: str = "") -> str:
    """生成完整日报文本。"""
    now = datetime.now()
    lines: list[str] = []

    header = f"招聘日报 · {now.strftime('%Y-%m-%d %H:%M')}"
    if company:
        header = f"{company} " + header
    lines.append("=" * 58)
    lines.append(f"  {header}")
    lines.append("=" * 58)

    # ---------------------------------------------------------- 总览
    all_cands = store.list_candidates()
    total = len(all_cands)
    lines.append("")
    lines.append(f"【候选人总数】{total}")

    if total == 0:
        lines.append("")
        lines.append("  暂无候选人数据。可先执行:")
        lines.append("    recruit candidate import <文件>")
        lines.append("=" * 58)
        return "\n".join(lines)

    # ---------------------------------------------------------- 漏斗
    lines.append("")
    lines.append("【招聘漏斗】")
    counts = store.count_by_status()
    for status, count in funnel_stats(store):
        label = status.label
        # 中文对齐:按显示宽度补空格
        pad = "　" * max(0, 5 - len(label))
        lines.append(f"  {label}{pad} {count:>4}  {_bar(count, total)}")

    # 不在正向漏斗里的状态单独列
    extra = [
        (s, counts.get(s.value, 0))
        for s in (CandidateStatus.REJECTED, CandidateStatus.ARCHIVED)
        if counts.get(s.value, 0)
    ]
    if extra:
        lines.append("")
        lines.append("  其他:")
        for status, count in extra:
            lines.append(f"    {status.label}: {count}")

    # ---------------------------------------------------------- 转化率
    reached = {
        "已接触": sum(counts.get(s.value, 0) for s in FUNNEL_ORDER[1:]),
        "已回复": sum(
            counts.get(s.value, 0) for s in FUNNEL_ORDER[2:]
        ),
        "进入面试": sum(
            counts.get(s.value, 0) for s in FUNNEL_ORDER[3:]
        ),
        "已入职": counts.get(CandidateStatus.HIRED.value, 0),
    }
    lines.append("")
    lines.append("【关键转化】")
    for label, value in reached.items():
        rate = (value / total * 100) if total else 0.0
        lines.append(f"  {label}: {value} 人({rate:.1f}%)")

    # ---------------------------------------------------------- 待跟进
    stale = stale_candidates(store, days=stale_days)
    lines.append("")
    if stale:
        lines.append(f"【待跟进提醒】已打招呼超过 {stale_days} 天未推进")
        for cand, days in stale[:8]:
            lines.append(f"  · {cand.name}({cand.current_title or '职位未填'})— 已 {days} 天")
        if len(stale) > 8:
            lines.append(f"  … 另有 {len(stale) - 8} 人")
    else:
        lines.append(f"【待跟进提醒】无 —— 没有超过 {stale_days} 天未推进的候选人")

    # ---------------------------------------------------------- 待确认草稿
    pending = store.list_drafts(only_pending=True)
    lines.append("")
    if pending:
        lines.append(f"【待确认话术】{len(pending)} 条草稿等待人工确认")
        for draft in pending[:5]:
            preview = draft.content[:36].replace("\n", " ")
            lines.append(f"  · [{draft.id}] {preview}…")
        if len(pending) > 5:
            lines.append(f"  … 另有 {len(pending) - 5} 条")
        lines.append("  确认后才会记为已发送:recruit message approve <草稿ID>")
    else:
        lines.append("【待确认话术】无积压")

    # ---------------------------------------------------------- 岗位
    summaries = job_summary(store)
    if summaries:
        lines.append("")
        lines.append("【岗位人才池】")
        for s in summaries[:6]:
            job = s["job"]
            if s["count"] == 0:
                lines.append(f"  {job.title}: 暂无匹配记录")
                continue
            lines.append(
                f"  {job.title}: {s['count']} 人"
                f"(均分 {s['avg']:.1f} · 最高 {s['best']:.1f})"
            )
            for m in s["top"]:
                cand = store.get_candidate(m.candidate_id)
                cname = cand.name if cand else m.candidate_id
                lines.append(f"      {m.grade} 档 {m.score:.1f}  {cname}")

    lines.append("")
    lines.append("=" * 58)
    return "\n".join(lines)
