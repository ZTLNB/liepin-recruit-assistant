"""岗位描述(JD)解析。

把一段自由文本的 JD 变成结构化的 ``JobProfile``,供匹配打分使用。

解析策略是"词典 + 规则",不依赖大模型 —— 好处是快、可离线、结果稳定可复现。
如果你的 JD 写法很特殊,直接编辑下面的 ``SKILL_ALIASES`` 词典即可。
"""

from __future__ import annotations

import re

from .models import JobProfile

# ---------------------------------------------------------------- 技能词典
# 结构:{规范显示名: [可识别的别名(小写)]}
# 别名匹配时按"长别名优先"处理,避免 "C" 误命中 "C++" 这类问题。
SKILL_ALIASES: dict[str, list[str]] = {
    # ---- 编程语言
    "Python": ["python"],
    "Java": ["java"],
    "Go": ["golang", "go语言", "go 语言", "go"],
    "C++": ["c++", "cpp"],
    "C#": ["c#", "csharp"],
    "JavaScript": ["javascript", "js"],
    "TypeScript": ["typescript", "ts"],
    "PHP": ["php"],
    "Ruby": ["ruby"],
    "Rust": ["rust"],
    "Kotlin": ["kotlin"],
    "Swift": ["swift"],
    "Scala": ["scala"],
    "SQL": ["sql"],
    # ---- 前端
    "React": ["react"],
    "Vue": ["vue", "vue.js", "vuejs"],
    "Angular": ["angular"],
    "Next.js": ["next.js", "nextjs"],
    "Webpack": ["webpack"],
    "Vite": ["vite"],
    "小程序": ["小程序", "微信小程序"],
    "Flutter": ["flutter"],
    "React Native": ["react native", "rn"],
    # ---- 后端框架
    "Spring": ["spring", "spring boot", "springboot"],
    "Django": ["django"],
    "Flask": ["flask"],
    "FastAPI": ["fastapi"],
    "Express": ["express"],
    "NestJS": ["nestjs", "nest.js"],
    "MyBatis": ["mybatis"],
    "gRPC": ["grpc"],
    "微服务": ["微服务", "microservice"],
    # ---- 数据库与存储
    "MySQL": ["mysql"],
    "PostgreSQL": ["postgresql", "postgres", "pg"],
    "MongoDB": ["mongodb", "mongo"],
    "Redis": ["redis"],
    "Oracle": ["oracle"],
    "Elasticsearch": ["elasticsearch", "es"],
    "ClickHouse": ["clickhouse"],
    "HBase": ["hbase"],
    # ---- 大数据
    "Hadoop": ["hadoop"],
    "Spark": ["spark"],
    "Flink": ["flink"],
    "Hive": ["hive"],
    "Kafka": ["kafka"],
    "数据仓库": ["数据仓库", "数仓", "data warehouse"],
    # ---- 云原生与运维
    "Docker": ["docker", "容器化"],
    "Kubernetes": ["kubernetes", "k8s"],
    "Jenkins": ["jenkins"],
    "CI/CD": ["ci/cd", "cicd", "持续集成"],
    "Linux": ["linux"],
    "AWS": ["aws"],
    "阿里云": ["阿里云", "aliyun"],
    "腾讯云": ["腾讯云"],
    # ---- 数据与算法
    "机器学习": ["机器学习", "machine learning", "ml"],
    "深度学习": ["深度学习", "deep learning", "dl"],
    "PyTorch": ["pytorch"],
    "TensorFlow": ["tensorflow", "tf"],
    "自然语言处理": ["自然语言处理", "nlp"],
    "计算机视觉": ["计算机视觉", "cv", "图像识别"],
    "大模型": ["大模型", "llm", "gpt", "aigc"],
    "推荐系统": ["推荐系统", "推荐算法"],
    "数据分析": ["数据分析", "data analysis"],
    "数据挖掘": ["数据挖掘", "data mining"],
    # ---- 产品与业务
    "产品设计": ["产品设计", "产品经理", "prd"],
    "项目管理": ["项目管理", "pmp", "敏捷开发", "scrum"],
    "用户增长": ["用户增长", "增长黑客", "growth"],
    "运营": ["运营", "活动运营", "内容运营", "用户运营"],
    "销售": ["销售", "大客户", "ka"],
    "商务谈判": ["商务谈判", "商务拓展", "bd"],
    "市场营销": ["市场营销", "品牌营销", "marketing"],
    "供应链": ["供应链", "采购"],
    "财务": ["财务", "会计", "cpa"],
    "人力资源": ["人力资源", "hr", "招聘"],
    # ---- 通用能力
    "英语": ["英语", "english", "英语流利"],
    "沟通能力": ["沟通能力", "沟通表达"],
    "团队协作": ["团队协作", "团队合作"],
    "抗压能力": ["抗压", "抗压能力"],
    "领导力": ["领导力", "带团队", "团队管理"],
}

# 反向索引:小写别名 -> 规范名。按别名长度降序排列,保证长别名优先匹配。
_ALIAS_INDEX: list[tuple[str, str]] = sorted(
    ((alias.lower(), canonical) for canonical, aliases in SKILL_ALIASES.items()
            for alias in aliases),
    key=lambda pair: len(pair[0]),
    reverse=True,
)

