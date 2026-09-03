"""
Multi-agent decision pipeline: three specialized Analyst agents (News,
Filings, Price) each produce an INDEPENDENT opinion from only their own
slice of the OSINT data - they never see each other's output. A Critic /
Synthesizer agent then combines the three opinions into the final Decision
Card, explicitly flagging any disagreement between analysts as a risk_flag
instead of silently averaging it away.

Every Gemini call uses forced structured function-calling (tool_config
mode=ANY), never free text, so every agent's output is auditable and
consistently shaped. Calls are retried automatically since the live model
has shown transient 503 "high demand" errors during testing.

Actor-Critic pattern: every agent's raw JSON is run through a deterministic
(non-LLM) Reviewer before it's accepted. The Reviewer never judges the
substance of an opinion - only that the output actually satisfies the
schema (valid enum values, confidence in range, reasoning not empty/trivial).
If it doesn't, the same agent is re-prompted with the specific validation
errors (REJECT_WITH_FEEDBACK) up to MAX_REVISIONS times; if it still can't
produce a valid answer, that counts as FAIL and the exception propagates.
Kept deterministic on purpose - a second LLM call per node would double
Gemini traffic and, given the transient 503s already observed live, add
fragility for no real benefit on the happy path.
"""
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

from google import genai
from google.genai import types

from config import GEMINI_API_KEY, GEMINI_MODEL

_client = genai.Client(api_key=GEMINI_API_KEY)

MAX_REVISIONS = 2


def _call_gemini(prompt: str, tool: types.Tool, function_name: str,
                  retries: int = 3, delay: float = 6.0) -> Dict:
    """Raw call with retry on transient API errors only (not validation)."""
    last_error = None
    for attempt in range(retries):
        try:
            response = _client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[tool],
                    tool_config=types.ToolConfig(
                        function_calling_config=types.FunctionCallingConfig(
                            mode="ANY",
                            allowed_function_names=[function_name],
                        )
                    ),
                ),
            )
            for candidate in response.candidates or []:
                for part in candidate.content.parts:
                    fc = getattr(part, "function_call", None)
                    if fc and fc.name == function_name:
                        return dict(fc.args)
            raise RuntimeError(f"Gemini did not call {function_name}")
        except Exception as e:
            last_error = e
            if attempt < retries - 1:
                time.sleep(delay)
    raise RuntimeError(f"{function_name} failed after {retries} attempts: {last_error}")


def _run_reviewed(prompt: str, tool: types.Tool, function_name: str,
                   validate) -> Dict:
    """
    Actor-Critic loop: Worker (Gemini) produces JSON, Reviewer (validate())
    checks it deterministically. APPROVE -> return. REJECT_WITH_FEEDBACK ->
    re-prompt with the specific problems, up to MAX_REVISIONS times.
    FAIL -> raise, after MAX_REVISIONS exhausted.
    """
    current_prompt = prompt
    for revision in range(MAX_REVISIONS + 1):
        output = _call_gemini(current_prompt, tool, function_name)
        problems = validate(output)
        if not problems:
            output["_reviewer"] = {"status": "approved", "revisions": revision}
            return output
        current_prompt = prompt + f"""

Your previous answer failed review for these reasons:
{chr(10).join('- ' + p for p in problems)}

Re-emit a corrected, COMPLETE answer via the same function call - fix every issue above.
"""
    raise RuntimeError(f"{function_name}: FAIL - reviewer rejected {MAX_REVISIONS} revisions, "
                        f"last problems: {problems}")


def _validate_common(opinion: Dict) -> List[str]:
    problems = []
    conf = opinion.get("confidence")
    if not isinstance(conf, (int, float)) or not (0 <= conf <= 100):
        problems.append(f"confidence must be a number 0-100, got {conf!r}")
    reasoning = (opinion.get("reasoning") or "").strip()
    if len(reasoning) < 15:
        problems.append("reasoning is missing or too short to be a real justification (min 15 chars)")
    return problems


def _enum_problem(opinion: Dict, field: str, allowed: tuple) -> Optional[str]:
    if opinion.get(field) not in allowed:
        return f"{field} must be one of {allowed}, got {opinion.get(field)!r}"
    return None


# ---------------------------------------------------------------------------
# News Analyst - sees ONLY headlines
# ---------------------------------------------------------------------------

NEWS_ANALYST_FUNCTION = types.FunctionDeclaration(
    name="emit_news_opinion",
    description="Independent opinion based ONLY on the provided news headlines.",
    parameters={
        "type": "OBJECT",
        "properties": {
            "sentiment": {"type": "STRING", "enum": ["bullish", "bearish", "neutral"]},
            "confidence": {"type": "INTEGER", "description": "0-100"},
            "reasoning": {"type": "STRING", "description": "1-3 sentences, your own words, no verbatim quotes"},
            "key_headlines": {
                "type": "ARRAY", "items": {"type": "STRING"},
                "description": "Up to 3 headline summaries that most influenced your opinion",
            },
        },
        "required": ["sentiment", "confidence", "reasoning", "key_headlines"],
    },
)
NEWS_ANALYST_TOOL = types.Tool(function_declarations=[NEWS_ANALYST_FUNCTION])


