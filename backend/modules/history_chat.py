import logging
from datetime import datetime
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from modules.llm_config import get_llm, get_llm_api_key
from modules.reviewer import LLMUnavailableError, MAX_CHAT_HISTORY, _format_transcript_labeled
from modules.scoring import overall_score as _calc_overall_score
from prompts import load_prompt

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 12
MAX_TRANSCRIPT_READS = 10

# Character budget for summary text in the triage table. Calls beyond the budget
# get scores-only rows so the system prompt stays within a reasonable size.
TRIAGE_SUMMARY_BUDGET_CHARS = 60_000


def _format_date(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return f"{dt.strftime('%b')} {dt.day}, {dt.year}"
    except Exception:
        return iso[:10] if iso else "—"


def _compute_overall_score(review: dict) -> str:
    score, _ = _calc_overall_score(review.get("review"))
    if score is None:
        return "—"
    return f"{score}/10"


def _build_handle_map(scoped_reviews: list[dict]) -> dict[str, dict]:
    """Build an ordered dict of handle → review, newest-first (C1 = most recent)."""
    sorted_reviews = sorted(
        scoped_reviews,
        key=lambda r: r.get("created_at") or "",
        reverse=True,
    )
    return {f"C{i + 1}": r for i, r in enumerate(sorted_reviews)}


def _build_triage_table(handle_map: dict[str, dict]) -> str:
    """
    Render the triage table string. Summaries are included newest-first until
    TRIAGE_SUMMARY_BUDGET_CHARS is consumed; older calls get scores-only rows.
    """
    lines: list[str] = []
    chars_used = 0
    n_with_summary = 0
    n_scores_only = 0

    for handle, review in handle_map.items():
        meta = review.get("metadata", {})
        framework = review.get("framework") or {}

        advisor = meta.get("advisor_name") or "Unknown"
        prospect = meta.get("prospect_name") or "—"
        firm = meta.get("firm") or "—"
        date = _format_date(review.get("created_at"))
        outcome = meta.get("call_outcome") or "—"
        template = framework.get("template_name") or "—"
        overall = _compute_overall_score(review)

        categories = (review.get("review") or {}).get("categories", [])
        scores = ", ".join(
            f"{c['name']}: {c.get('score', '?')}/{c.get('max_score', 10)}"
            for c in categories
        )

        summary = (review.get("review") or {}).get("summary") or ""

        if summary and chars_used + len(summary) <= TRIAGE_SUMMARY_BUDGET_CHARS:
            summary_line = f"  Summary: {summary}"
            chars_used += len(summary)
            n_with_summary += 1
        else:
            summary_line = "  Summary: [omitted — call get_feedback for detail]"
            n_scores_only += 1

        lines.append(
            f"{handle} | {advisor} | Prospect: {prospect} | {firm} | {date} | Outcome: {outcome} | Template: {template}\n"
            f"  Overall: {overall} | {scores}\n"
            f"{summary_line}"
        )

    table = "\n\n".join(lines)
    if n_scores_only > 0:
        total = n_with_summary + n_scores_only
        header = (
            f"[Showing summaries for {n_with_summary} of {total} most recent calls; "
            f"remaining {n_scores_only} have scores only.]\n\n"
        )
        return header + table
    return table


def _execute_tool(name: str, args: dict, handle_map: dict[str, dict]) -> str:
    call_handle = (args.get("call") or "").strip().upper()
    if call_handle not in handle_map:
        valid = ", ".join(handle_map.keys())
        return f"Error: '{call_handle}' is not in the scoped call set. Valid handles: {valid}"

    review = handle_map[call_handle]

    if name == "get_feedback":
        categories = (review.get("review") or {}).get("categories", [])
        if not categories:
            return "No feedback data available for this call."
        parts = [
            f"{c['name']} ({c.get('score', '?')}/{c.get('max_score', 10)}): {c.get('feedback', '—')}"
            for c in categories
        ]
        return "\n\n".join(parts)

    if name == "read_transcript":
        transcript = review.get("transcript") or []
        if not transcript:
            return "No transcript available for this call."
        speaker_map = review.get("speaker_map") or {}
        return _format_transcript_labeled(transcript, speaker_map)

    return f"Error: Unknown tool '{name}'"


def chat_over_reviews(scoped_reviews: list[dict], messages: list[dict]) -> str:
    """
    Agentic cross-call pattern analysis over a scoped set of completed reviews.

    scoped_reviews: full review dicts, already visibility-filtered and status=complete.
    messages: [{"role": "user"|"assistant", "content": str}, ...] with the latest user
        turn as the last entry.
    Returns the agent's final answer as a plain string.
    Raises LLMUnavailableError if no API key is configured.
    """
    if not get_llm_api_key():
        raise LLMUnavailableError("No LLM API key is configured.")

    handle_map = _build_handle_map(scoped_reviews)
    triage_table = _build_triage_table(handle_map)
    system_prompt = load_prompt("history_chat.system").format(triage_table=triage_table)

    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_feedback",
                "description": (
                    "Get per-criterion coaching feedback for a specific call. "
                    "Use when you need to understand why a call scored a certain way."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "call": {
                            "type": "string",
                            "description": "The call handle from the triage table (e.g. 'C1', 'C3').",
                        }
                    },
                    "required": ["call"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_transcript",
                "description": (
                    "Read the full labeled transcript for a specific call. "
                    "Use sparingly — only for exact quotes or to verify what was said."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "call": {
                            "type": "string",
                            "description": "The call handle from the triage table (e.g. 'C1', 'C3').",
                        }
                    },
                    "required": ["call"],
                },
            },
        },
    ]

    llm = get_llm(temperature=0.2, role="history_chat")
    llm_with_tools = llm.bind_tools(tools)

    role_map: dict[str, Any] = {"user": HumanMessage, "assistant": AIMessage}
    trimmed = messages[-MAX_CHAT_HISTORY:] if len(messages) > MAX_CHAT_HISTORY else messages
    lc_messages: list[Any] = [SystemMessage(content=system_prompt)] + [
        role_map[m["role"]](content=m["content"]) for m in trimmed
    ]

    transcript_reads = 0

    for iteration in range(MAX_ITERATIONS):
        response = llm_with_tools.invoke(lc_messages)
        lc_messages.append(response)

        if not response.tool_calls:
            return response.content.strip() or "I was unable to generate a response."

        for tc in response.tool_calls:
            tool_name = tc["name"]
            tool_args = tc.get("args", {})
            tool_call_id = tc["id"]

            if tool_name == "read_transcript":
                if transcript_reads >= MAX_TRANSCRIPT_READS:
                    result = (
                        "Error: Maximum transcript reads reached. "
                        "Please base your answer on the summaries and feedback already gathered."
                    )
                else:
                    result = _execute_tool(tool_name, tool_args, handle_map)
                    transcript_reads += 1
            else:
                result = _execute_tool(tool_name, tool_args, handle_map)

            lc_messages.append(ToolMessage(content=result, tool_call_id=tool_call_id))

    # Hit MAX_ITERATIONS — force a plain-text answer without tools
    logger.warning(
        "history_chat: hit MAX_ITERATIONS=%d after %d transcript read(s); forcing final answer",
        MAX_ITERATIONS,
        transcript_reads,
    )
    lc_messages.append(
        HumanMessage(
            content="Please provide your best answer now based on everything you have gathered. Do not call any more tools."
        )
    )
    base_llm = get_llm(temperature=0.2, role="history_chat")
    final = base_llm.invoke(lc_messages)
    return (
        final.content or "I was unable to generate a complete answer within the iteration limit."
    ).strip()
