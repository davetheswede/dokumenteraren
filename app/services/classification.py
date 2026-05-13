from __future__ import annotations

import re

from ..catalog import DOCUMENT_TEMPLATES


WORD_RE = re.compile(r"[a-zåäö0-9]+", re.IGNORECASE)


def normalize_tag(value: str) -> str:
    return value.strip().lower().replace(" ", "-")


def merge_tags(*parts: str) -> str:
    tags: list[str] = []
    seen: set[str] = set()
    for part in parts:
        for raw_tag in part.split(","):
            tag = raw_tag.strip()
            if not tag:
                continue
            key = tag.lower()
            if key not in seen:
                seen.add(key)
                tags.append(tag)
    return ",".join(tags)


def guess_template_id(*texts: str) -> str:
    haystack = " ".join(text for text in texts if text).lower()
    haystack_words = set(WORD_RE.findall(haystack))
    best_id = ""
    best_score = 0
    for item in DOCUMENT_TEMPLATES:
        score = 0
        if item["name"].lower() in haystack:
            score += 8
        for keyword in item.get("keywords", []):
            keyword_lower = keyword.lower()
            if keyword_lower in haystack:
                score += 5
            elif keyword_lower in haystack_words:
                score += 3
        for field in item.get("fields", []):
            if str(field).replace("_", " ").lower() in haystack:
                score += 1
        if score > best_score:
            best_score = score
            best_id = item["id"]
    return best_id if best_score >= 3 else "general_document"


def auto_classify(
    filename: str,
    *,
    subject: str = "",
    sender: str = "",
    default_tags: str = "",
    source_tag: str = "",
) -> tuple[str, str]:
    template_id = guess_template_id(filename, subject, sender)
    sender_domain = sender.rsplit("@", 1)[-1].strip(">").lower() if "@" in sender else ""
    inferred_tags = ["automatiskt sorterad"]
    if source_tag:
        inferred_tags.append(source_tag)
    if sender_domain:
        inferred_tags.append(f"from:{normalize_tag(sender_domain)}")
    if template_id and template_id != "general_document":
        inferred_tags.append("mall:gissad")
    return template_id, merge_tags(default_tags, ",".join(inferred_tags))
