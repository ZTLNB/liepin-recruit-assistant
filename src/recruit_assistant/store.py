"""SQLite 持久化层。

所有数据都存在本地单个 .db 文件里 —— 候选人简历属于个人信息,
本工具坚持"数据不出本机"的原则,不引入任何远程存储。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import (
    Candidate,
    CandidateStatus,
    JobProfile,
    MatchResult,
    MessageDraft,
    _now,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    raw_jd      TEXT,
    skills      TEXT,          -- JSON 数组
    nice_to_have TEXT,         -- JSON 数组
    min_years   REAL,
    max_years   REAL,
    education   TEXT,
    keywords    TEXT,          -- JSON 数组
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS candidates (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    resume_text     TEXT,
    years           REAL,
    education       TEXT,
    current_title   TEXT,
    current_company TEXT,
    skills          TEXT,      -- JSON 数组
    source          TEXT,
    status          TEXT,
    note            TEXT,
    created_at      TEXT,
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS matches (
    candidate_id TEXT NOT NULL,
    job_id       TEXT NOT NULL,
    score        REAL,
    skill_hits   TEXT,         -- JSON 数组
    skill_misses TEXT,         -- JSON 数组
    bonus_hits   TEXT,         -- JSON 数组
    reasons      TEXT,         -- JSON 数组
    scored_at    TEXT,
    PRIMARY KEY (candidate_id, job_id)
);

CREATE TABLE IF NOT EXISTS messages (
    id           TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    job_id       TEXT NOT NULL,
    content      TEXT,
    template     TEXT,
    approved     INTEGER DEFAULT 0,
    sent_at      TEXT,
    created_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_candidates_status ON candidates(status);
CREATE INDEX IF NOT EXISTS idx_matches_job ON matches(job_id, score DESC);
CREATE INDEX IF NOT EXISTS idx_messages_candidate ON messages(candidate_id);
"""


def _loads(value: str | None) -> list:
    """安全地把 JSON 文本还原成 list,损坏数据返回空列表而不是抛异常。"""
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _dumps(value: list) -> str:
    return json.dumps(value, ensure_ascii=False)


