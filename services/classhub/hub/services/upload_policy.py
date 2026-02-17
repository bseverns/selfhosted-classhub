"""Upload-policy helpers extracted for independent unit testing."""


def parse_extensions(ext_csv: str) -> list[str]:
    parts = [p.strip().lower() for p in (ext_csv or "").split(",") if p.strip()]
    out = []
    for p in parts:
        if not p.startswith("."):
            p = "." + p
        if p not in out:
            out.append(p)
    return out


def front_matter_submission(front_matter: dict) -> dict:
    """Normalize lesson front-matter submission settings."""
    if not isinstance(front_matter, dict):
        return {"type": "", "accepted_exts": [], "naming": ""}

    submission = front_matter.get("submission") or {}
    if not isinstance(submission, dict):
        return {"type": "", "accepted_exts": [], "naming": ""}

    sub_type = str(submission.get("type") or "").strip().lower()
    naming = str(submission.get("naming") or "").strip()
    accepted = submission.get("accepted") or []
    if isinstance(accepted, str):
        accepted = [p.strip() for p in accepted.replace("|", ",").split(",") if p.strip()]

    accepted_exts = []
    for raw in accepted:
        ext = str(raw).strip().lower()
        if not ext:
            continue
        if not ext.startswith("."):
            ext = "." + ext
        if ext not in accepted_exts:
            accepted_exts.append(ext)

    return {"type": sub_type, "accepted_exts": accepted_exts, "naming": naming}
