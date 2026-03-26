import copy
from typing import Any, Dict, List, Optional


def run_has_term_overlap(title_terms: set[str], msg_terms: set[str]) -> bool:
    for message_term in msg_terms:
        if len(message_term) < 4:
            continue
        for title_term in title_terms:
            if len(title_term) < 4:
                continue
            if (
                message_term == title_term
                or message_term.startswith(title_term)
                or title_term.startswith(message_term)
            ):
                return True
    return False


def run_task_reference_candidates(grounding: Dict[str, Any], *, helpers: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(grounding, dict):
        return []
    candidates: Dict[str, Dict[str, Any]] = {}

    def add_rows(rows: Any, source: str) -> None:
        if not isinstance(rows, list):
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            task_id = row.get("id")
            title = row.get("title")
            if not isinstance(task_id, str) or not task_id.strip():
                continue
            if not isinstance(title, str) or not title.strip():
                continue
            existing = candidates.get(task_id.strip())
            if not existing:
                existing = {
                    "id": task_id.strip(),
                    "title": helpers["_canonical_task_title"](title),
                    "parent_title": str(row.get("parent_title") or "").strip() or None,
                    "status": str(row.get("status") or "").strip().lower(),
                    "sources": set(),
                }
                candidates[task_id.strip()] = existing
            existing["sources"].add(source)
            if not existing.get("parent_title") and isinstance(row.get("parent_title"), str) and row.get("parent_title").strip():
                existing["parent_title"] = row.get("parent_title").strip()
            if source == "displayed" and isinstance(row.get("ordinal"), int):
                existing["ordinal"] = row.get("ordinal")
            if source == "displayed" and isinstance(row.get("view_name"), str):
                existing["view_name"] = row.get("view_name")

    add_rows(grounding.get("tasks"), "grounding")
    add_rows(grounding.get("recent_task_refs"), "recent")
    add_rows(grounding.get("displayed_task_refs"), "displayed")
    return list(candidates.values())


def run_score_task_reference_candidate(clause: str, candidate: Dict[str, Any], *, helpers: Dict[str, Any]) -> Dict[str, Any]:
    clause_text = helpers["_normalize_query_text"](clause)
    if not clause_text:
        return {"score": 0, "evidence": []}
    title_text = helpers["_normalize_query_text"](candidate.get("title"))
    if not title_text:
        return {"score": 0, "evidence": []}
    parent_text = helpers["_normalize_query_text"](candidate.get("parent_title"))

    clause_terms = {
        term
        for term in helpers["_grounding_terms"](clause_text)
        if term not in helpers["TASK_MATCH_IGNORE_TERMS"]
    }
    title_terms = helpers["_grounding_terms"](title_text)
    overlap_terms = {
        term
        for term in clause_terms
        if any(
            term == title_term or term.startswith(title_term) or title_term.startswith(term)
            for title_term in title_terms
        )
    }

    score = 0
    evidence: List[str] = []
    if title_text in clause_text:
        score += 10
        evidence.append("title_exact")
    elif overlap_terms:
        score += len(overlap_terms) * 3
        evidence.append(f"term_overlap:{','.join(sorted(overlap_terms))}")
        if len(overlap_terms) >= 2:
            score += 2
    else:
        return {"score": 0, "evidence": []}

    if parent_text:
        parent_terms = helpers["_grounding_terms"](parent_text)
        parent_overlap_terms = {
            term
            for term in clause_terms
            if any(
                term == parent_term or term.startswith(parent_term) or parent_term.startswith(term)
                for parent_term in parent_terms
            )
        }
        if parent_text in clause_text:
            score += 4
            evidence.append("parent_exact")
        elif parent_overlap_terms:
            score += len(parent_overlap_terms) * 2
            evidence.append(f"parent_overlap:{','.join(sorted(parent_overlap_terms))}")

    sources = candidate.get("sources") or set()
    if "displayed" in sources:
        score += 4
        evidence.append("displayed")
    if "recent" in sources:
        score += 3
        evidence.append("recent")
    if "grounding" in sources:
        score += 1
        evidence.append("grounding")
    if candidate.get("status") in {"open", "blocked"}:
        score += 1
        evidence.append("open")

    return {"score": score, "evidence": evidence}


def run_rank_task_reference_candidates(
    clause: str,
    grounding: Dict[str, Any],
    *,
    open_only: bool = True,
    helpers: Dict[str, Any],
) -> List[Dict[str, Any]]:
    ranked: List[Dict[str, Any]] = []
    for candidate in run_task_reference_candidates(grounding, helpers=helpers):
        if open_only and candidate.get("status") not in {"open", "blocked"}:
            continue
        scored = run_score_task_reference_candidate(clause, candidate, helpers=helpers)
        score = scored.get("score") or 0
        if score <= 0:
            continue
        ranked.append(
            {
                "id": candidate["id"],
                "title": candidate["title"],
                "parent_title": candidate.get("parent_title"),
                "status": candidate.get("status"),
                "sources": sorted(candidate.get("sources") or []),
                "score": score,
                "evidence": scored.get("evidence") or [],
            }
        )
    ranked.sort(
        key=lambda item: (
            item["score"],
            1 if "displayed" in item["sources"] else 0,
            1 if "recent" in item["sources"] else 0,
        ),
        reverse=True,
    )
    return ranked


def run_best_task_reference_candidate(
    clause: str,
    grounding: Dict[str, Any],
    *,
    open_only: bool = True,
    helpers: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    ranked = run_rank_task_reference_candidates(clause, grounding, open_only=open_only, helpers=helpers)
    if not ranked:
        return None
    top = ranked[0]
    runner_up_score = ranked[1]["score"] if len(ranked) > 1 else 0
    if "title_exact" in (top.get("evidence") or []) and top["score"] >= 10:
        return top
    if top["score"] >= 6 and (top["score"] - runner_up_score) >= 2:
        return top
    return None


def run_completion_candidate_rows(grounding: Dict[str, Any], *, helpers: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(grounding, dict):
        return []
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for key in ("recent_task_refs", "tasks"):
        rows = grounding.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            task_id = row.get("id")
            title = row.get("title")
            if not isinstance(task_id, str) or not task_id.strip():
                continue
            if not isinstance(title, str) or not title.strip():
                continue
            if task_id in seen:
                continue
            seen.add(task_id)
            out.append(
                {
                    "id": task_id.strip(),
                    "title": helpers["_canonical_task_title"](title),
                    "status": str(row.get("status") or "").strip().lower(),
                }
            )
    return out


def run_sanitize_completion_extraction(
    extraction: Dict[str, Any],
    grounding: Dict[str, Any],
    *,
    helpers: Dict[str, Any],
) -> Dict[str, Any]:
    if not isinstance(extraction, dict):
        return helpers["_empty_extraction"]()

    rows = run_completion_candidate_rows(grounding, helpers=helpers)
    open_by_id: Dict[str, Dict[str, Any]] = {
        row["id"]: row for row in rows if row.get("status") in {"open", "blocked"}
    }
    open_by_title: Dict[str, Dict[str, Any]] = {
        row["title"].lower().strip(): row for row in rows if row.get("status") in {"open", "blocked"}
    }

    normalized_tasks: List[Dict[str, Any]] = []
    seen: set[str] = set()
    raw_tasks = extraction.get("tasks", [])
    if isinstance(raw_tasks, list):
        for task in raw_tasks:
            if not isinstance(task, dict):
                continue
            action = str(task.get("action") or "").lower()
            status = str(task.get("status") or "").lower()
            if action != "complete" and status != "done":
                normalized_tasks.append(task)
                continue
            candidate = None
            target_id = task.get("target_task_id")
            if isinstance(target_id, str) and target_id.strip():
                candidate = open_by_id.get(target_id.strip())
            if candidate is None:
                title = task.get("title")
                if isinstance(title, str) and title.strip():
                    candidate = open_by_title.get(title.strip().lower())
            if candidate is None:
                title_parts = [
                    part.strip()
                    for part in (task.get("title"), task.get("notes"))
                    if isinstance(part, str) and part.strip()
                ]
                if title_parts:
                    candidate = run_best_task_reference_candidate(
                        " ".join(title_parts),
                        grounding,
                        open_only=True,
                        helpers=helpers,
                    )
            if isinstance(candidate, dict) and candidate.get("id") in open_by_id:
                task_id = candidate["id"]
                if task_id in seen:
                    continue
                seen.add(task_id)
                resolved = open_by_id[task_id]
                normalized_tasks.append(
                    {
                        "title": resolved["title"],
                        "action": "complete",
                        "status": "done",
                        "target_task_id": task_id,
                    }
                )

    out = dict(extraction)
    out["tasks"] = normalized_tasks
    return out


def run_sanitize_create_extraction(extraction: Dict[str, Any], *, helpers: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(extraction, dict):
        return helpers["_empty_extraction"]()

    raw_tasks = extraction.get("tasks", [])
    if not isinstance(raw_tasks, list):
        return extraction

    sanitized_tasks: List[Dict[str, Any]] = []
    for task in raw_tasks:
        if not isinstance(task, dict):
            continue
        title = task.get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        normalized = dict(task)
        action = str(normalized.get("action") or "").lower()
        status = str(normalized.get("status") or "").lower()
        target_task_id = normalized.get("target_task_id")
        if action in {"complete", "archive", "update"} or status in {"done", "archived"}:
            sanitized_tasks.append(normalized)
            continue
        if isinstance(target_task_id, str) and target_task_id.strip():
            normalized.pop("target_task_id", None)
        normalized["action"] = "create"
        sanitized_tasks.append(normalized)

    out = dict(extraction)
    out["tasks"] = sanitized_tasks
    return out


def run_apply_displayed_task_reference_extraction(
    extraction: Dict[str, Any],
    grounding: Dict[str, Any],
    *,
    helpers: Dict[str, Any],
) -> Dict[str, Any]:
    if not isinstance(extraction, dict):
        extraction = helpers["_empty_extraction"]()
    rows = grounding.get("displayed_task_refs") if isinstance(grounding, dict) else None
    if not isinstance(rows, list) or not rows:
        return extraction

    raw_tasks = extraction.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        return extraction

    displayed_by_title = {
        helpers["_canonical_task_title"](row.get("title")).lower(): row
        for row in rows
        if isinstance(row, dict)
        and isinstance(row.get("id"), str)
        and row.get("id")
        and isinstance(row.get("title"), str)
        and row.get("title")
    }
    single_displayed = rows[0] if len(rows) == 1 and isinstance(rows[0], dict) else None
    normalized_tasks: List[Any] = []
    for task in raw_tasks:
        if not isinstance(task, dict):
            normalized_tasks.append(task)
            continue
        action = str(task.get("action") or "").lower()
        status = str(task.get("status") or "").lower()
        requires_target = action in {"update", "complete", "archive"} or status in {"done", "archived"}
        if not requires_target:
            normalized_tasks.append(task)
            continue
        normalized = dict(task)
        target_task_id = normalized.get("target_task_id")
        if not isinstance(target_task_id, str) or not target_task_id.strip():
            title_value = normalized.get("title")
            matched_row = None
            if isinstance(title_value, str) and title_value.strip():
                matched_row = displayed_by_title.get(helpers["_canonical_task_title"](title_value).lower())
            if matched_row is None and single_displayed is not None:
                matched_row = single_displayed
            if isinstance(matched_row, dict):
                normalized["target_task_id"] = matched_row["id"].strip()
                normalized["title"] = helpers["_canonical_task_title"](matched_row["title"])
        normalized_tasks.append(normalized)
    out = dict(extraction)
    out["tasks"] = normalized_tasks
    return out


def run_is_explicit_displayed_reference_mutation(
    message: str,
    extraction: Dict[str, Any],
    grounding: Dict[str, Any],
    *,
    helpers: Dict[str, Any],
) -> bool:
    rows = grounding.get("displayed_task_refs") if isinstance(grounding, dict) else None
    if not isinstance(rows, list) or not isinstance(extraction, dict):
        return False
    displayed_ids = {
        row.get("id")
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("id"), str) and row.get("id")
    }
    tasks = extraction.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        return False
    for task in tasks:
        if not isinstance(task, dict):
            continue
        action = str(task.get("action") or "").lower()
        status = str(task.get("status") or "").lower()
        if task.get("target_task_id") not in displayed_ids:
            continue
        if action in {"update", "complete", "archive"} or status in {"done", "archived"}:
            return True
    return False


def run_is_explicit_recent_named_reference_mutation(
    message: str,
    extraction: Dict[str, Any],
    grounding: Dict[str, Any],
    *,
    helpers: Dict[str, Any],
) -> bool:
    if not isinstance(extraction, dict):
        return False
    rows = grounding.get("recent_task_refs") if isinstance(grounding, dict) else None
    if not isinstance(rows, list):
        return False
    recent_ids = {
        row.get("id")
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("id"), str) and row.get("id")
    }
    tasks = extraction.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        return False
    for task in tasks:
        if not isinstance(task, dict):
            continue
        target_task_id = task.get("target_task_id")
        action = str(task.get("action") or "").lower()
        status = str(task.get("status") or "").lower()
        if target_task_id in recent_ids and (action in {"complete", "archive"} or status in {"done", "archived"}):
            return True
    return False


def run_reminder_requires_target(reminder: Dict[str, Any]) -> bool:
    action = str(reminder.get("action") or "").strip().lower()
    status = str(reminder.get("status") or "").strip().lower()
    return action in {"update", "complete", "dismiss", "cancel"} or status in {"completed", "dismissed", "canceled"}


def run_reminder_requires_schedule(reminder: Dict[str, Any], *, helpers: Dict[str, Any]) -> bool:
    if run_reminder_requires_target(reminder):
        return False
    return helpers["_parse_due_at"](reminder.get("remind_at")) is None


def run_sanitize_targeted_task_actions(
    message: str,
    extraction: Dict[str, Any],
    grounding: Dict[str, Any],
    *,
    helpers: Dict[str, Any],
) -> Dict[str, Any]:
    if not isinstance(extraction, dict):
        return helpers["_empty_extraction"]()
    raw_tasks = extraction.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        return extraction

    rows = run_completion_candidate_rows(grounding, helpers=helpers)
    row_by_id = {row["id"]: row for row in rows}
    sanitized: List[Any] = []
    for task in raw_tasks:
        if not isinstance(task, dict):
            sanitized.append(task)
            continue
        target_id = task.get("target_task_id")
        action = str(task.get("action") or "").lower()
        status = str(task.get("status") or "").lower()
        requires_target = action in {"update", "complete", "archive"} or status in {"done", "archived"}
        if (not isinstance(target_id, str) or not target_id.strip()) and requires_target:
            candidate_seed = " ".join(
                part
                for part in (message, task.get("title"), task.get("notes"))
                if isinstance(part, str) and part.strip()
            )
            best_candidate = run_best_task_reference_candidate(
                candidate_seed,
                grounding,
                open_only=True,
                helpers=helpers,
            )
            if best_candidate:
                normalized = dict(task)
                normalized["target_task_id"] = best_candidate["id"]
                normalized["title"] = best_candidate["title"]
                target_id = best_candidate["id"]
                task = normalized
            else:
                sanitized.append(task)
                continue
        elif not isinstance(target_id, str) or not target_id.strip():
            sanitized.append(task)
            continue

        target = row_by_id.get(target_id.strip())
        if not target:
            normalized = dict(task)
            normalized.pop("target_task_id", None)
            if normalized.get("action") in {"update", "noop"}:
                normalized["action"] = "create"
            sanitized.append(normalized)
            continue

        if action in {"complete", "archive"}:
            sanitized.append(task)
            continue

        candidate_title = str(target.get("title") or "")
        task_seed = " ".join(
            part
            for part in (task.get("title"), task.get("notes"))
            if isinstance(part, str) and part.strip()
        )
        if task_seed:
            candidate_terms = helpers["_grounding_terms"](candidate_title.lower())
            seed_terms = helpers["_grounding_terms"](task_seed.lower())
            if run_has_term_overlap(candidate_terms, seed_terms):
                sanitized.append(task)
                continue
        if (
            isinstance(task.get("title"), str)
            and helpers["_canonical_task_title"](task.get("title")).lower()
            == helpers["_canonical_task_title"](candidate_title).lower()
        ):
            sanitized.append(task)
            continue

        normalized = dict(task)
        normalized.pop("target_task_id", None)
        normalized["action"] = "create"
        sanitized.append(normalized)

    out = dict(extraction)
    out["tasks"] = sanitized
    return out


def run_reminder_reference_candidates(grounding: Dict[str, Any], *, helpers: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(grounding, dict):
        return []
    candidates_by_id: Dict[str, Dict[str, Any]] = {}

    def add_rows(rows: Any, source: str) -> None:
        if not isinstance(rows, list):
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            reminder_id = row.get("id")
            title = row.get("title")
            if not isinstance(reminder_id, str) or not reminder_id.strip():
                continue
            if not isinstance(title, str) or not title.strip():
                continue
            existing = candidates_by_id.get(reminder_id)
            if existing is None:
                candidates_by_id[reminder_id] = {
                    "id": reminder_id.strip(),
                    "title": helpers["_canonical_task_title"](title),
                    "status": str(row.get("status") or "").strip().lower(),
                    "message": row.get("message"),
                    "work_item_title": row.get("work_item_title"),
                    "kind": row.get("kind"),
                    "remind_at": row.get("remind_at"),
                    "sources": {source},
                }
                continue
            existing["sources"].add(source)
            if not existing.get("message") and row.get("message"):
                existing["message"] = row.get("message")
            if not existing.get("work_item_title") and row.get("work_item_title"):
                existing["work_item_title"] = row.get("work_item_title")
            if not existing.get("remind_at") and row.get("remind_at"):
                existing["remind_at"] = row.get("remind_at")
            row_status = str(row.get("status") or "").strip().lower()
            if existing.get("status") not in {"pending", "sent"} and row_status in {"pending", "sent"}:
                existing["status"] = row_status

    add_rows(grounding.get("recent_reminder_refs"), "recent")
    add_rows(grounding.get("reminders"), "grounding")
    return list(candidates_by_id.values())


def run_score_reminder_reference_candidate(
    clause: str,
    candidate: Dict[str, Any],
    *,
    helpers: Dict[str, Any],
) -> Dict[str, Any]:
    normalized_clause = helpers["_canonical_task_title"](clause).lower().strip()
    if not normalized_clause:
        return {"score": 0, "evidence": []}

    title = helpers["_canonical_task_title"](candidate.get("title")).lower().strip()
    message = str(candidate.get("message") or "").lower()
    work_item_title = helpers["_canonical_task_title"](candidate.get("work_item_title")).lower().strip()
    candidate_terms = helpers["_grounding_terms"](title)
    message_terms = helpers["_grounding_terms"](message)
    work_item_terms = helpers["_grounding_terms"](work_item_title)
    clause_terms = helpers["_grounding_terms"](normalized_clause)
    evidence: List[str] = []
    score = 0

    if title == normalized_clause:
        score += 10
        evidence.append("title_exact")
    else:
        overlap_terms = sorted((candidate_terms | message_terms | work_item_terms) & clause_terms)
        if not overlap_terms:
            return {"score": 0, "evidence": []}
        score += len(overlap_terms) * 3
        evidence.append(f"term_overlap:{','.join(overlap_terms)}")
        if len(overlap_terms) >= 2:
            score += 2

    status = candidate.get("status")
    if status == "pending":
        score += 2
        evidence.append("pending")
    elif status == "sent":
        score += 1
        evidence.append("sent")
    sources = candidate.get("sources") or set()
    if "recent" in sources:
        score += 3
        evidence.append("recent")
    if "grounding" in sources:
        score += 1
        evidence.append("grounding")
    return {"score": score, "evidence": evidence}


def run_rank_reminder_reference_candidates(
    clause: str,
    grounding: Dict[str, Any],
    *,
    active_only: bool = True,
    helpers: Dict[str, Any],
) -> List[Dict[str, Any]]:
    ranked: List[Dict[str, Any]] = []
    for candidate in run_reminder_reference_candidates(grounding, helpers=helpers):
        if active_only and candidate.get("status") not in {"pending", "sent"}:
            continue
        scored = run_score_reminder_reference_candidate(clause, candidate, helpers=helpers)
        score = scored.get("score") or 0
        if score <= 0:
            continue
        ranked.append(
            {
                "id": candidate["id"],
                "title": candidate["title"],
                "work_item_title": candidate.get("work_item_title"),
                "remind_at": candidate.get("remind_at"),
                "status": candidate.get("status"),
                "sources": sorted(candidate.get("sources") or []),
                "score": score,
                "evidence": scored.get("evidence") or [],
            }
        )
    ranked.sort(
        key=lambda item: (
            item["score"],
            1 if "recent" in item.get("sources", []) else 0,
            1 if "grounding" in item.get("sources", []) else 0,
        ),
        reverse=True,
    )
    return ranked


def run_best_reminder_reference_candidate(
    clause: str,
    grounding: Dict[str, Any],
    *,
    active_only: bool = True,
    helpers: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    ranked = run_rank_reminder_reference_candidates(
        clause,
        grounding,
        active_only=active_only,
        helpers=helpers,
    )
    if not ranked:
        return None
    top = ranked[0]
    runner_up_score = ranked[1]["score"] if len(ranked) > 1 else 0
    if "title_exact" in (top.get("evidence") or []) and top["score"] >= 8:
        return top
    if top["score"] >= 5 and (top["score"] - runner_up_score) >= 2:
        return top
    return None


def run_sanitize_targeted_reminder_actions(
    message: str,
    extraction: Dict[str, Any],
    grounding: Dict[str, Any],
    *,
    helpers: Dict[str, Any],
) -> Dict[str, Any]:
    if not isinstance(extraction, dict):
        return helpers["_empty_extraction"]()
    raw_reminders = extraction.get("reminders")
    if not isinstance(raw_reminders, list) or not raw_reminders:
        return extraction

    rows = run_reminder_reference_candidates(grounding, helpers=helpers)
    row_by_id = {row["id"]: row for row in rows}
    sanitized: List[Any] = []
    for reminder in raw_reminders:
        if not isinstance(reminder, dict):
            sanitized.append(reminder)
            continue
        normalized = dict(reminder)
        if not normalized.get("action") and not run_reminder_requires_target(normalized):
            normalized["action"] = "create"
        target_id = normalized.get("target_reminder_id")
        if (not isinstance(target_id, str) or not target_id.strip()) and run_reminder_requires_target(normalized):
            candidate_seed = " ".join(
                part
                for part in (message, normalized.get("title"), normalized.get("message"))
                if isinstance(part, str) and part.strip()
            )
            best_candidate = run_best_reminder_reference_candidate(
                candidate_seed,
                grounding,
                active_only=True,
                helpers=helpers,
            )
            if best_candidate:
                normalized["target_reminder_id"] = best_candidate["id"]
                normalized["title"] = best_candidate["title"]
        elif isinstance(target_id, str) and target_id.strip():
            target_row = row_by_id.get(target_id.strip())
            if target_row is None:
                normalized.pop("target_reminder_id", None)
            else:
                title_value = normalized.get("title")
                if not isinstance(title_value, str) or not title_value.strip() or title_value.strip() == target_id.strip():
                    normalized["title"] = target_row["title"]
        sanitized.append(normalized)

    out = dict(extraction)
    out["reminders"] = sanitized
    return out


def run_detected_mutation_phrase(task: Optional[Dict[str, Any]] = None) -> str:
    action = str((task or {}).get("action") or "").lower()
    status = str((task or {}).get("status") or "").lower()
    if action == "archive" or status == "archived":
        return "delete"
    if action == "complete" or status == "done":
        return "mark as done"
    if action == "update":
        return "update"
    return "change"


def run_detected_reminder_mutation_phrase(reminder: Optional[Dict[str, Any]] = None) -> str:
    action = str((reminder or {}).get("action") or "").lower()
    status = str((reminder or {}).get("status") or "").lower()
    if action in {"cancel", "dismiss"} or status in {"canceled", "dismissed"}:
        return "cancel"
    if action == "complete" or status == "completed":
        return "mark as done"
    if action == "update":
        return "update"
    return "change"


def run_build_candidate_clarification_text(action_phrase: str, entity_label: str, ranked: List[Dict[str, Any]], *, helpers: Dict[str, Any]) -> str:
    def _label(item: Dict[str, Any]) -> str:
        title = str(item.get("title") or "").strip()
        parent_title = str(item.get("parent_title") or "").strip()
        if parent_title:
            return f"{title} (under {parent_title})"
        work_item_title = str(item.get("work_item_title") or "").strip()
        if work_item_title:
            return f"{title} (for {work_item_title})"
        return title

    if len(ranked) == 1 or ranked[0]["score"] >= ranked[1]["score"] + 2:
        return (
            f"Do you mean <code>{helpers['escape_html'](_label(ranked[0]))}</code>?\n"
            f"Tell me if that is the {entity_label} you want to {action_phrase}."
        )
    options = "\n".join(f"• <code>{helpers['escape_html'](_label(item))}</code>" for item in ranked[:2])
    return (
        f"Which {entity_label} do you want to {action_phrase}?\n"
        f"{options}\n\n"
        f"Reply with the {entity_label} name, and I will revise the change."
    )


def run_candidate_task_clarification_info(
    message: str,
    extraction: Dict[str, Any],
    grounding: Dict[str, Any],
    *,
    helpers: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    candidate_queries: List[tuple[str, Optional[Dict[str, Any]]]] = []
    if isinstance(extraction, dict):
        tasks = extraction.get("tasks")
        if isinstance(tasks, list):
            for task in tasks:
                if not isinstance(task, dict):
                    continue
                action = str(task.get("action") or "").lower()
                status = str(task.get("status") or "").lower()
                requires_target = action in {"update", "complete", "archive"} or status in {"done", "archived"}
                if requires_target and not task.get("target_task_id"):
                    query = task.get("title") if isinstance(task.get("title"), str) and task.get("title").strip() else message
                    candidate_queries.append((query, task))
    for query, task in candidate_queries:
        ranked = run_rank_task_reference_candidates(query, grounding, open_only=True, helpers=helpers)
        if not ranked:
            continue
        action_phrase = run_detected_mutation_phrase(task)
        candidates = [
            {
                "id": item["id"],
                "title": item["title"],
                "parent_title": item.get("parent_title"),
                "status": item.get("status"),
                "score": item.get("score"),
            }
            for item in ranked[:4]
        ]
        if len(ranked) == 1 or ranked[0]["score"] >= ranked[1]["score"] + 2:
            top_label = ranked[0]["title"]
            if isinstance(ranked[0].get("parent_title"), str) and ranked[0]["parent_title"].strip():
                top_label = f"{top_label} (under {ranked[0]['parent_title'].strip()})"
            return {
                "text": (
                    f"Do you mean <code>{helpers['escape_html'](top_label)}</code>?\n"
                    f"Tell me if that is the task you want to {action_phrase}."
                ),
                "action_phrase": action_phrase,
                "candidates": candidates,
                "query": query,
                "state": {"kind": "task_candidates", "candidates": candidates},
            }
        return {
            "text": run_build_candidate_clarification_text(action_phrase, "task", ranked, helpers=helpers),
            "action_phrase": action_phrase,
            "candidates": candidates,
            "query": query,
            "state": {"kind": "task_candidates", "candidates": candidates},
        }
    return None


def run_candidate_reminder_clarification_info(
    message: str,
    extraction: Dict[str, Any],
    grounding: Dict[str, Any],
    *,
    helpers: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    candidate_queries: List[tuple[str, Optional[Dict[str, Any]]]] = []
    if isinstance(extraction, dict):
        reminders = extraction.get("reminders")
        if isinstance(reminders, list):
            for reminder in reminders:
                if not isinstance(reminder, dict):
                    continue
                if run_reminder_requires_target(reminder) and not reminder.get("target_reminder_id"):
                    query = reminder.get("title") if isinstance(reminder.get("title"), str) and reminder.get("title").strip() else message
                    candidate_queries.append((query, reminder))
    for query, reminder in candidate_queries:
        ranked = run_rank_reminder_reference_candidates(query, grounding, active_only=True, helpers=helpers)
        if not ranked:
            continue
        action_phrase = run_detected_reminder_mutation_phrase(reminder)
        candidates = [
            {
                "id": item["id"],
                "title": item["title"],
                "work_item_title": item.get("work_item_title"),
                "remind_at": item.get("remind_at"),
                "status": item.get("status"),
                "score": item.get("score"),
            }
            for item in ranked[:4]
        ]
        return {
            "text": run_build_candidate_clarification_text(action_phrase, "reminder", ranked, helpers=helpers),
            "action_phrase": action_phrase,
            "candidates": candidates,
            "query": query,
            "state": {"kind": "reminder_candidates", "candidates": candidates},
        }
    return None


def run_missing_reminder_schedule_info(extraction: Dict[str, Any], *, helpers: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(extraction, dict):
        return None
    reminders = extraction.get("reminders")
    if not isinstance(reminders, list):
        return None
    for idx, reminder in enumerate(reminders):
        if not isinstance(reminder, dict):
            continue
        if not run_reminder_requires_schedule(reminder, helpers=helpers):
            continue
        title = str(reminder.get("title") or "").strip() or "that reminder"
        return {
            "text": (
                "I need one clarification before applying changes:\n"
                f"• When should I remind you about <code>{helpers['escape_html'](title)}</code>?\n\n"
                "Reply with a time like <code>tomorrow at 3 PM</code> or <code>next Monday morning</code>."
            ),
            "state": {"kind": "reminder_schedule", "reminder_index": idx},
        }
    return None


def run_build_candidate_task_clarification(
    message: str,
    extraction: Dict[str, Any],
    grounding: Dict[str, Any],
    *,
    helpers: Dict[str, Any],
) -> Optional[str]:
    info = run_candidate_task_clarification_info(message, extraction, grounding, helpers=helpers)
    if not info:
        return None
    text = info.get("text")
    return text if isinstance(text, str) and text.strip() else None


def run_merge_grounding_task_refs(grounding: Dict[str, Any], key: str, rows: List[Dict[str, Any]]) -> None:
    existing_rows = grounding.get(key)
    merged: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows + (existing_rows if isinstance(existing_rows, list) else []):
        if not isinstance(row, dict):
            continue
        task_id = row.get("id")
        title = row.get("title")
        if not isinstance(task_id, str) or not task_id.strip():
            continue
        if not isinstance(title, str) or not title.strip():
            continue
        if task_id in seen:
            continue
        seen.add(task_id)
        merged.append(row)
    grounding[key] = merged


def run_select_clarification_candidate(
    reply_text: str,
    candidates: List[Dict[str, Any]],
    *,
    helpers: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    if not candidates:
        return None
    status_values = {
        str(candidate.get("status") or "").strip().lower()
        for candidate in candidates
        if isinstance(candidate, dict)
    }
    open_only = bool(status_values & {"open", "blocked"})
    reply_grounding = {
        "tasks": candidates,
        "recent_task_refs": candidates,
        "displayed_task_refs": candidates,
    }
    best_candidate = run_best_task_reference_candidate(
        reply_text,
        reply_grounding,
        open_only=open_only,
        helpers=helpers,
    )
    if best_candidate:
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get("id") == best_candidate["id"]:
                return candidate
    return None


def run_fill_clarified_task_target(base_extraction: Dict[str, Any], candidate: Dict[str, Any], *, helpers: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(base_extraction, dict):
        return helpers["_empty_extraction"]()
    tasks = base_extraction.get("tasks")
    if not isinstance(tasks, list):
        return base_extraction
    unresolved_indexes = [
        idx
        for idx, task in enumerate(tasks)
        if isinstance(task, dict)
        and not (isinstance(task.get("target_task_id"), str) and task.get("target_task_id").strip())
        and (
            str(task.get("action") or "").lower() in {"update", "complete", "archive"}
            or str(task.get("status") or "").lower() in {"done", "archived"}
        )
    ]
    if len(unresolved_indexes) != 1:
        return base_extraction
    resolved = copy.deepcopy(base_extraction)
    resolved_tasks = resolved.get("tasks") if isinstance(resolved.get("tasks"), list) else []
    task = resolved_tasks[unresolved_indexes[0]]
    task["target_task_id"] = candidate["id"]
    task["title"] = candidate["title"]
    return resolved


def run_fill_clarified_reminder_target(
    base_extraction: Dict[str, Any],
    candidate: Dict[str, Any],
    *,
    helpers: Dict[str, Any],
) -> Dict[str, Any]:
    if not isinstance(base_extraction, dict):
        return helpers["_empty_extraction"]()
    reminders = base_extraction.get("reminders")
    if not isinstance(reminders, list):
        return base_extraction
    unresolved_indexes = [
        idx
        for idx, reminder in enumerate(reminders)
        if isinstance(reminder, dict)
        and not (isinstance(reminder.get("target_reminder_id"), str) and reminder.get("target_reminder_id").strip())
        and run_reminder_requires_target(reminder)
    ]
    if len(unresolved_indexes) != 1:
        return base_extraction
    resolved = copy.deepcopy(base_extraction)
    resolved_reminders = resolved.get("reminders") if isinstance(resolved.get("reminders"), list) else []
    reminder = resolved_reminders[unresolved_indexes[0]]
    reminder["target_reminder_id"] = candidate["id"]
    reminder["title"] = candidate["title"]
    return resolved
