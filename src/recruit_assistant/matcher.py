"""候选人与岗位的匹配打分。

评分模型是**加权可解释**的 —— 每一项得分都会写进 ``reasons``,
HR 能看懂"为什么这个人 82 分",而不是面对一个黑盒数字。

权重分配(总计 100 分):

======================  ====  ==========================================
维度                    权重  说明
======================  ====  ==========================================
核心技能命中            50    岗位必需技能里,候选人覆盖了多少
经验年限符合度          20    低于下限扣分,远高于上限也扣分
加分技能                10    命中 nice_to_have 的比例
学历符合                10    达到要求得满分,低一档给一半
关键词重合              10    简历文本与岗位关键词的重合度
======================  ====  ==========================================

没有命中任何核心技能时,总分会被压到很低(技能项 0 分),
避免"什么都沾一点"的简历拿到虚高分。
"""

from __future__ import annotations

from .jd import SKILL_ALIASES
from .models import Candidate, JobProfile, MatchResult

# 各维度权重,集中在这里方便调整
WEIGHT_SKILL = 50.0
WEIGHT_EXPERIENCE = 20.0
WEIGHT_BONUS = 10.0
WEIGHT_EDUCATION = 10.0
WEIGHT_KEYWORD = 10.0

# 学历档次映射,用于比较高低
_EDUCATION_RANK = {"大专": 1, "本科": 2, "硕士": 3, "博士": 4}


def _normalize_skill(skill: str) -> str:
    """把技能写法归一到规范名(如 'vue.js' -> 'Vue')。"""
    key = skill.strip().lower()
    for canonical, aliases in SKILL_ALIASES.items():
        if key == canonical.lower() or key in [a.lower() for a in aliases]:
            return canonical
    return skill.strip()


def candidate_skill_set(candidate: Candidate) -> set[str]:
    """汇总候选人的技能:显式标签 + 从简历正文里识别出的技能。

    很多简历的技能是散落在正文里的,只看标签会漏掉一大半。
    """
    from .jd import _find_skills  # 复用同一套词典,保证口径一致

    skills = {_normalize_skill(s) for s in candidate.skills if s.strip()}
    if candidate.resume_text:
        skills.update(_find_skills(candidate.resume_text))
    return skills


def _score_skills(
    cand_skills: set[str], job: JobProfile
) -> tuple[float, list[str], list[str], list[str]]:
    """返回 (得分, 命中列表, 缺失列表, 说明)。"""
    if not job.skills:
        return WEIGHT_SKILL, [], [], ["岗位未指定必需技能,技能项给基础分"]

    hits = [s for s in job.skills if s in cand_skills]
    misses = [s for s in job.skills if s not in cand_skills]
    ratio = len(hits) / len(job.skills)
    score = ratio * WEIGHT_SKILL

    reasons = [f"核心技能命中 {len(hits)}/{len(job.skills)}({ratio:.0%})"]
    if misses:
        reasons.append("缺失:" + "、".join(misses[:6]))
    return score, hits, misses, reasons


def _score_experience(candidate: Candidate, job: JobProfile) -> tuple[float, list[str]]:
    """经验年限评分。低于下限线性扣分,超出上限每年扣一点(避免严重 over-qualified)。"""
    years = candidate.years
    reasons: list[str] = []

    if job.min_years <= 0 and job.max_years is None:
        return WEIGHT_EXPERIENCE, ["岗位未限定经验年限,经验项给满分"]

    lo = job.min_years
    hi = job.max_years

    if years < lo:
        # 差得越多扣得越狠,但不低于 0
        gap = lo - years
        penalty_ratio = min(1.0, gap / max(lo, 1.0))
        score = WEIGHT_EXPERIENCE * (1.0 - penalty_ratio)
        reasons.append(f"经验 {years:g} 年,低于要求下限 {lo:g} 年,扣分")
        return score, reasons

    if hi is not None and years > hi:
        over = years - hi
        penalty_ratio = min(0.6, over / max(hi, 1.0) * 0.5)
        score = WEIGHT_EXPERIENCE * (1.0 - penalty_ratio)
        reasons.append(f"经验 {years:g} 年,高于岗位上限 {hi:g} 年,可能资历过高")
        return score, reasons

    span = f"{lo:g}" if hi is None else f"{lo:g}-{hi:g}"
    reasons.append(f"经验 {years:g} 年,符合要求({span} 年)")
    return WEIGHT_EXPERIENCE, reasons


