import os
import json as _json
import logging
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from modules.llm_config import get_llm, get_llm_api_key

logger = logging.getLogger(__name__)

SPEAKER_ID_PROMPT = (
    "You are analyzing a financial advisor sales call transcript. "
    "Based on the content of these opening segments, identify which speaker number is the "
    "financial advisor/salesperson and which is the prospect/client. "
    "Speakers are identified by their 0-indexed speaker number. "
    "Respond with a JSON object in this exact format:\n"
    '{{"advisor": <speaker_number>, "prospect": <speaker_number>}}\n\n'
    "Do not include anything outside the JSON object."
)

CRITERION_PROMPT_TEMPLATE = (
    "You are a call reviewer for financial advisors. Your current job is to analyze "
    "this call recording based on the following criteria:\n\n"
    "Criteria: {description}\n\n"
    "You know this has been successfully accomplished when: {success_condition}\n\n"
    "Respond with a JSON object in this exact format:\n"
    '{{"score": <integer 1-{max_score}>, "feedback": "<2-3 sentences of coaching feedback>"}}\n\n'
    "Do not include anything outside the JSON object."
)

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


CHAT_SYSTEM_PROMPT_TEMPLATE = (
    "You are a call review assistant. You have been given a complete transcript of a "
    "financial advisor's sales call{framework_clause}.\n\n"
    "Your sole job is to answer questions about THIS call. You must:\n"
    "- Base all factual claims about what was said ONLY on the transcript. Do not use "
    "outside knowledge.\n"
    "- If a question cannot be answered from the transcript or the review framework, "
    'reply exactly: "I can only answer questions about this call\'s transcript."\n'
    "- Cite EVERY relevant moment with its timestamp and a short verbatim quote, "
    'e.g. 00:01:23 — "the advisor said..."\n'
    "- Timestamps must exactly match a bracketed line in the transcript below.\n"
    "- You may offer light interpretation ONLY when it is directly anchored to a "
    "cited, timestamped quote.\n"
    "- Refer to speakers by their role label (Advisor, Prospect, etc.) as shown in "
    "the transcript.\n"
    "- When a question relates to how the call was evaluated, use the review framework "
    "below for context, but still cite transcript evidence for any claim about what "
    "actually happened on the call.\n\n"
    "{framework_section}"
    "Transcript:\n{transcript}"
)

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


def chat_about_transcript(
    transcript: list[dict],
    speaker_map: dict,
    messages: list[dict],
    framework: dict | None = None,
) -> str:
    """
    Respond to a user question grounded strictly in the given transcript, with the
    review framework available as evaluation context.

    messages: [{"role": "user"|"assistant", "content": str}, ...], last entry is the new user turn.
    framework: the review framework snapshot (template_name + criteria) the call was scored
        against; optional (omitted from the prompt when absent).
    Raises LLMUnavailableError if no API key is configured.
    """
    if not get_llm_api_key():
        raise LLMUnavailableError("No LLM API key is configured.")

    transcript_text = _format_transcript_labeled(transcript, speaker_map)
    framework_section = _format_framework(framework)
    framework_clause = (
        ", along with the review framework it was evaluated against"
        if framework_section
        else ""
    )
    system_prompt = CHAT_SYSTEM_PROMPT_TEMPLATE.format(
        framework_clause=framework_clause,
        framework_section=framework_section,
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

    sample = [seg for seg in transcript[:10] if seg.get("speaker") is not None]
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
            SystemMessage(content=SPEAKER_ID_PROMPT),
            HumanMessage(content=f"Transcript sample:\n{sample_text}"),
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
            system_prompt = CRITERION_PROMPT_TEMPLATE.format(
                description=criterion["description"],
                success_condition=criterion["success_condition"],
                max_score=max_score,
            )
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"Transcript:\n{transcript_text}"),
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

        summary_prompt = (
            "You are a sales coach for financial advisors. "
            "Given the following call transcript and category scores, "
            "write a 3-4 sentence overall summary of the advisor's performance. "
            "Be specific, constructive, and actionable. "
            "Return only the summary text, no JSON."
        )
        scores_text = "\n".join(
            f"- {c['name']}: {c['score']}/{c.get('max_score', 10)} — {c['feedback']}"
            for c in categories
        )
        summary_messages = [
            SystemMessage(content=summary_prompt),
            HumanMessage(
                content=f"Transcript:\n{transcript_text}\n\nCategory Scores:\n{scores_text}"
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
