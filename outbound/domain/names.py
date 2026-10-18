"""Small text helpers for people and company names. Pure functions, shared by every layer."""

from __future__ import annotations

import re


def split_person(cell: str) -> tuple[str, str]:
    """``"Jack Kelly\\n(Co-Founder)"`` becomes (name, title)."""
    lines = [line.strip() for line in cell.splitlines() if line.strip()]
    if not lines:
        return "", ""
    title = " ".join(lines[1:])
    match = re.fullmatch(r"\((.*)\)", title)
    return lines[0], (match.group(1).strip() if match else title)


def split_name(full_name: str) -> tuple[str | None, str | None]:
    """First name and the rest; either may be None."""
    parts = full_name.split()
    if not parts:
        return None, None
    return parts[0], " ".join(parts[1:]) or None


def read_profile_title(title: str) -> tuple[str, str, str]:
    """``"Jane Doe - CTO - Acme Energy | LinkedIn"`` becomes (name, title, company)."""
    body = re.sub(r"\s*[|\-\u2013]\s*LinkedIn\s*$", "", title.strip(), flags=re.IGNORECASE)
    parts = [p.strip() for p in re.split(r"\s+[-\u2013]\s+", body) if p.strip()]
    if len(parts) >= 3:
        return parts[0], parts[1], parts[-1]
    if len(parts) == 2:
        return parts[0], "", parts[1]
    return (parts[0] if parts else ""), "", ""


def display_name(name: str | None, domain: str) -> str:
    """What to call a company: its name if we have one, else the first label of its domain."""
    return name or domain.split(".")[0].title()
