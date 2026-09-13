"""手动导入适配器:从本地 CSV / JSON 文件读取候选人。

这是默认且唯一内置的数据来源。你从哪儿拿到这些数据(平台导出、
自己整理、招聘系统导出)由你决定,本工具只负责把它们规范化入库。
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from ..models import Candidate, CandidateStatus
from .base import CandidateSource

# 列名别名映射:把各种写法的表头归一到内部字段名
COLUMN_ALIASES: dict[str, str] = {
    # 姓名
    "name": "name", "姓名": "name", "候选人": "name", "名字": "name",
    # 年限
    "years": "years", "年限": "years", "工作年限": "years",
    "经验": "years", "工作经验": "years",
    # 学历
    "education": "education", "学历": "education", "最高学历": "education",
    # 职位
    "current_title": "current_title", "当前职位": "current_title",
    "职位": "current_title", "岗位": "current_title", "title": "current_title",
    # 公司
    "current_company": "current_company", "当前公司": "current_company",
    "公司": "current_company", "company": "current_company",
    # 技能
    "skills": "skills", "技能": "skills", "技能标签": "skills", "标签": "skills",
    # 简历正文
    "resume_text": "resume_text", "简历": "resume_text",
    "简历正文": "resume_text", "resume": "resume_text", "详情": "resume_text",
    # 来源
    "source": "source", "来源": "source", "渠道": "source",
    # 状态
    "status": "status", "状态": "status",
    # 备注
    "note": "note", "备注": "note",
}

# 技能字段内部的分隔符
SKILL_SEPARATORS = ["|", ";", "；", "、", ","]


def _normalize_header(raw: str) -> str | None:
    """把表头归一成内部字段名,无法识别返回 None。"""
    key = (raw or "").strip().lower().replace(" ", "").replace("_", "")
    for alias, field in COLUMN_ALIASES.items():
        if key == alias.lower().replace("_", ""):
            return field
    return None


def _split_skills(value: str) -> list[str]:
    """把技能字符串拆成列表,支持多种分隔符混用。"""
    if not value:
        return []
    parts = [value]
    for sep in SKILL_SEPARATORS:
        expanded: list[str] = []
        for chunk in parts:
            expanded.extend(chunk.split(sep))
        parts = expanded
    return [p.strip() for p in parts if p.strip()]


def _to_float(value, default: float = 0.0) -> float:
    """宽松转 float:容忍 '3年'、'3'、'' 等写法。"""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return default
    digits = ""
    for ch in text:
        if ch.isdigit() or ch == ".":
            digits += ch
        elif digits:
            break
    try:
        return float(digits) if digits else default
    except ValueError:
        return default


def _read_text(path: Path) -> str:
    """读文件,自动尝试 UTF-8 与 GBK(Windows 导出的 CSV 常见 GBK)。"""
    for encoding in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    # 兜底:忽略无法解码的字符,保证流程不中断
    return path.read_text(encoding="utf-8", errors="ignore")


def _row_to_candidate(row: dict) -> Candidate | None:
    """把一行归一化后的数据变成 Candidate,姓名为空则丢弃。"""
    name = str(row.get("name") or "").strip()
    if not name:
        return None

    status_raw = row.get("status")
    try:
        status = CandidateStatus.from_str(status_raw) if status_raw else CandidateStatus.NEW
    except ValueError:
        status = CandidateStatus.NEW

    return Candidate(
        name=name,
        years=_to_float(row.get("years")),
        education=str(row.get("education") or "").strip(),
        current_title=str(row.get("current_title") or "").strip(),
        current_company=str(row.get("current_company") or "").strip(),
        skills=_split_skills(str(row.get("skills") or "")),
        resume_text=str(row.get("resume_text") or "").strip(),
        source=str(row.get("source") or "manual").strip() or "manual",
        status=status,
        note=str(row.get("note") or "").strip(),
    )


class ManualImportSource(CandidateSource):
    """从本地 CSV / JSON 文件导入候选人。"""

    name = "manual"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> list[Candidate]:
        if not self.path.exists():
            raise FileNotFoundError(f"文件不存在:{self.path}")

        suffix = self.path.suffix.lower()
        if suffix == ".json":
            return self._load_json()
        if suffix in (".csv", ".txt", ".tsv"):
            return self._load_csv()
        raise ValueError(
            f"不支持的格式 {suffix!r},请使用 .csv 或 .json"
        )

    # ------------------------------------------------------------------ CSV

    def _load_csv(self) -> list[Candidate]:
        text = _read_text(self.path)
        # 嗅探分隔符(逗号 / 制表符)
        sample = text[:2048]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
        except csv.Error:
            dialect = csv.excel

        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        if not reader.fieldnames:
            return []

        # 表头归一化:原始表头 -> 内部字段名
        mapping = {
            original: _normalize_header(original)
            for original in reader.fieldnames
        }

        candidates: list[Candidate] = []
        for raw_row in reader:
            normalized: dict = {}
            for original, value in raw_row.items():
                field = mapping.get(original)
                if field:
                    normalized[field] = value
            cand = _row_to_candidate(normalized)
            if cand:
                candidates.append(cand)
        return candidates

    # ----------------------------------------------------------------- JSON

    def _load_json(self) -> list[Candidate]:
        text = _read_text(self.path)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON 解析失败:{exc}") from exc

        # 支持三种结构:[...] / {"candidates": [...]} / {"data": [...]}
        if isinstance(data, dict):
            for key in ("candidates", "data", "items", "list"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
            else:
                data = [data]

        if not isinstance(data, list):
            raise ValueError("JSON 顶层结构应为数组或含 candidates 字段的对象")

        candidates: list[Candidate] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            normalized: dict = {}
            for key, value in item.items():
                field = _normalize_header(key) or (
                    key if key in COLUMN_ALIASES.values() else None
                )
                if field:
                    normalized[field] = value
            # JSON 里 skills 可能是真正的数组
            skills_value = normalized.get("skills")
            if isinstance(skills_value, list):
                normalized["skills"] = "|".join(str(s) for s in skills_value)

            cand = _row_to_candidate(normalized)
            if cand:
                candidates.append(cand)
        return candidates
