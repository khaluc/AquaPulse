"""Minimal reviewer accounts for the verification queue.

Section 16 needs to know who is a volunteer and who is an expert, and a volunteer must
not verify their own report. There is no user system yet, so reviewers come from
AQUAPULSE_REVIEWERS:

    AQUAPULSE_REVIEWERS="volunteer:vol-01:<token>,expert:exp-01:<token>"

and call the API with "Authorization: Bearer <token>". Enough for a pilot on one
server; a real deployment needs proper accounts (Supabase Auth, per section 3).
"""

from __future__ import annotations

import hmac
import os
from dataclasses import dataclass

from fastapi import Header, HTTPException

VOLUNTEER, EXPERT = "volunteer", "expert"


@dataclass(frozen=True)
class Reviewer:
    id: str
    role: str


def configured_reviewers() -> dict[str, Reviewer]:
    """token -> reviewer, from the environment each time (so tests can change it)."""
    reviewers = {}
    for entry in filter(None, (e.strip() for e in os.environ.get("AQUAPULSE_REVIEWERS", "").split(","))):
        role, reviewer_id, token = entry.split(":", 2)
        if role not in (VOLUNTEER, EXPERT) or not reviewer_id or len(token) < 8:
            raise ValueError(f"AQUAPULSE_REVIEWERS: mục không hợp lệ cho {reviewer_id or '?'}")
        reviewers[token] = Reviewer(reviewer_id, role)
    return reviewers


def volunteer_ids() -> set[str]:
    return {r.id for r in configured_reviewers().values() if r.role == VOLUNTEER}


def current_reviewer(authorization: str | None = Header(None)) -> Reviewer:
    reviewers = configured_reviewers()
    if not reviewers:
        raise HTTPException(status_code=503, detail="Chưa cấu hình tài khoản xác minh (AQUAPULSE_REVIEWERS).")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Cần đăng nhập tài khoản xác minh.")
    given = authorization.removeprefix("Bearer ").strip()
    for token, reviewer in reviewers.items():
        if hmac.compare_digest(given, token):
            return reviewer
    raise HTTPException(status_code=401, detail="Mã đăng nhập không đúng.")