def _validate_news_opinion(opinion: Dict) -> List[str]:
    problems = _validate_common(opinion)
    p = _enum_problem(opinion, "sentiment", ("bullish", "bearish", "neutral"))
    if p:
        problems.append(p)
    if not isinstance(opinion.get("key_headlines"), list):
        problems.append("key_headlines must be a list of strings")
    return problems


def _analyze_news(symbol: str, news_items: List[Dict]) -> Dict:
    if not news_items:
        return {"sentiment": "neutral", "confidence": 0,
                "reasoning": "No recent news found.", "key_headlines": [],
                "_reviewer": {"status": "skipped", "reason": "no data"}}
    lines = [f"- [{n.get('created_at')}] {n.get('headline')} (source: {n.get('source')})"
             for n in news_items]
    prompt = f"""You are a news sentiment analyst. You have ONLY the headlines below for
{symbol} - no SEC filings, no price data. Judge sentiment purely from this news flow.

NEWS:
{chr(10).join(lines)}
"""
    return _run_reviewed(prompt, NEWS_ANALYST_TOOL, "emit_news_opinion", _validate_news_opinion)


# ---------------------------------------------------------------------------
# Filings Analyst - sees ONLY SEC filings
# ---------------------------------------------------------------------------

FILINGS_ANALYST_FUNCTION = types.FunctionDeclaration(
    name="emit_filings_opinion",
    description="Independent opinion based ONLY on the provided SEC filings.",
    parameters={
        "type": "OBJECT",
        "properties": {
            "sentiment": {"type": "STRING", "enum": ["bullish", "bearish", "neutral"]},
            "confidence": {"type": "INTEGER", "description": "0-100"},
            "reasoning": {"type": "STRING", "description": "1-3 sentences, your own words"},
            "insider_direction": {
                "type": "STRING",
                "enum": ["buying", "selling", "mixed", "none"],
                "description": "Net direction of any Form 4 insider activity seen, 'none' if no Form 4s present",
            },
        },
        "required": ["sentiment", "confidence", "reasoning", "insider_direction"],
    },
)
FILINGS_ANALYST_TOOL = types.Tool(function_declarations=[FILINGS_ANALYST_FUNCTION])


def _validate_filings_opinion(opinion: Dict) -> List[str]:
    problems = _validate_common(opinion)
    p = _enum_problem(opinion, "sentiment", ("bullish", "bearish", "neutral"))
    if p:
        problems.append(p)
    p = _enum_problem(opinion, "insider_direction", ("buying", "selling", "mixed", "none"))
    if p:
        problems.append(p)
    return problems


def _analyze_filings(symbol: str, filings: List[Dict]) -> Dict:
    if not filings:
        return {"sentiment": "neutral", "confidence": 0,
                "reasoning": "No recent SEC filings found.", "insider_direction": "none",
                "_reviewer": {"status": "skipped", "reason": "no data"}}
    lines = [f"- [{f.get('filed_at')}] {f.get('form')} - {f.get('company')}" for f in filings]
    prompt = f"""You are an SEC filings analyst. You have ONLY the filings below for {symbol} -
no news, no price data. Judge sentiment purely from these filings, paying particular
attention to any Form 4 insider buying/selling pattern.

FILINGS:
{chr(10).join(lines)}
"""
    return _run_reviewed(prompt, FILINGS_ANALYST_TOOL, "emit_filings_opinion", _validate_filings_opinion)


# ---------------------------------------------------------------------------
# Price/Momentum Analyst - sees ONLY price/volume context
# ---------------------------------------------------------------------------

PRICE_ANALYST_FUNCTION = types.FunctionDeclaration(
    name="emit_price_opinion",
    description="Independent opinion based ONLY on recent price/volume action.",
    parameters={
        "type": "OBJECT",
        "properties": {
            "momentum_bias": {"type": "STRING", "enum": ["bullish", "bearish", "neutral"]},
            "already_priced_in": {"type": "BOOLEAN"},
            "confidence": {"type": "INTEGER", "description": "0-100"},
            "reasoning": {"type": "STRING", "description": "1-3 sentences, your own words"},
        },
        "required": ["momentum_bias", "already_priced_in", "confidence", "reasoning"],
    },
)
PRICE_ANALYST_TOOL = types.Tool(function_declarations=[PRICE_ANALYST_FUNCTION])


def _validate_price_opinion(opinion: Dict) -> List[str]:
    problems = _validate_common(opinion)
    p = _enum_problem(opinion, "momentum_bias", ("bullish", "bearish", "neutral"))
    if p:
        problems.append(p)
    if not isinstance(opinion.get("already_priced_in"), bool):
        problems.append(f"already_priced_in must be a boolean, got {opinion.get('already_priced_in')!r}")
    return problems


