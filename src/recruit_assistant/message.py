"""打招呼话术生成。

设计立场:**生成草稿,不代发消息。**

所有话术都产出为 ``MessageDraft``,``approved`` 默认为 False。
只有人工看过、确认没问题,才通过 ``store.approve_draft`` 放行。
这样既省了 HR 逐字敲的功夫,又保留了"发出前必须有人把关"的责任边界。

话术原则(写在模板里,也是给使用者的提醒):
- 简短 —— 没人愿意读三屏的招聘私信
- 具体 —— 提到候选人的实际技能,而不是复制粘贴
- 留退路 —— 给对方"不感兴趣"的出口,这是基本的职业礼貌
"""

from __future__ import annotations

from .matcher import candidate_skill_set
from .models import Candidate, JobProfile, MatchResult, MessageDraft

# ---------------------------------------------------------------- 内置模板
# 占位符:{name} {title} {company} {skills} {years} {education}
TEMPLATES: dict[str, str] = {
    "default": (
        "{name}您好,我是{company}的招聘负责人。"
        "我们正在招聘{title},看到您在{skills}方面有{years}年经验,"
        "感觉和岗位比较匹配。"
        "方便的话想和您简单沟通一下,也欢迎您先了解岗位详情。"
        "如果暂无换工作的打算,打扰了。"
    ),
    "warm": (
        "{name}您好呀,冒昧打扰~ "
        "我们在招{title},看了您的经历,{skills}这块正是团队在找的方向。"
        "想问问您近期有没有看新机会的想法?有的话我把岗位详情发给您看看,"
        "没有的话也完全理解,祝您工作顺利!"
    ),
    "direct": (
        "{name}你好,{company}在招{title}。"
        "你的{skills}经验匹配度较高。"
        "方便聊聊吗?"
    ),
    "senior": (
        "{name}您好。{company}目前在组建团队,招聘{title}。"
        "注意到您在{skills}方向有{years}年的积累,这与我们的需求高度契合。"
        "如果您对新的机会持开放态度,希望有机会和您深入交流;"
        "若暂时不考虑,也请不必回复,祝好。"
    ),
}


def _format_skills(hits: list[str], fallback: str = "相关技术", limit: int = 2) -> str:
    """把命中技能拼成可读短语,最多取 limit 个。"""
    picked = [s for s in hits if s][:limit]
    if not picked:
        return fallback
    if len(picked) == 1:
        return picked[0]
    return "、".join(picked)


def _format_years(years: float) -> str:
    """年限格式化:整数不带小数点,如 3 而不是 3.0。"""
    if years <= 0:
        return "相关"
    return f"{years:g}"


def build_message(
    candidate: Candidate,
    job: JobProfile,
    match: MatchResult | None = None,
    template: str = "default",
    company: str = "我们公司",
    custom_template: str | None = None,
) -> MessageDraft:
    """生成一条打招呼草稿(**不会发送**)。

    参数:
        candidate: 候选人
        job:       目标岗位
        match:     匹配结果,用于挑出最相关的技能作为话术亮点;可为 None
        template:  模板名,取值见 ``TEMPLATES``
        company:   公司名,用于话术开头
        custom_template: 自定义模板字符串,给定时覆盖 ``template``
    """
    tpl = custom_template if custom_template is not None else TEMPLATES.get(template)
    if tpl is None:
        raise ValueError(
            f"未知模板 {template!r},可选:{', '.join(sorted(TEMPLATES))}"
        )

    # 优先用匹配命中的技能;没有匹配结果时退回候选人自己的技能标签
    hits = list(match.skill_hits) if match else []
    if not hits:
        hits = [s for s in candidate.skills if s][:2]
    if not hits:
        hits = sorted(candidate_skill_set(candidate))[:2]

    content = tpl.format(
        name=candidate.name or "你好",
        title=job.title or "相关岗位",
        company=company,
        skills=_format_skills(hits),
        years=_format_years(candidate.years),
        education=candidate.education or "相关专业",
    )

    return MessageDraft(
        candidate_id=candidate.id,
        job_id=job.id,
        content=content.strip(),
        template=template if custom_template is None else "custom",
        approved=False,          # 强制人工确认
    )


def build_batch(
    pairs: list[tuple[Candidate, MatchResult]],
    job: JobProfile,
    template: str = "default",
    company: str = "我们公司",
    limit: int = 10,
) -> list[MessageDraft]:
    """批量生成草稿(按匹配分从高到低,默认最多 10 条)。

    注意:批量生成的草稿**全部**处于未确认状态,仍需逐条人工过目。
    """
    drafts: list[MessageDraft] = []
    for candidate, match in pairs[:limit]:
        drafts.append(
            build_message(
                candidate=candidate,
                job=job,
                match=match,
                template=template,
                company=company,
            )
        )
    return drafts


def list_templates() -> dict[str, str]:
    """返回所有内置模板,便于 CLI 展示。"""
    return dict(TEMPLATES)
