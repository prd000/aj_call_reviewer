import os
import json as _json
import logging
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from modules.llm_config import get_llm, get_llm_api_key
from prompts import load_prompt

logger = logging.getLogger(__name__)

STUB_REVIEW = {
    "summary": (
        "This was a solid introductory call that demonstrated good fundamentals in "
        "rapport building and needs discovery. The advisor asked thoughtful open-ended "
        "questions and listened actively to the prospect's concerns about retirement "
        "planning. There is room to improve on solution presentation specificity and "
        "to address objections more proactively before they arise."
    ),
    "categories": [
        {
            "name": "Rapport Building",
            "score": 8,
            "max_score": 10,
            "feedback": (
                "The advisor opened warmly and created a comfortable atmosphere for the "
                "prospect to share openly. Good use of affirmations and acknowledgment of "
                "the prospect's existing effort. Consider personalizing the opening with "
                "a specific reference to something you know about the prospect's situation."
            ),
        },
        {
            "name": "Needs Discovery",
            "score": 7,
            "max_score": 10,
            "feedback": (
                "Strong questioning technique with good use of open-ended questions about "
                "retirement timeline and existing accounts. The advisor uncovered the "
                "prospect's Social Security gap concern organically. Dig deeper on income "
                "needs and current lifestyle expectations to sharpen the planning picture."
            ),
        },
        {
            "name": "Solution Presentation",
            "score": 6,
            "max_score": 10,
            "feedback": (
                "The advisor referenced a 'comprehensive income strategy' but didn't "
                "elaborate on specifics or make it tangible for the prospect. Present "
                "at least one concrete example or case study to illustrate the solution. "
                "Tie the solution directly back to the Social Security gap concern the "
                "prospect raised."
            ),
        },
        {
            "name": "Objection Handling",
            "score": 5,
            "max_score": 10,
            "feedback": (
                "No direct objections were raised in this call, so the advisor did not "
                "have a chance to demonstrate objection handling skills. Proactively "
                "surface and address common concerns — fee transparency, risk tolerance, "
                "and liquidity — before the prospect raises them to build trust and "
                "demonstrate expertise."
            ),
        },
    ],
}


class LLMUnavailableError(RuntimeError):
    pass


MAX_CHAT_HISTORY = 8


def _format_transcript_labeled(transcript: list[dict], speaker_map: dict) -> str:
    lines = []
    for segment in transcript:
        timestamp = segment.get("timestamp", "")
        text = segment.get("text", "")
        spk = segment.get("speaker")
        if spk is not None:
            label = speaker_map.get(str(spk), f"Speaker {spk + 1}")
        else:
            label = "Speaker"
        lines.append(f"[{timestamp}] {label}: {text}")
    return "\n".join(lines)


def _format_framework(framework: dict | None) -> str:
    """
    Render the review framework (the criteria the call was scored against) as a
    readable block for the chat system prompt. Returns "" when no framework is
    available (e.g. legacy records), so the prompt section is simply omitted.
    """
    if not framework:
        return ""
    criteria = framework.get("criteria") or []
    if not criteria:
        return ""

    name = framework.get("template_name") or "Review Framework"
    lines = [f"Review Framework: {name}"]
    for i, criterion in enumerate(criteria, 1):
        title = criterion.get("title") or criterion.get("description", "")[:60]
        description = criterion.get("description", "")
        success = criterion.get("success_condition", "")
        max_score = criterion.get("max_score", 10)
        lines.append(f"{i}. {title} (max score {max_score})")
        if description:
            lines.append(f"   Criteria: {description}")
        if success:
            lines.append(f"   Success when: {success}")
    return "\n".join(lines) + "\n\n"


def _format_review_results(review_results: dict | None) -> str:
    """
    Render the official review (the scores + written feedback this call received)
    as a readable block for the chat system prompt. Returns "" when no review is
    available (e.g. a call still processing, or a legacy record), so the prompt
    section is simply omitted.
    """
    if not review_results:
        return ""
    categories = review_results.get("categories") or []
    summary = (review_results.get("summary") or "").strip()
    if not categories and not summary:
        return ""

    lines = []
    if summary:
        lines.append(f"Overall summary: {summary}")
        lines.append("")
    if categories:
        lines.append("Scores and feedback by criterion:")
        for c in categories:
            name = c.get("name", "")
            score = c.get("score")
            max_score = c.get("max_score", 10)
            feedback = (c.get("feedback") or "").strip()
            if score is not None:
                lines.append(f"- {name}: {score}/{max_score}")
            else:
                lines.append(f"- {name}:")
            if feedback:
                lines.append(f"  {feedback}")
    return "\n".join(lines) + "\n\n"


