import os
import json as _json
import logging
from langchain_core.messages import HumanMessage, SystemMessage
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
    '{{"score": <integer 1-10>, "feedback": "<2-3 sentences of coaching feedback>"}}\n\n'
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
            system_prompt = CRITERION_PROMPT_TEMPLATE.format(
                description=criterion["description"],
                success_condition=criterion["success_condition"],
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
            f"- {c['name']}: {c['score']}/10 — {c['feedback']}"
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