def _score_bonus(cand_skills: set[str], job: JobProfile) -> tuple[float, list[str], list[str]]:
    """加分技能评分。"""
    if not job.nice_to_have:
        return WEIGHT_BONUS, [], ["岗位未指定加分技能,该项给满分"]

    hits = [s for s in job.nice_to_have if s in cand_skills]
    ratio = len(hits) / len(job.nice_to_have)
    score = ratio * WEIGHT_BONUS
    reasons = [f"加分技能命中 {len(hits)}/{len(job.nice_to_have)}"]
    return score, hits, reasons


def _score_education(candidate: Candidate, job: JobProfile) -> tuple[float, list[str]]:
    """学历评分:达标满分,低一档给一半,低两档及以上为 0。"""
    if not job.education:
        return WEIGHT_EDUCATION, ["岗位未限定学历,该项给满分"]

    want = _EDUCATION_RANK.get(job.education)
    have = _EDUCATION_RANK.get(candidate.education)

    if want is None:
        return WEIGHT_EDUCATION, [f"岗位学历要求 '{job.education}' 无法识别,给满分"]
    if have is None:
        return WEIGHT_EDUCATION * 0.5, ["候选人学历未知,给一半分"]

    diff = want - have
    if diff <= 0:
        return WEIGHT_EDUCATION, [f"学历 {candidate.education} 满足要求({job.education})"]
    if diff == 1:
        return WEIGHT_EDUCATION * 0.5, [
            f"学历 {candidate.education} 低于要求({job.education}),给一半分"
        ]
    return 0.0, [f"学历 {candidate.education} 明显低于要求({job.education})"]


def _score_keywords(candidate: Candidate, job: JobProfile) -> tuple[float, list[str]]:
    """关键词重合度:岗位标题词与岗位自定义关键词在简历里的出现情况。"""
    terms = list(dict.fromkeys(job.keywords + job.skills + job.nice_to_have))
    if not terms:
        return WEIGHT_KEYWORD, ["无关键词可比对,该项给满分"]

    haystack = f"{candidate.resume_text} {candidate.current_title} {candidate.current_company}".lower()
    hits = [t for t in terms if t.lower() in haystack]
    ratio = len(hits) / len(terms)
    score = ratio * WEIGHT_KEYWORD
    return score, [f"关键词重合 {len(hits)}/{len(terms)}({ratio:.0%})"]


def score_candidate(candidate: Candidate, job: JobProfile) -> MatchResult:
    """给单个候选人在某岗位上打分。

    返回的 ``MatchResult`` 里包含总分、各维度明细和人类可读的评分依据。
    """
    cand_skills = candidate_skill_set(candidate)

    s_skill, hits, misses, r_skill = _score_skills(cand_skills, job)
    s_exp, r_exp = _score_experience(candidate, job)
    s_bonus, bonus_hits, r_bonus = _score_bonus(cand_skills, job)
    s_edu, r_edu = _score_education(candidate, job)
    s_kw, r_kw = _score_keywords(candidate, job)

    total = s_skill + s_exp + s_bonus + s_edu + s_kw

    reasons: list[str] = []
    reasons.extend(r_skill)
    reasons.extend(r_exp)
    reasons.extend(r_bonus)
    reasons.extend(r_edu)
    reasons.extend(r_kw)
    reasons.append(
        f"分项:技能 {s_skill:.0f}/{WEIGHT_SKILL:.0f} · "
        f"经验 {s_exp:.0f}/{WEIGHT_EXPERIENCE:.0f} · "
        f"加分 {s_bonus:.0f}/{WEIGHT_BONUS:.0f} · "
        f"学历 {s_edu:.0f}/{WEIGHT_EDUCATION:.0f} · "
        f"关键词 {s_kw:.0f}/{WEIGHT_KEYWORD:.0f}"
    )

    return MatchResult(
        candidate_id=candidate.id,
        job_id=job.id,
        score=round(total, 2),
        skill_hits=hits,
        skill_misses=misses,
        bonus_hits=bonus_hits,
        reasons=reasons,
    )


def rank_candidates(
    candidates: list[Candidate], job: JobProfile, min_score: float = 0.0
) -> list[MatchResult]:
    """批量打分并按分数降序返回(过滤掉低于 min_score 的)。"""
    results = [score_candidate(c, job) for c in candidates]
    return sorted(
        (r for r in results if r.score >= min_score),
        key=lambda r: r.score,
        reverse=True,
    )
