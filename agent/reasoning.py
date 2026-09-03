"""
Feeds the collected OSINT data (news + SEC filings + price context) to Gemini
to produce a transparent, auditable 'Decision Card'.

Key design choice: instead of free text, we force Gemini into a structured
JSON "function call" (tool_config mode=ANY). This guarantees every decision
card follows the same template, is auditable, and renders consistently in the UI.
"""
from typing import Dict, List

from google import genai
from google.genai import types

from config import GEMINI_API_KEY, GEMINI_MODEL

_client = genai.Client(api_key=GEMINI_API_KEY)

DECISION_CARD_FUNCTION = types.FunctionDeclaration(
    name="emit_decision_card",
    description="Produces a structured, transparent OSINT analysis card.",
    parameters={
        "type": "OBJECT",
        "properties": {
            "event_summary": {
                "type": "STRING",
                "description": "A 2-3 sentence summary of the event in your own words. Do not quote the source verbatim.",
            },
            "event_type": {
                "type": "STRING",
                "enum": [
                    "earnings", "insider_activity", "regulatory",
                    "product", "macro", "litigation", "other",
                ],
            },
            "sentiment": {"type": "STRING", "enum": ["bullish", "bearish", "neutral"]},
            "confidence_score": {
                "type": "INTEGER",
                "description": "0-100: how reliable this signal is as a basis for a trading decision",
            },
            "already_priced_in": {
                "type": "BOOLEAN",
                "description": "Whether recent price/volume action suggests the information is already reflected in the market",
            },
            "reasoning_steps": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
                "description": "Short, ordered sentences explaining step by step how the decision was reached (for the audit trail)",
            },
            "risk_flags": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
                "description": "Risks worth flagging: low volume, single source, possible manipulation, etc.",
            },
        },
        "required": [
            "event_summary", "event_type", "sentiment", "confidence_score",
            "already_priced_in", "reasoning_steps", "risk_flags",
        ],
    },
)

DECISION_CARD_TOOL = types.Tool(function_declarations=[DECISION_CARD_FUNCTION])


def _format_sources(news_items: List[Dict], filings: List[Dict]) -> str:
    lines = []
    if news_items:
        lines.append("NEWS:")
        for n in news_items:
            lines.append(f"- [{n.get('created_at')}] {n.get('headline')} (source: {n.get('source')}, url: {n.get('url')})")
    if filings:
        lines.append("\nOFFICIAL SEC FILINGS:")
        for f in filings:
            lines.append(f"- [{f.get('filed_at')}] {f.get('form')} - {f.get('company')} (url: {f.get('url')})")
    if not lines:
        lines.append("(No OSINT sources found for this symbol recently.)")
    return "\n".join(lines)


def build_decision_card(symbol: str, news_items: List[Dict], filings: List[Dict],
                         price_context: Dict) -> Dict:
    """
    Runs Gemini as a research analyst and returns a structured decision card.
    The returned dict matches the DECISION_CARD_FUNCTION schema plus 'symbol' and 'sources'.
    """
    sources_text = _format_sources(news_items, filings)

    prompt = f"""You are a careful, skeptical financial research analyst. Below you will find
the OSINT (open-source intelligence) data collected for {symbol} stock, along with
recent price/volume context. Your task is to evaluate this and produce a structured
decision card.

Rules:
- Do NOT quote sources verbatim; summarize in your own words.
- If the data is weak (single source, stale date, low volume), flag this in risk_flags
  and keep confidence_score low.
- Judge already_priced_in from the percent change and volume ratio in price_context:
  if a large price move has already happened, the news is likely already priced in.
- reasoning_steps should be clear enough that another person can follow your chain of logic.

OSINT SOURCES:
{sources_text}

PRICE/VOLUME CONTEXT:
{price_context}
"""

    response = _client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[DECISION_CARD_TOOL],
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode="ANY",
                    allowed_function_names=["emit_decision_card"],
                )
            ),
        ),
    )

    for candidate in response.candidates or []:
        for part in candidate.content.parts:
            fc = getattr(part, "function_call", None)
            if fc and fc.name == "emit_decision_card":
                card = dict(fc.args)
                card["symbol"] = symbol
                card["sources"] = {"news": news_items, "filings": filings, "price_context": price_context}
                return card

    raise RuntimeError("Gemini did not return a structured decision card.")