def chat_about_transcript(
    transcript: list[dict],
    speaker_map: dict,
    messages: list[dict],
    framework: dict | None = None,
    review_results: dict | None = None,
) -> str:
    """
    Respond to a user question grounded strictly in the given transcript, with the
    review framework and this call's official review (scores + feedback) available
    as additional sources.

    messages: [{"role": "user"|"assistant", "content": str}, ...], last entry is the new user turn.
    framework: the review framework snapshot (template_name + criteria) the call was scored
        against; optional (omitted from the prompt when absent).
    review_results: the call's generated review ({"summary", "categories": [...]}); optional
        (omitted from the prompt when absent — e.g. a call still processing or a legacy record).
    Raises LLMUnavailableError if no API key is configured.
    """
    if not get_llm_api_key():
        raise LLMUnavailableError("No LLM API key is configured.")

    transcript_text = _format_transcript_labeled(transcript, speaker_map)
    framework_section = _format_framework(framework)
    review_section = _format_review_results(review_results)
    system_prompt = load_prompt("chat.system").format(
        framework_section=framework_section,
        review_section=review_section,
        transcript=transcript_text,
    )

    if len(transcript) > 2000:
        logger.warning(
            "chat_about_transcript: transcript has %d segments — may approach token limit",
            len(transcript),
        )

    role_map = {"user": HumanMessage, "assistant": AIMessage}
    history = messages[-MAX_CHAT_HISTORY:]
    lc_messages = [SystemMessage(content=system_prompt)] + [
        role_map[m["role"]](content=m["content"]) for m in history
    ]

    llm = get_llm(temperature=0.0)
    return llm.invoke(lc_messages).content.strip()


def identify_speakers(transcript: list[dict]) -> dict:
    """
    Sample the first 10 transcript segments and make one LLM call to determine
    which speaker index is the advisor and which is the prospect.

    Returns a dict mapping speaker int to role label, e.g. {0: "Advisor", 1: "Prospect"}.
    Returns an empty dict if identification fails or the LLM API key is absent.
    """
    api_key = get_llm_api_key()
    if not api_key:
        logger.warning("LLM API key not set; skipping speaker identification.")
        return {}

    sample = [seg for seg in transcript[:20] if seg.get("speaker") is not None]
    speakers_present = {seg["speaker"] for seg in sample}
    if len(speakers_present) < 2:
        logger.warning("Fewer than 2 speakers found in sample; skipping speaker identification.")
        return {}

    try:
        llm = get_llm(temperature=0.0)

        sample_text = "\n".join(
            f"[Speaker {seg['speaker']}] {seg['text']}" for seg in sample
        )

        messages = [
            SystemMessage(content=load_prompt("speaker_id.system")),
            HumanMessage(content=load_prompt("speaker_id.user").format(sample_text=sample_text)),
        ]
        response = llm.invoke(messages)
        content = response.content.strip()

        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(line for line in lines if not line.startswith("```")).strip()

        parsed = _json.loads(content)
        speaker_map = {}
        if "advisor" in parsed:
            speaker_map[int(parsed["advisor"])] = "Advisor"
        if "prospect" in parsed:
            speaker_map[int(parsed["prospect"])] = "Prospect"

        logger.info("Speaker identification result: %s", speaker_map)
        return speaker_map

    except Exception as exc:
        logger.warning("Speaker identification failed: %s", exc)
        return {}


def _format_transcript(transcript: list[dict]) -> str:
    lines = []
    for segment in transcript:
        timestamp = segment.get("timestamp", "")
        text = segment.get("text", "")
        lines.append(f"[{timestamp}] {text}")
    return "\n".join(lines)


def review_call(transcript: list[dict], criteria: list[dict]) -> dict:
    """
    Generate a structured review for a call transcript.

    Each criterion dict must have 'description' and 'success_condition' keys.
    One LLM call is made per criterion; results are assembled into a scored
    category list with an overall summary.

    Falls back to stub data when the LLM API key is absent or criteria is empty.

    Returns:
        {
            "summary": "...",
            "categories": [
                {"name": "...", "score": 7, "feedback": "..."},
                ...
            ]
        }
    """
    api_key = get_llm_api_key()

    if not api_key:
        logger.warning("LLM API key is not set. Returning stub review for development.")
        return STUB_REVIEW

    if not criteria:
        logger.warning("No criteria provided. Returning stub review.")
        return STUB_REVIEW

    try:
        llm = get_llm(temperature=0.3)

        transcript_text = _format_transcript(transcript)
        categories = []

        for criterion in criteria:
            max_score = criterion.get("max_score", 10)
            system_prompt = load_prompt("criterion.system").format(
                description=criterion["description"],
                success_condition=criterion["success_condition"],
                max_score=max_score,
            )
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=load_prompt("criterion.user").format(transcript=transcript_text)),
            ]
            response = llm.invoke(messages)
            content = response.content.strip()

            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(
                    line for line in lines if not line.startswith("```")
                ).strip()

            parsed = _json.loads(content)
            categories.append(
                {
                    "name": criterion.get("title") or criterion["description"][:60],
                    "score": int(parsed["score"]),
                    "max_score": max_score,
                    "feedback": parsed["feedback"],
                }
            )

        scores_text = "\n".join(
            f"- {c['name']}: {c['score']}/{c.get('max_score', 10)} — {c['feedback']}"
            for c in categories
        )
        summary_messages = [
            SystemMessage(content=load_prompt("summary.system")),
            HumanMessage(
                content=load_prompt("summary.user").format(
                    transcript=transcript_text,
                    scores_text=scores_text,
                )
            ),
        ]
        summary_response = llm.invoke(summary_messages)

        return {
            "summary": summary_response.content.strip(),
            "categories": categories,
        }

    except Exception as exc:
        logger.error("Review generation failed: %s", exc, exc_info=True)
        raise