class Store:
    """所有读写都通过这个类,上层不直接碰 SQL。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ------------------------------------------------------------ 生命周期

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------ 岗位

    def add_job(self, job: JobProfile) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO jobs
               (id, title, raw_jd, skills, nice_to_have, min_years, max_years,
                education, keywords, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                job.id, job.title, job.raw_jd, _dumps(job.skills),
                _dumps(job.nice_to_have), job.min_years, job.max_years,
                job.education, _dumps(job.keywords), job.created_at,
            ),
        )
        self.conn.commit()

    def get_job(self, job_id: str) -> JobProfile | None:
        row = self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    def list_jobs(self) -> list[JobProfile]:
        rows = self.conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
        return [self._row_to_job(r) for r in rows]

    def find_job_by_title(self, title: str) -> JobProfile | None:
        """按标题精确匹配(便于 CLI 里用标题代替 ID)。"""
        row = self.conn.execute(
            "SELECT * FROM jobs WHERE title = ? LIMIT 1", (title,)
        ).fetchone()
        return self._row_to_job(row) if row else None

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> JobProfile:
        return JobProfile.from_dict({
            "id": row["id"], "title": row["title"], "raw_jd": row["raw_jd"],
            "skills": _loads(row["skills"]), "nice_to_have": _loads(row["nice_to_have"]),
            "min_years": row["min_years"], "max_years": row["max_years"],
            "education": row["education"], "keywords": _loads(row["keywords"]),
            "created_at": row["created_at"],
        })

    # ---------------------------------------------------------------- 候选人

    def add_candidate(self, cand: Candidate) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO candidates
               (id, name, resume_text, years, education, current_title,
                current_company, skills, source, status, note,
                created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                cand.id, cand.name, cand.resume_text, cand.years, cand.education,
                cand.current_title, cand.current_company, _dumps(cand.skills),
                cand.source, cand.status.value, cand.note,
                cand.created_at, cand.updated_at,
            ),
        )
        self.conn.commit()

    def get_candidate(self, cand_id: str) -> Candidate | None:
        row = self.conn.execute(
            "SELECT * FROM candidates WHERE id = ?", (cand_id,)
        ).fetchone()
        return self._row_to_candidate(row) if row else None

    def find_candidate_by_name(self, name: str) -> Candidate | None:
        row = self.conn.execute(
            "SELECT * FROM candidates WHERE name = ? LIMIT 1", (name,)
        ).fetchone()
        return self._row_to_candidate(row) if row else None

    def list_candidates(
        self, status: CandidateStatus | None = None, limit: int | None = None
    ) -> list[Candidate]:
        sql = "SELECT * FROM candidates"
        params: list = []
        if status is not None:
            sql += " WHERE status = ?"
            params.append(status.value)
        sql += " ORDER BY created_at DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        rows = self.conn.execute(sql, params).fetchall()
        return [self._row_to_candidate(r) for r in rows]

    def update_status(self, cand_id: str, status: CandidateStatus) -> bool:
        cur = self.conn.execute(
            "UPDATE candidates SET status = ?, updated_at = ? WHERE id = ?",
            (status.value, _now(), cand_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def count_by_status(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) AS n FROM candidates GROUP BY status"
        ).fetchall()
        return {r["status"]: r["n"] for r in rows}

    @staticmethod
    def _row_to_candidate(row: sqlite3.Row) -> Candidate:
        return Candidate.from_dict({
            "id": row["id"], "name": row["name"], "resume_text": row["resume_text"],
            "years": row["years"], "education": row["education"],
            "current_title": row["current_title"],
            "current_company": row["current_company"],
            "skills": _loads(row["skills"]), "source": row["source"],
            "status": row["status"], "note": row["note"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
        })

    # ---------------------------------------------------------------- 匹配结果

    def save_match(self, result: MatchResult) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO matches
               (candidate_id, job_id, score, skill_hits, skill_misses,
                bonus_hits, reasons, scored_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                result.candidate_id, result.job_id, result.score,
                _dumps(result.skill_hits), _dumps(result.skill_misses),
                _dumps(result.bonus_hits), _dumps(result.reasons),
                result.scored_at,
            ),
        )
        self.conn.commit()

    def get_matches(self, job_id: str, min_score: float = 0.0) -> list[MatchResult]:
        """按分数从高到低返回某岗位的匹配结果。"""
        rows = self.conn.execute(
            """SELECT * FROM matches WHERE job_id = ? AND score >= ?
               ORDER BY score DESC""",
            (job_id, min_score),
        ).fetchall()
        return [
            MatchResult.from_dict({
                "candidate_id": r["candidate_id"], "job_id": r["job_id"],
                "score": r["score"], "skill_hits": _loads(r["skill_hits"]),
                "skill_misses": _loads(r["skill_misses"]),
                "bonus_hits": _loads(r["bonus_hits"]),
                "reasons": _loads(r["reasons"]), "scored_at": r["scored_at"],
            })
            for r in rows
        ]

    def get_match(self, candidate_id: str, job_id: str) -> MatchResult | None:
        row = self.conn.execute(
            "SELECT * FROM matches WHERE candidate_id = ? AND job_id = ?",
            (candidate_id, job_id),
        ).fetchone()
        if not row:
            return None
        return MatchResult.from_dict({
            "candidate_id": row["candidate_id"], "job_id": row["job_id"],
            "score": row["score"], "skill_hits": _loads(row["skill_hits"]),
            "skill_misses": _loads(row["skill_misses"]),
            "bonus_hits": _loads(row["bonus_hits"]),
            "reasons": _loads(row["reasons"]), "scored_at": row["scored_at"],
        })

    # ------------------------------------------------------------------ 消息

    def save_draft(self, draft: MessageDraft) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO messages
               (id, candidate_id, job_id, content, template, approved,
                sent_at, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                draft.id, draft.candidate_id, draft.job_id, draft.content,
                draft.template, 1 if draft.approved else 0,
                draft.sent_at, draft.created_at,
            ),
        )
        self.conn.commit()

    def list_drafts(self, only_pending: bool = False) -> list[MessageDraft]:
        """``only_pending=True`` 时只返回尚未人工确认的草稿。"""
        sql = "SELECT * FROM messages"
        if only_pending:
            sql += " WHERE approved = 0 AND sent_at IS NULL"
        sql += " ORDER BY created_at DESC"
        rows = self.conn.execute(sql).fetchall()
        return [
            MessageDraft.from_dict({
                "id": r["id"], "candidate_id": r["candidate_id"],
                "job_id": r["job_id"], "content": r["content"],
                "template": r["template"], "approved": bool(r["approved"]),
                "sent_at": r["sent_at"], "created_at": r["created_at"],
            })
            for r in rows
        ]

    def get_draft(self, draft_id: str) -> MessageDraft | None:
        row = self.conn.execute(
            "SELECT * FROM messages WHERE id = ?", (draft_id,)
        ).fetchone()
        if not row:
            return None
        return MessageDraft.from_dict({
            "id": row["id"], "candidate_id": row["candidate_id"],
            "job_id": row["job_id"], "content": row["content"],
            "template": row["template"], "approved": bool(row["approved"]),
            "sent_at": row["sent_at"], "created_at": row["created_at"],
        })

    def approve_draft(self, draft_id: str) -> bool:
        """人工确认草稿 —— 这是发送前的强制关卡。"""
        cur = self.conn.execute(
            "UPDATE messages SET approved = 1 WHERE id = ?", (draft_id,)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def mark_sent(self, draft_id: str) -> bool:
        """记录"已发送"。只允许对已确认的草稿操作,防止误触。"""
        cur = self.conn.execute(
            "UPDATE messages SET sent_at = ? WHERE id = ? AND approved = 1",
            (_now(), draft_id),
        )
        self.conn.commit()
        return cur.rowcount > 0
