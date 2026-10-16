"""Agent 14 - Meeting-to-Execution.

Extracts decisions, action items, owners, deadlines and open questions from an
authorised transcript. Owners are resolved only through the directory; deadlines
are resolved deterministically relative to the meeting date; ambiguous items
ask for clarification instead of guessing. Every item cites transcript lines.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from app.agents.base import AgentContext, AgentInput, AgentResult, AgentSpec, BaseAgent, ProposedAction
from app.agents.common import guard_untrusted, number_lines, parse_dt, resolve_deadline
from app.agents.registry import register
from app.agents.services import AgentServices
from app.core.errors import NotFound

ACTION_PAT = re.compile(r"\b(will|should|needs? to|has to|going to|can you|could you|please|let'?s|i'?ll|action:?|todo:?)\b", re.I)
DECISION_PAT = re.compile(r"\b(decided|decision|agreed|we'?ll go with|approved|sign(ed)? off|consensus)\b", re.I)
QUESTION_PAT = re.compile(r"\?$|\b(open question|unclear|tbd|to be decided|not sure|need to confirm)\b", re.I)
DEADLINE_PAT = re.compile(r"\b(by|before|due|until)\s+((?:end of )?(?:today|tomorrow|eod|eow|week|this week|next week|next month|end of month|monday|tuesday|wednesday|thursday|friday|saturday|sunday|[a-z]+ \d{1,2}(?:st|nd|rd|th)?|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)|in \d+ (?:days?|weeks?))", re.I)
OWNER_PAT = re.compile(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+)?)(?:,| will| should| needs to| has to| is going to| can you| could you| to)\b")
NOT_NAMES = {"someone", "somebody", "everyone", "anyone", "we", "i", "let", "please", "can", "could", "open", "thanks", "great", "yes", "no", "ok", "okay", "the", "this", "that", "it", "also", "and", "then", "action", "todo", "team"}


class MeetingIn(AgentInput):
    transcript: str | None = Field(default=None, max_length=300_000)
    meeting_id: str | None = None
    title: str | None = None
    meeting_date: str | None = None
    attendees: list[str] = Field(default_factory=list)
    create_tasks: bool = True


class RawItem(BaseModel):
    kind: str  # action|decision|question
    text: str
    owner_mention: str | None = None
    deadline_phrase: str | None = None
    line_refs: list[int]


class Extraction(BaseModel):
    items: list[RawItem] = Field(default_factory=list)


class ActionItem(BaseModel):
    text: str
    owner_mention: str | None
    owner_resolved: dict[str, Any] | None
    owner_status: str  # resolved|ambiguous|unknown|none
    deadline_phrase: str | None
    deadline: str | None
    deadline_status: str
    line_refs: list[int]
    quote: str
    needs_clarification: list[str]


class MeetingOut(BaseModel):
    meeting_id: str | None
    title: str | None
    decisions: list[dict[str, Any]]
    action_items: list[ActionItem]
    open_questions: list[dict[str, Any]]
    tasks_proposed: int
    clarifications_needed: int
    line_count: int


def heuristic_extract(lines: list[dict[str, Any]]) -> Extraction:
    items: list[RawItem] = []
    for ln in lines:
        t = ln["text"]
        if DECISION_PAT.search(t):
            items.append(RawItem(kind="decision", text=t[:300], line_refs=[ln["line"]]))
            continue
        if QUESTION_PAT.search(t) and not ACTION_PAT.search(t):
            items.append(RawItem(kind="question", text=t[:300], line_refs=[ln["line"]]))
            continue
        if ACTION_PAT.search(t):
            owner = None
            for om in OWNER_PAT.finditer(t):
                if om.group(1).split()[0].lower() not in NOT_NAMES:
                    owner = om.group(1)
                    break
            if not owner and re.match(r"^\s*i('| wi)ll\b", t, re.I) and ln["speaker"]:
                owner = ln["speaker"]
            dm = DEADLINE_PAT.search(t)
            items.append(RawItem(kind="action", text=t[:300], owner_mention=owner, deadline_phrase=dm.group(0) if dm else None, line_refs=[ln["line"]]))
    return Extraction(items=items)


@register
class MeetingToExecutionAgent(BaseAgent):
    spec = AgentSpec(
        key="meeting_to_execution",
        name="Meeting-to-Execution Agent",
        department="operations",
        version="1.2.0",
        description="Turns authorised meeting transcripts into evidence-linked decisions, action items with directory-resolved owners and deterministic deadlines, and open questions.",
        use_cases=["Post-meeting task creation", "Decision logs", "Follow-up clarifications"],
        input_model=MeetingIn,
        output_model=MeetingOut,
        allowed_tools=["workspace.get_transcript", "workspace.directory_lookup", "platform.create_task"],
        permission_scopes=["workspace:read", "tasks:write"],
        policies=["directory_resolved_owners_only", "deterministic_deadlines", "evidence_linked", "clarify_when_ambiguous"],
        timeout_seconds=120,
        token_budget=24000,
        risk_level="low",
        baseline_minutes_saved=25,
    )

    def run(self, ctx: AgentContext, payload: MeetingIn, services: AgentServices) -> AgentResult:  # type: ignore[override]
        result = AgentResult(status="completed")
        transcript, title, attendees, mdate = payload.transcript, payload.title, list(payload.attendees), parse_dt(payload.meeting_date)
        if not transcript and payload.meeting_id:
            try:
                m = services.tools.call("workspace.get_transcript", meeting_id=payload.meeting_id)
                transcript, title = m.get("transcript"), title or m.get("title")
                attendees = attendees or m.get("attendees", [])
                mdate = mdate or parse_dt(m.get("date"))
                result.add_evidence(f"meeting:{payload.meeting_id}", excerpt=title, source_type="workspace")
            except NotFound:
                result.status = "needs_input"
                result.missing_information = [f"Transcript for meeting {payload.meeting_id} is not available"]
                result.data = MeetingOut(meeting_id=payload.meeting_id, title=title, decisions=[], action_items=[], open_questions=[], tasks_proposed=0, clarifications_needed=1, line_count=0).model_dump()
                result.summary = "No transcript available"
                return result
        if not transcript:
            result.status = "needs_input"
            result.missing_information = ["A transcript or meeting_id is required"]
            result.data = MeetingOut(meeting_id=payload.meeting_id, title=title, decisions=[], action_items=[], open_questions=[], tasks_proposed=0, clarifications_needed=1, line_count=0).model_dump()
            result.summary = "No transcript provided"
            return result
        base = mdate or ctx.now
        lines = number_lines(transcript)
        by_line = {ln["line"]: ln for ln in lines}
        wrapped = guard_untrusted(result, "\n".join(f"L{ln['line']} {ln['speaker'] or '?'}: {ln['text']}" for ln in lines), "meeting_transcript")
        extraction = services.structured(
            task="meeting_extraction", schema=Extraction,
            system="Extract action items (kind=action, with owner_mention exactly as named in the transcript and the deadline phrase verbatim), decisions (kind=decision) and open questions (kind=question). Cite line numbers. Do not infer owners or dates that are not stated.",
            user=wrapped, heuristic=lambda: heuristic_extract(lines),
        )
        valid = [i for i in extraction.items if i.line_refs and all(n in by_line for n in i.line_refs)]
        if len(valid) < len(extraction.items):
            result.warnings.append(f"Dropped {len(extraction.items) - len(valid)} item(s) with invalid line references")

        decisions, questions, actions = [], [], []
        clarifications = 0
        cache: dict[str, dict[str, Any]] = {}
        for item in valid:
            quote = by_line[item.line_refs[0]]["text"][:200]
            ref = f"transcript:line:{item.line_refs[0]}"
            result.add_evidence(ref, excerpt=quote, source_type="transcript")
            if item.kind == "decision":
                decisions.append({"text": item.text, "line_refs": item.line_refs, "quote": quote})
                continue
            if item.kind == "question":
                questions.append({"text": item.text, "line_refs": item.line_refs, "quote": quote})
                continue
            needs: list[str] = []
            owner_resolved, owner_status = None, "none"
            if item.owner_mention:
                key = item.owner_mention.lower()
                if key not in cache:
                    cache[key] = services.tools.call("workspace.directory_lookup", name=item.owner_mention)
                lookup = cache[key]
                if lookup.get("matches") and not lookup.get("ambiguous"):
                    e = lookup["matches"][0]
                    owner_resolved, owner_status = {"id": e.get("id"), "name": e.get("name"), "email": e.get("email")}, "resolved"
                    result.add_evidence(f"directory:{e.get('id')}", excerpt=e.get("name"), source_type="directory")
                elif lookup.get("matches"):
                    owner_status = "ambiguous"
                    needs.append(f"Owner '{item.owner_mention}' matches several people: {', '.join(m.get('name', '') for m in lookup['matches'][:3])}")
                else:
                    owner_status = "unknown"
                    needs.append(f"Owner '{item.owner_mention}' not found in the directory")
            else:
                needs.append("No owner stated")
            deadline, dstatus = resolve_deadline(item.deadline_phrase, base)
            if dstatus == "ambiguous":
                needs.append(f"Deadline '{item.deadline_phrase}' is ambiguous")
            elif dstatus == "none":
                needs.append("No deadline stated")
            if needs:
                clarifications += 1
            actions.append(ActionItem(text=item.text, owner_mention=item.owner_mention, owner_resolved=owner_resolved, owner_status=owner_status, deadline_phrase=item.deadline_phrase, deadline=deadline.isoformat() if deadline else None, deadline_status=dstatus, line_refs=item.line_refs, quote=quote, needs_clarification=needs))

        proposed = 0
        if payload.create_tasks:
            for a in actions:
                refs = [f"transcript:line:{n}" for n in a.line_refs]
                desc = f"From meeting{': ' + title if title else ''}\nQuote: \"{a.quote}\"" + (("\n\nNEEDS CLARIFICATION: " + "; ".join(a.needs_clarification)) if a.needs_clarification else "")
                result.proposed_actions.append(ProposedAction(action_type="platform.create_task", tool_key="platform.create_task", payload={"title": a.text[:200], "description": desc, "priority": "medium", "owner_user_id": None, "owner_name": a.owner_resolved["name"] if a.owner_resolved else None, "due_at": a.deadline, "evidence_refs": refs, "labels": ["meeting"] + (["needs-clarification"] if a.needs_clarification else [])}, reason="Action item extracted from transcript", risk_level="low", evidence_refs=refs, estimated_minutes_saved=4))
                proposed += 1
        for a in actions:
            for n in a.needs_clarification:
                result.missing_information.append(f"'{a.text[:60]}': {n}")
        result.data = MeetingOut(meeting_id=payload.meeting_id, title=title, decisions=decisions, action_items=actions, open_questions=questions, tasks_proposed=proposed, clarifications_needed=clarifications, line_count=len(lines)).model_dump()
        result.summary = f"{len(decisions)} decision(s), {len(actions)} action item(s) ({clarifications} need clarification), {len(questions)} open question(s)"
        result.confidence = 0.85 if actions and clarifications < len(actions) else 0.6
        result.estimated_minutes_saved = self.spec.baseline_minutes_saved
        return result
