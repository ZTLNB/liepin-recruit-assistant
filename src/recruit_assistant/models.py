"""数据模型定义。

本模块只负责描述"数据长什么样",不包含任何持久化或业务逻辑,
方便单元测试直接构造对象。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


def _now() -> str:
    """统一的本地时间字符串(秒级精度,便于排序与展示)。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def new_id(prefix: str) -> str:
    """生成带前缀的短 ID,例如 ``job_3f2a1b9c``。"""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


class CandidateStatus(str, Enum):
    """候选人在招聘漏斗中的状态。"""

    NEW = "NEW"                 # 新入库,尚未接触
    CONTACTED = "CONTACTED"     # 已发送招呼,等待回复
    REPLIED = "REPLIED"         # 候选人已回复
    INTERVIEW = "INTERVIEW"     # 进入面试流程
    OFFER = "OFFER"             # 已发 offer
    HIRED = "HIRED"             # 已入职
    REJECTED = "REJECTED"       # 已淘汰 / 候选人拒绝
    ARCHIVED = "ARCHIVED"       # 归档(暂不跟进)

    @property
    def label(self) -> str:
        """中文显示名,用于报表与终端输出。"""
        return {
            "NEW": "待接触",
            "CONTACTED": "已打招呼",
            "REPLIED": "已回复",
            "INTERVIEW": "面试中",
            "OFFER": "已发 Offer",
            "HIRED": "已入职",
            "REJECTED": "已淘汰",
            "ARCHIVED": "已归档",
        }[self.value]

    @classmethod
    def from_str(cls, value: str) -> "CandidateStatus":
        """宽松解析状态字符串,大小写不敏感,也接受中文标签。"""
        text = (value or "").strip()
        upper = text.upper()
        if upper in cls.__members__:
            return cls[upper]
        for member in cls:
            if member.label == text:
                return member
        raise ValueError(f"无法识别的候选人状态:{value!r}")


# 招聘漏斗的正向顺序,用于报表里的转化率计算
FUNNEL_ORDER: list[CandidateStatus] = [
    CandidateStatus.NEW,
    CandidateStatus.CONTACTED,
    CandidateStatus.REPLIED,
    CandidateStatus.INTERVIEW,
    CandidateStatus.OFFER,
    CandidateStatus.HIRED,
]


@dataclass
class JobProfile:
    """岗位画像 —— 由岗位描述(JD)解析而来,是匹配打分的基准。"""

    title: str
    raw_jd: str = ""
    skills: list[str] = field(default_factory=list)        # 核心技能(必需)
    nice_to_have: list[str] = field(default_factory=list)  # 加分技能
    min_years: float = 0.0                                 # 经验年限下限
    max_years: float | None = None                         # 经验年限上限(可选)
    education: str = ""                                    # 学历要求
    keywords: list[str] = field(default_factory=list)      # 其他关键词
    id: str = field(default_factory=lambda: new_id("job"))
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "raw_jd": self.raw_jd,
            "skills": self.skills,
            "nice_to_have": self.nice_to_have,
            "min_years": self.min_years,
            "max_years": self.max_years,
            "education": self.education,
            "keywords": self.keywords,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "JobProfile":
        return cls(
            id=data.get("id") or new_id("job"),
            title=data.get("title", ""),
            raw_jd=data.get("raw_jd", ""),
            skills=list(data.get("skills") or []),
            nice_to_have=list(data.get("nice_to_have") or []),
            min_years=float(data.get("min_years") or 0.0),
            max_years=(float(data["max_years"]) if data.get("max_years") is not None else None),
            education=data.get("education", ""),
            keywords=list(data.get("keywords") or []),
            created_at=data.get("created_at") or _now(),
        )


@dataclass
class Candidate:
    """候选人档案。"""

    name: str
    resume_text: str = ""
    years: float = 0.0                                     # 工作年限
    education: str = ""                                    # 学历
    current_title: str = ""                                # 当前职位
    current_company: str = ""                              # 当前公司
    skills: list[str] = field(default_factory=list)        # 技能标签
    source: str = "manual"                                 # 来源渠道
    status: CandidateStatus = CandidateStatus.NEW
    note: str = ""                                         # 备注
    id: str = field(default_factory=lambda: new_id("cand"))
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "resume_text": self.resume_text,
            "years": self.years,
            "education": self.education,
            "current_title": self.current_title,
            "current_company": self.current_company,
            "skills": self.skills,
            "source": self.source,
            "status": self.status.value,
            "note": self.note,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Candidate":
        return cls(
            id=data.get("id") or new_id("cand"),
            name=data.get("name", ""),
            resume_text=data.get("resume_text", ""),
            years=float(data.get("years") or 0.0),
            education=data.get("education", ""),
            current_title=data.get("current_title", ""),
            current_company=data.get("current_company", ""),
            skills=list(data.get("skills") or []),
            source=data.get("source", "manual"),
            status=CandidateStatus.from_str(data.get("status", "NEW")),
            note=data.get("note", ""),
            created_at=data.get("created_at") or _now(),
            updated_at=data.get("updated_at") or _now(),
        )


@dataclass
class MatchResult:
    """一次「候选人 × 岗位」的匹配结果。"""

    candidate_id: str
    job_id: str
    score: float                                           # 0~100
    skill_hits: list[str] = field(default_factory=list)     # 命中的核心技能
    skill_misses: list[str] = field(default_factory=list)   # 缺失的核心技能
    bonus_hits: list[str] = field(default_factory=list)     # 命中的加分技能
    reasons: list[str] = field(default_factory=list)        # 人类可读的评分依据
    scored_at: str = field(default_factory=_now)

    @property
    def grade(self) -> str:
        """把分数映射成 A/B/C/D 档,方便快速筛。"""
        if self.score >= 85:
            return "A"
        if self.score >= 70:
            return "B"
        if self.score >= 55:
            return "C"
        return "D"

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "job_id": self.job_id,
            "score": round(self.score, 2),
            "grade": self.grade,
            "skill_hits": self.skill_hits,
            "skill_misses": self.skill_misses,
            "bonus_hits": self.bonus_hits,
            "reasons": self.reasons,
            "scored_at": self.scored_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MatchResult":
        return cls(
            candidate_id=data["candidate_id"],
            job_id=data["job_id"],
            score=float(data.get("score") or 0.0),
            skill_hits=list(data.get("skill_hits") or []),
            skill_misses=list(data.get("skill_misses") or []),
            bonus_hits=list(data.get("bonus_hits") or []),
            reasons=list(data.get("reasons") or []),
            scored_at=data.get("scored_at") or _now(),
        )


@dataclass
class MessageDraft:
    """待发送的招呼话术草稿。

    注意:本工具**不会**自动发送任何消息。草稿生成后必须由人工确认,
    确认动作通过 ``mark_sent`` 记录,仅用于台账追踪。
    """

    candidate_id: str
    job_id: str
    content: str
    template: str = "default"
    approved: bool = False                                 # 是否已人工确认
    sent_at: str | None = None
    id: str = field(default_factory=lambda: new_id("msg"))
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "candidate_id": self.candidate_id,
            "job_id": self.job_id,
            "content": self.content,
            "template": self.template,
            "approved": self.approved,
            "sent_at": self.sent_at,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MessageDraft":
        return cls(
            id=data.get("id") or new_id("msg"),
            candidate_id=data["candidate_id"],
            job_id=data["job_id"],
            content=data.get("content", ""),
            template=data.get("template", "default"),
            approved=bool(data.get("approved")),
            sent_at=data.get("sent_at"),
            created_at=data.get("created_at") or _now(),
        )