def _analyze_price(symbol: str, price_context: Dict) -> Dict:
    if not price_context.get("available"):
        return {"momentum_bias": "neutral", "already_priced_in": False,
                "confidence": 0, "reasoning": "No price data available.",
                "_reviewer": {"status": "skipped", "reason": "no data"}}
    prompt = f"""You are a price/volume momentum analyst. You have ONLY the data below for
{symbol} - no news, no filings. Judge momentum bias and whether a move already looks
priced in (a large price change on low relative volume suggests the news behind it is
NOT yet reflected; a large move on high relative volume suggests it likely already is).

PRICE/VOLUME CONTEXT:
{price_context}
"""
    return _run_reviewed(prompt, PRICE_ANALYST_TOOL, "emit_price_opinion", _validate_price_opinion)


# ---------------------------------------------------------------------------
# Critic / Synthesizer - combines the three independent opinions
# ---------------------------------------------------------------------------

DECISION_CARD_FUNCTION = types.FunctionDeclaration(
    name="emit_decision_card",
    description="Synthesizes three independent analyst opinions into one transparent OSINT decision card.",
    parameters={
        "type": "OBJECT",
        "properties": {
            "event_summary": {
                "type": "STRING",
                "description": "A 2-3 sentence summary of the event in your own words.",
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
                "description": "0-100: final synthesized confidence, after weighing agreement/disagreement between the three analysts",
            },
            "already_priced_in": {"type": "BOOLEAN"},
            "reasoning_steps": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
                "description": "Ordered sentences explaining the synthesis. MUST explicitly state where the three analysts agreed or disagreed.",
            },
            "risk_flags": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
                "description": "Risks worth flagging. Any material disagreement between the three analysts MUST appear here explicitly.",
            },
        },
        "required": [
            "event_summary", "event_type", "sentiment", "confidence_score",
            "already_priced_in", "reasoning_steps", "risk_flags",
        ],
    },
)

DECISION_CARD_TOOL = types.Tool(function_declarations=[DECISION_CARD_FUNCTION])

_EVENT_TYPES = ("earnings", "insider_activity", "regulatory", "product", "macro", "litigation", "other")


def _validate_decision_card(card: Dict) -> List[str]:
    problems = []
    conf = card.get("confidence_score")
    if not isinstance(conf, (int, float)) or not (0 <= conf <= 100):
        problems.append(f"confidence_score must be a number 0-100, got {conf!r}")
    if len((card.get("event_summary") or "").strip()) < 15:
        problems.append("event_summary is missing or too short")
    p = _enum_problem(card, "event_type", _EVENT_TYPES)
    if p:
        problems.append(p)
    p = _enum_problem(card, "sentiment", ("bullish", "bearish", "neutral"))
    if p:
        problems.append(p)
    if not isinstance(card.get("already_priced_in"), bool):
        problems.append(f"already_priced_in must be a boolean, got {card.get('already_priced_in')!r}")
    if not isinstance(card.get("reasoning_steps"), list) or not card["reasoning_steps"]:
        problems.append("reasoning_steps must be a non-empty list of strings")
    if not isinstance(card.get("risk_flags"), list):
        problems.append("risk_flags must be a list (can be empty)")
    return problems


def build_decision_card(symbol: str, news_items: List[Dict], filings: List[Dict],
                         price_context: Dict) -> Dict:
    """
    Runs three specialized Analyst agents (News/Filings/Price) concurrently -
    each sees ONLY its own slice of the OSINT data and does not know what the
    others concluded - then a Critic agent synthesizes their independent
    opinions into the final Decision Card, explicitly flagging disagreement
    between analysts rather than silently averaging it away.

    Returns a dict matching DECISION_CARD_FUNCTION's schema plus 'symbol',
    'sources', and the raw 'analyst_opinions' (for transparency/audit).
    """
    with ThreadPoolExecutor(max_workers=3) as pool:
        news_future = pool.submit(_analyze_news, symbol, news_items)
        filings_future = pool.submit(_analyze_filings, symbol, filings)
        price_future = pool.submit(_analyze_price, symbol, price_context)
        news_opinion = news_future.result()
        filings_opinion = filings_future.result()
        price_opinion = price_future.result()

    prompt = f"""You are the lead analyst synthesizing three independent junior analysts'
opinions on {symbol} into one final decision. Each junior analyst saw ONLY their own
data slice and does not know what the others concluded.

NEWS ANALYST: {news_opinion}

FILINGS ANALYST: {filings_opinion}

PRICE/MOMENTUM ANALYST: {price_opinion}

Rules:
- If the analysts materially disagree (e.g. news is bullish but insiders are selling,
  or the price analyst says the move already happened while the news analyst treats
  it as fresh), you MUST call this out explicitly in both reasoning_steps and
  risk_flags, and keep confidence_score conservative.
- Do not just average the three opinions - reason about WHY they might differ and
  which signal should carry more weight here.
- already_priced_in should follow the price analyst's judgment unless the other two
  give strong reason to override it.
"""

    card = _run_reviewed(prompt, DECISION_CARD_TOOL, "emit_decision_card", _validate_decision_card)
    card["symbol"] = symbol
    card["sources"] = {"news": news_items, "filings": filings, "price_context": price_context}
    card["analyst_opinions"] = {
        "news": news_opinion,
        "filings": filings_opinion,
        "price": price_opinion,
    }
    return card
