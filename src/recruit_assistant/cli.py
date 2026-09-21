"""命令行入口。

用法概览::

    recruit init                                  初始化数据目录
    recruit job add --title "后端工程师" --jd-file jd.txt
    recruit job list
    recruit candidate import candidates.csv
    recruit candidate list --status NEW
    recruit candidate status <候选人ID> CONTACTED
    recruit match --job <岗位ID> --min-score 60
    recruit match show --job <岗位ID>
    recruit message draft --job <岗位ID> --candidate <候选人ID>
    recruit message batch --job <岗位ID> --limit 5
    recruit message list --pending
    recruit message approve <草稿ID>
    recruit message sent <草稿ID>
    recruit report --stale-days 3
    recruit export --job <岗位ID> --out result.csv
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from pathlib import Path

from . import __version__
from .adapters import ManualImportSource
from .jd import parse_jd
from .matcher import rank_candidates, score_candidate
from .message import TEMPLATES, build_batch, build_message, list_templates
from .models import Candidate, CandidateStatus, JobProfile, MatchResult
from .ratelimit import RateLimiter
from .report import build_report
from .store import Store

DEFAULT_DB = Path.home() / ".recruit-assistant" / "recruit.db"
DEFAULT_RATE_STATE = Path.home() / ".recruit-assistant" / "rate_state.json"

STATUS_CHOICES = [s.name for s in CandidateStatus]


# ---------------------------------------------------------------- 工具函数


def _out(text: str = "") -> None:
    print(text)


def _resolve_job(store: Store, key: str) -> JobProfile | None:
    """按 ID 或标题查找岗位 —— 允许用户少打几个字符。"""
    job = store.get_job(key)
    if job:
        return job
    job = store.find_job_by_title(key)
    if job:
        return job
    # 退一步:标题模糊匹配(唯一命中才认)
    matches = [j for j in store.list_jobs() if key.lower() in j.title.lower()]
    return matches[0] if len(matches) == 1 else None


def _resolve_candidate(store: Store, key: str) -> Candidate | None:
    """按 ID 或姓名查找候选人。"""
    cand = store.get_candidate(key)
    if cand:
        return cand
    cand = store.find_candidate_by_name(key)
    if cand:
        return cand
    matches = [c for c in store.list_candidates() if key.lower() in c.name.lower()]
    return matches[0] if len(matches) == 1 else None


def _read_jd(args) -> str:
    """从 --jd 或 --jd-file 取 JD 正文。"""
    if getattr(args, "jd", None):
        return args.jd
    if getattr(args, "jd_file", None):
        path = Path(args.jd_file)
        if not path.exists():
            raise SystemExit(f"错误:JD 文件不存在 -> {path}")
        return path.read_text(encoding="utf-8", errors="ignore")
    return ""


# ---------------------------------------------------------------- 子命令实现


def cmd_init(args) -> int:
    db = Path(args.db)
    with Store(db) as store:
        _out(f"✅ 数据目录已就绪:{db}")
        _out(f"   当前岗位 {len(store.list_jobs())} 个,候选人 {len(store.list_candidates())} 人")
    rate = RateLimiter(Path(args.rate_state))
    _out(f"   频率护栏状态:{rate.state_path}")
    _out("")
    _out("提示:本工具不会自动向候选人发送任何消息。")
    _out("     所有话术都需人工确认后才记为已发送。")
    return 0


def cmd_job_add(args) -> int:
    jd_text = _read_jd(args)
    if not jd_text:
        raise SystemExit("错误:请通过 --jd 或 --jd-file 提供岗位描述")

    job = parse_jd(args.title, jd_text)
    with Store(args.db) as store:
        store.add_job(job)

    _out(f"✅ 岗位已创建:{job.title}")
    _out(f"   ID:{job.id}")
    _out(f"   必需技能:{'、'.join(job.skills) or '(未识别到)'}")
    if job.nice_to_have:
        _out(f"   加分技能:{'、'.join(job.nice_to_have)}")
    _out(f"   经验要求:{job.min_years:g} 年起" + (f" ~ {job.max_years:g} 年" if job.max_years else ""))
    _out(f"   学历要求:{job.education or '(未限定)'}")
    return 0


def cmd_job_list(args) -> int:
    with Store(args.db) as store:
        jobs = store.list_jobs()
    if not jobs:
        _out("暂无岗位。用 `recruit job add` 创建一个。")
        return 0

    _out(f"{'ID':<16} {'岗位':<20} {'技能数':>6} {'年限':>8}")
    _out("-" * 56)
    for job in jobs:
        years = f"{job.min_years:g}+" if job.max_years is None else f"{job.min_years:g}-{job.max_years:g}"
        _out(f"{job.id:<16} {job.title:<20} {len(job.skills):>6} {years:>8}")
    return 0


def cmd_candidate_import(args) -> int:
    source = ManualImportSource(args.file)
    try:
        candidates = source.load()
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"错误:{exc}") from exc

    if not candidates:
        _out("⚠️ 未解析出任何候选人,请检查文件表头与内容。")
        return 1

    with Store(args.db) as store:
        for cand in candidates:
            store.add_candidate(cand)
        total = len(store.list_candidates())

    _out(f"✅ 已导入 {len(candidates)} 名候选人(库中现有 {total} 人)")
    for cand in candidates[:5]:
        _out(f"   · {cand.name}({cand.current_title or '职位未填'},{cand.years:g} 年)")
    if len(candidates) > 5:
        _out(f"   … 另有 {len(candidates) - 5} 人")
    return 0


def cmd_candidate_list(args) -> int:
    status = CandidateStatus.from_str(args.status) if args.status else None
    with Store(args.db) as store:
        candidates = store.list_candidates(status=status, limit=args.limit)

    if not candidates:
        _out("没有符合条件的候选人。")
        return 0

    _out(f"{'ID':<16} {'姓名':<10} {'状态':<10} {'年限':>5} {'当前职位':<18}")
    _out("-" * 66)
    for cand in candidates:
        _out(
            f"{cand.id:<16} {cand.name:<10} {cand.status.label:<10} "
            f"{cand.years:>5g} {cand.current_title[:16]:<18}"
        )
    _out("")
    _out(f"共 {len(candidates)} 人")
    return 0


def cmd_candidate_status(args) -> int:
    try:
        status = CandidateStatus.from_str(args.status)
    except ValueError as exc:
        raise SystemExit(f"错误:{exc}") from exc

    with Store(args.db) as store:
        cand = _resolve_candidate(store, args.candidate)
        if not cand:
            raise SystemExit(f"错误:找不到候选人 {args.candidate!r}")
        store.update_status(cand.id, status)

    _out(f"✅ {cand.name} 的状态已更新为「{status.label}」")
    return 0


def cmd_match_run(args) -> int:
    with Store(args.db) as store:
        job = _resolve_job(store, args.job)
        if not job:
            raise SystemExit(f"错误:找不到岗位 {args.job!r}")

        candidates = store.list_candidates()
        if not candidates:
            raise SystemExit("错误:库里还没有候选人,请先导入。")

        results = rank_candidates(candidates, job, min_score=args.min_score)
        for result in results:
            store.save_match(result)

        _out(f"✅ 已完成匹配:{len(candidates)} 名候选人 × 「{job.title}」")
        _out(f"   达到 {args.min_score:g} 分的有 {len(results)} 人")
        _out("")
        if not results:
            return 0

        _out(f"{'档':<3} {'分数':>6}  {'姓名':<10} 命中技能")
        _out("-" * 60)
        for result in results[: args.limit]:
            cand = store.get_candidate(result.candidate_id)
            name = cand.name if cand else result.candidate_id
            hits = "、".join(result.skill_hits[:4]) or "(无)"
            _out(f"{result.grade:<3} {result.score:>6.1f}  {name:<10} {hits}")
        if len(results) > args.limit:
            _out(f"… 另有 {len(results) - args.limit} 人,用 `recruit match show` 查看全部")
    return 0


def cmd_match_show(args) -> int:
    with Store(args.db) as store:
        job = _resolve_job(store, args.job)
        if not job:
            raise SystemExit(f"错误:找不到岗位 {args.job!r}")
        results = store.get_matches(job.id, min_score=args.min_score)
        if not results:
            _out("暂无匹配记录,先运行 `recruit match --job ...`。")
            return 0
        # 一次性把候选人姓名查出来,避免在循环里反复开关数据库连接
        names = {}
        for result in results:
            cand = store.get_candidate(result.candidate_id)
            names[result.candidate_id] = cand.name if cand else result.candidate_id

    _out(f"「{job.title}」匹配详情({len(results)} 人)")
    _out("=" * 60)
    for result in results:
        _out("")
        _out(f"[{result.grade}] {result.score:.1f} 分 — {names[result.candidate_id]}")
        if args.verbose:
            for reason in result.reasons:
                _out(f"     · {reason}")
    return 0


def cmd_match_dispatch(args) -> int:
    """``match`` 的位置参数决定走"执行打分"还是"查看结果"。"""
    if args.action == "show":
        return cmd_match_show(args)
    return cmd_match_run(args)


def cmd_message_draft(args) -> int:
    with Store(args.db) as store:
        job = _resolve_job(store, args.job)
        if not job:
            raise SystemExit(f"错误:找不到岗位 {args.job!r}")
        cand = _resolve_candidate(store, args.candidate)
        if not cand:
            raise SystemExit(f"错误:找不到候选人 {args.candidate!r}")

        match = store.get_match(cand.id, job.id)
        if match is None:
            match = score_candidate(cand, job)

        try:
            draft = build_message(
                candidate=cand, job=job, match=match,
                template=args.template, company=args.company,
            )
        except ValueError as exc:
            raise SystemExit(f"错误:{exc}") from exc

        store.save_draft(draft)

    _out(f"📝 话术草稿已生成(未发送)· 草稿ID {draft.id}")
    _out(f"   候选人:{cand.name}  岗位:{job.title}  模板:{draft.template}")
    _out("-" * 60)
    _out(draft.content)
    _out("-" * 60)
    _out("")
    _out("⚠️ 草稿尚未发送。确认内容无误后执行:")
    _out(f"     recruit message approve {draft.id}")
    return 0


def cmd_message_batch(args) -> int:
    with Store(args.db) as store:
        job = _resolve_job(store, args.job)
        if not job:
            raise SystemExit(f"错误:找不到岗位 {args.job!r}")

        matches = store.get_matches(job.id, min_score=args.min_score)
        if not matches:
            raise SystemExit("错误:没有匹配记录,请先运行 `recruit match`。")

        pairs: list[tuple[Candidate, MatchResult]] = []
        for match in matches[: args.limit]:
            cand = store.get_candidate(match.candidate_id)
            if cand:
                pairs.append((cand, match))

        drafts = build_batch(
            pairs, job=job, template=args.template, company=args.company,
            limit=args.limit,
        )
        for draft in drafts:
            store.save_draft(draft)

    _out(f"📝 已生成 {len(drafts)} 条草稿(全部待人工确认)")
    _out("")
    for draft in drafts:
        _out(f"[{draft.id}] {draft.content[:50]}…")
    _out("")
    _out("⚠️ 这些草稿都不会自动发出。逐条确认请用:")
    _out("     recruit message list --pending")
    _out("     recruit message approve <草稿ID>")
    return 0


def cmd_message_list(args) -> int:
    with Store(args.db) as store:
        drafts = store.list_drafts(only_pending=args.pending)

    if not drafts:
        _out("没有待确认的草稿。" if args.pending else "暂无草稿记录。")
        return 0

    _out(f"{'草稿ID':<16} {'确认':<5} {'发送':<6} 内容摘要")
    _out("-" * 70)
    for draft in drafts:
        approved = "✅" if draft.approved else "⬜"
        sent = draft.sent_at[:10] if draft.sent_at else "—"
        preview = draft.content[:30].replace("\n", " ")
        _out(f"{draft.id:<16} {approved:<5} {sent:<6} {preview}…")
    _out("")
    _out(f"共 {len(drafts)} 条")
    return 0


def cmd_message_approve(args) -> int:
    with Store(args.db) as store:
        draft = store.get_draft(args.draft)
        if not draft:
            raise SystemExit(f"错误:找不到草稿 {args.draft!r}")
        _out("内容如下:")
        _out("-" * 60)
        _out(draft.content)
        _out("-" * 60)
        store.approve_draft(draft.id)

    _out(f"✅ 草稿 {draft.id} 已确认,可以发送了。")
    _out("")
    _out("请到猎聘客户端**手动**把上面这段话发给候选人。")
    _out("发送完成后,执行以下命令登记:")
    _out(f"     recruit message sent {draft.id}")
    return 0


def cmd_message_sent(args) -> int:
    with Store(args.db) as store:
        draft = store.get_draft(args.draft)
        if not draft:
            raise SystemExit(f"错误:找不到草稿 {args.draft!r}")
        if not draft.approved:
            raise SystemExit(
                "错误:该草稿尚未人工确认,不能登记为已发送。\n"
                f"     请先执行:recruit message approve {draft.id}"
            )

        # 频率护栏:登记发送动作也要记账,防止密集操作
        rate = RateLimiter(Path(args.rate_state))
        decision = rate.check()
        if not decision.allowed:
            _out(f"⛔ 频率护栏拦截:{decision.reason}")
            _out(f"   请等待约 {decision.retry_after_seconds} 秒后重试。")
            _out("   这是为了降低账号被平台风控的风险。")
            return 2

        ok = store.mark_sent(draft.id)
        if ok:
            rate.record()
            # 同步把候选人状态推进到"已打招呼"
            store.update_status(draft.candidate_id, CandidateStatus.CONTACTED)

    _out(f"✅ 已登记:草稿 {draft.id} 标记为已发送")
    _out(f"   剩余本小时配额:{decision.remaining_quota} 次")
    return 0


def cmd_report(args) -> int:
    with Store(args.db) as store:
        text = build_report(store, stale_days=args.stale_days, company=args.company)
    _out(text)
    return 0


def cmd_export(args) -> int:
    with Store(args.db) as store:
        job = _resolve_job(store, args.job)
        if not job:
            raise SystemExit(f"错误:找不到岗位 {args.job!r}")
        matches = store.get_matches(job.id, min_score=args.min_score)

        rows = []
        for match in matches:
            cand = store.get_candidate(match.candidate_id)
            if not cand:
                continue
            rows.append({
                "候选人ID": cand.id,
                "姓名": cand.name,
                "档位": match.grade,
                "匹配分": f"{match.score:.1f}",
                "当前职位": cand.current_title,
                "当前公司": cand.current_company,
                "年限": f"{cand.years:g}",
                "学历": cand.education,
                "命中技能": "|".join(match.skill_hits),
                "缺失技能": "|".join(match.skill_misses),
                "状态": cand.status.label,
            })

    if not rows:
        _out("没有可导出的数据。")
        return 0

    out_path = Path(args.out)
    # Windows 下 Excel 打开 UTF-8 CSV 会乱码,加 BOM 解决
    with out_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    _out(f"✅ 已导出 {len(rows)} 条到 {out_path}")
    return 0


def cmd_templates(args) -> int:
    _out("内置话术模板:")
    for name, tpl in list_templates().items():
        _out("")
        _out(f"[{name}]")
        _out(f"  {tpl}")
    return 0


# ---------------------------------------------------------------- 参数定义


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="recruit",
        description="猎聘招聘助手 —— 半自动化招聘流水线(所有对外发送均需人工确认)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  recruit init\n"
            '  recruit job add --title "后端工程师" --jd-file jd.txt\n'
            "  recruit candidate import candidates.csv\n"
            "  recruit match --job 后端工程师 --min-score 60\n"
            "  recruit report\n"
        ),
    )
    parser.add_argument("--db", default=str(DEFAULT_DB), help="数据库文件路径")
    parser.add_argument(
        "--rate-state", default=str(DEFAULT_RATE_STATE), help="频率护栏状态文件路径"
    )
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")

    sub = parser.add_subparsers(dest="command", metavar="<命令>")

    # init
    p = sub.add_parser("init", help="初始化数据目录")
    p.set_defaults(func=cmd_init)

    # job
    job_p = sub.add_parser("job", help="岗位管理")
    job_sub = job_p.add_subparsers(dest="job_command", metavar="<子命令>")

    p = job_sub.add_parser("add", help="新增岗位(自动解析 JD)")
    p.add_argument("--title", required=True, help="岗位名称")
    p.add_argument("--jd", help="JD 正文(直接传字符串)")
    p.add_argument("--jd-file", dest="jd_file", help="JD 文件路径")
    p.set_defaults(func=cmd_job_add)

    p = job_sub.add_parser("list", help="列出所有岗位")
    p.set_defaults(func=cmd_job_list)

    # candidate
    cand_p = sub.add_parser("candidate", help="候选人管理")
    cand_sub = cand_p.add_subparsers(dest="candidate_command", metavar="<子命令>")

    p = cand_sub.add_parser("import", help="从 CSV/JSON 批量导入")
    p.add_argument("file", help="文件路径(.csv 或 .json)")
    p.set_defaults(func=cmd_candidate_import)

    p = cand_sub.add_parser("list", help="列出候选人")
    p.add_argument("--status", choices=STATUS_CHOICES, help="按状态筛选")
    p.add_argument("--limit", type=int, default=50, help="最多显示条数")
    p.set_defaults(func=cmd_candidate_list)

    p = cand_sub.add_parser("status", help="更新候选人状态")
    p.add_argument("candidate", help="候选人 ID 或姓名")
    p.add_argument("status", help=f"新状态,可选:{', '.join(STATUS_CHOICES)}")
    p.set_defaults(func=cmd_candidate_status)

    # match —— 用位置参数区分动作,这样 `recruit match --job X` 可以直接用
    p = sub.add_parser("match", help="匹配打分(默认执行打分)")
    p.add_argument(
        "action", nargs="?", default="run", choices=["run", "show"],
        help="run=执行打分(默认) / show=查看已有结果",
    )
    p.add_argument("--job", required=True, help="岗位 ID 或标题")
    p.add_argument("--min-score", dest="min_score", type=float, default=0.0, help="最低分过滤")
    p.add_argument("--limit", type=int, default=20, help="最多显示条数(run 时有效)")
    p.add_argument("--verbose", action="store_true", help="显示详细评分依据(show 时有效)")
    p.set_defaults(func=cmd_match_dispatch)

    # message
    msg_p = sub.add_parser("message", help="招呼话术(草稿需人工确认)")
    msg_sub = msg_p.add_subparsers(dest="message_command", metavar="<子命令>")

    p = msg_sub.add_parser("draft", help="为单个候选人生成话术草稿")
    p.add_argument("--job", required=True, help="岗位 ID 或标题")
    p.add_argument("--candidate", required=True, help="候选人 ID 或姓名")
    p.add_argument("--template", default="default", choices=sorted(TEMPLATES), help="话术模板")
    p.add_argument("--company", default="我们公司", help="公司名")
    p.set_defaults(func=cmd_message_draft)

    p = msg_sub.add_parser("batch", help="按匹配分批量生成草稿")
    p.add_argument("--job", required=True, help="岗位 ID 或标题")
    p.add_argument("--limit", type=int, default=5, help="生成条数上限")
    p.add_argument("--min-score", dest="min_score", type=float, default=60.0)
    p.add_argument("--template", default="default", choices=sorted(TEMPLATES))
    p.add_argument("--company", default="我们公司", help="公司名")
    p.set_defaults(func=cmd_message_batch)

    p = msg_sub.add_parser("list", help="列出草稿")
    p.add_argument("--pending", action="store_true", help="只看待确认的")
    p.set_defaults(func=cmd_message_list)

    p = msg_sub.add_parser("approve", help="人工确认草稿")
    p.add_argument("draft", help="草稿 ID")
    p.set_defaults(func=cmd_message_approve)

    p = msg_sub.add_parser("sent", help="登记为已发送(需先确认)")
    p.add_argument("draft", help="草稿 ID")
    p.set_defaults(func=cmd_message_sent)

    # report
    p = sub.add_parser("report", help="生成招聘日报")
    p.add_argument("--stale-days", dest="stale_days", type=int, default=3, help="几天未推进算超期")
    p.add_argument("--company", default="", help="公司名(显示在标题)")
    p.set_defaults(func=cmd_report)

    # export
    p = sub.add_parser("export", help="导出匹配结果为 CSV")
    p.add_argument("--job", required=True, help="岗位 ID 或标题")
    p.add_argument("--out", required=True, help="输出文件路径")
    p.add_argument("--min-score", dest="min_score", type=float, default=0.0)
    p.set_defaults(func=cmd_export)

    # templates
    p = sub.add_parser("templates", help="查看内置话术模板")
    p.set_defaults(func=cmd_templates)

    return parser


def _make_output_resilient() -> None:
    """别让控制台编码决定命令能不能跑完。

    这个 CLI 的界面全是中文。Windows 上 stdout/stderr 一旦不是控制台
    (被管道或文件接管),Python 用的就是 locale 编码而不是宽字符 API;
    英文 Windows 的 locale 是 cp1252,一打中文就 UnicodeEncodeError。

    最直接的受害者是 ``recruit --help``:argparse 把帮助文本写 stdout,
    在英文 Windows 上(以及任何 ``recruit --help | more`` 的场景)直接崩。
    用户拿到工具的第一个命令就失败,而且报的是编码栈,看不出跟工具有关。

    这里只把错误处理换成 replace,保留控制台原有编码:编不出来的字符退化成
    ?,而不是让整个程序失败。强制改成 UTF-8 会更糟 —— 中文 Windows 的
    cp936 控制台会显示乱码。
    """
    for stream in (sys.stdout, sys.stderr):
        # 用 isinstance 而不是 hasattr:sys.stdout 的静态类型是 TextIO | Any,
        # 直接调 reconfigure 会被类型检查器判成 union-attr;而测试里被替换成
        # StringIO 的流本来也不该有这个方法,跳过才是对的。
        if isinstance(stream, io.TextIOWrapper):
            try:
                stream.reconfigure(errors="replace")
            except (ValueError, OSError):  # 流已关闭或已分离
                pass


def main(argv: list[str] | None = None) -> int:
    _make_output_resilient()
    parser = build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "command", None):
        parser.print_help()
        return 0

    # 子命令里再嵌套一层的情况(job add / candidate list 等)
    if getattr(args, "command", None) in ("job", "candidate", "message"):
        sub_attr = f"{args.command}_command"
        if not getattr(args, sub_attr, None):
            # 没给二级命令时,默认走最常用的那个
            defaults = {
                "job": ("job_command", "list", cmd_job_list),
                "candidate": ("candidate_command", "list", cmd_candidate_list),
                "message": ("message_command", "list", cmd_message_list),
            }
            attr, value, func = defaults[args.command]
            setattr(args, attr, value)
            args.func = func

    if not hasattr(args, "func"):
        parser.print_help()
        return 0

    try:
        return args.func(args)
    except SystemExit:
        raise
    except BrokenPipeError:  # 输出被 head 等截断时静默退出
        return 0
    except KeyboardInterrupt:
        _out("\n已中断。")
        return 130


if __name__ == "__main__":
    sys.exit(main())