# 学历关键词,按含金量从高到低
EDUCATION_LEVELS: list[tuple[str, str]] = [
    ("博士", "博士"),
    ("硕士", "硕士"),
    ("研究生", "硕士"),
    ("本科", "本科"),
    ("学士", "本科"),
    ("统招", "本科"),
    ("大专", "大专"),
    ("专科", "大专"),
]

# 加分项引导词。
# 注意:中文 JD 里这类词通常是**后置**的(如"有大模型经验者优先"),
# 所以切分时以"句子"为单位归类,而不是按标记位置切前后。
BONUS_MARKERS = [
    "加分", "优先", "更佳", "更好", "额外",
    "nice to have", "best to have", "preferred", "plus",
]


def _find_skills(text: str) -> list[str]:
    """从文本中识别技能,保持词典顺序,已识别的长别名会被移除避免重复命中。"""
    lowered = text.lower()
    found: list[str] = []
    consumed_spans: list[tuple[int, int]] = []

    for alias, canonical in _ALIAS_INDEX:
        if canonical in found:
            continue
        start = lowered.find(alias)
        if start == -1:
            continue
        end = start + len(alias)
        # 跳过与已命中区间重叠的位置(长别名优先的体现)
        if any(not (end <= s or start >= e) for s, e in consumed_spans):
            continue
        # 英文/字母别名要求词边界,避免 "java" 命中 "javascript"
        if alias.isascii() and alias.isalpha():
            before = lowered[start - 1] if start > 0 else " "
            after = lowered[end] if end < len(lowered) else " "
            if before.isalnum() or after.isalnum():
                continue
        found.append(canonical)
        consumed_spans.append((start, end))

    return found


def _parse_years(text: str) -> tuple[float, float | None]:
    """解析经验年限要求,返回 (下限, 上限)。

    支持:"3年以上"、"3年及以上"、"3-5年"、"3~5年"、"3到5年"、"至少3年"。
    """
    # 先试区间:3-5年 / 3~5年 / 3到5年 / 3至5年
    range_match = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:-|~|～|—|到|至)\s*(\d+(?:\.\d+)?)\s*年", text
    )
    if range_match:
        lo = float(range_match.group(1))
        hi = float(range_match.group(2))
        return (min(lo, hi), max(lo, hi))

    # 前缀式下限:至少3年 / 不低于4年 / 最少2年 / 超过5年
    prefix_match = re.search(
        r"(?:至少|不低于|最少|多于|超过)\s*(\d+(?:\.\d+)?)\s*年", text
    )
    if prefix_match:
        return (float(prefix_match.group(1)), None)

    # 后缀式下限:3年以上 / 3年及以上 / 3年起
    suffix_match = re.search(
        r"(\d+(?:\.\d+)?)\s*年\s*(?:以上|及以上|起|或以上)", text
    )
    if suffix_match:
        return (float(suffix_match.group(1)), None)

    # 最后试"经验X年"这种平铺写法
    plain_match = re.search(r"(\d+(?:\.\d+)?)\s*年(?:以上)?(?:工作)?经验", text)
    if plain_match:
        return (float(plain_match.group(1)), None)

    return (0.0, None)


def _parse_education(text: str) -> str:
    """取 JD 里出现过的最高学历要求。"""
    for keyword, label in EDUCATION_LEVELS:
        if keyword in text:
            return label
    return ""


def _split_required_and_bonus(text: str) -> tuple[str, str]:
    """把 JD 切成"必需部分"和"加分部分"。

    按句子为单位归类:含加分引导词的句子整体归入加分部分。

    为什么不按标记位置切前后?因为中文 JD 的加分词普遍是后置的 ——
    "有大模型经验者优先" 里,加分内容是 "大模型",它在标记**前面**。
    按位置切会把加分技能错划成必需技能。

    代价是:同一句里混写的必需技能也会被归为加分。
    所以**建议把加分项单独成句**,这也符合 JD 的常见写法。

    返回 (必需文本, 加分文本)。
    """
    if not text:
        return "", ""

    # 按中英文句号、分号、换行、感叹号、问号切句
    sentences = re.split(r"[。;；\n\r!！?？]+", text)

    required_parts: list[str] = []
    bonus_parts: list[str] = []

    for sentence in sentences:
        stripped = sentence.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if any(marker.lower() in lowered for marker in BONUS_MARKERS):
            bonus_parts.append(stripped)
        else:
            required_parts.append(stripped)

    return "。".join(required_parts), "。".join(bonus_parts)


def parse_jd(title: str, raw_jd: str) -> JobProfile:
    """把岗位标题 + JD 正文解析成 ``JobProfile``。

    参数:
        title: 岗位名称,如 "高级后端工程师"
        raw_jd: JD 正文(可含换行)
    """
    required_text, bonus_text = _split_required_and_bonus(raw_jd)

    required_skills = _find_skills(required_text)
    bonus_skills = [s for s in _find_skills(bonus_text) if s not in required_skills]

    min_years, max_years = _parse_years(raw_jd)
    education = _parse_education(raw_jd)

    # 关键词:标题里的词 + 从 JD 里抓的常见要求词(用于宽松匹配)
    keywords: list[str] = []
    for token in re.split(r"[\s/、,，]+", title):
        token = token.strip()
        if token and len(token) >= 2 and token not in keywords:
            keywords.append(token)

    return JobProfile(
        title=title,
        raw_jd=raw_jd,
        skills=required_skills,
        nice_to_have=bonus_skills,
        min_years=min_years,
        max_years=max_years,
        education=education,
        keywords=keywords,
    )
