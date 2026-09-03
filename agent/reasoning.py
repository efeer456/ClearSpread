"""
Toplanan OSINT verisini (haber + SEC filing + fiyat baglami) Gemini'a vererek
seffaf, denetlenebilir bir 'Karar Karti' (decision card) uretir.

Onemli tasarim karari: Gemini'dan serbest metin degil, zorunlu bir "function call"
seklinde yapisal JSON istiyoruz (tool_config mode=ANY). Bu, her karar kartinin ayni
sablonda, denetlenebilir ve UI'da tutarli sekilde gosterilebilir olmasini saglar.
"""
from typing import Dict, List

from google import genai
from google.genai import types

from config import GEMINI_API_KEY, GEMINI_MODEL

_client = genai.Client(api_key=GEMINI_API_KEY)

DECISION_CARD_FUNCTION = types.FunctionDeclaration(
    name="emit_decision_card",
    description="Yapilandirilmis, seffaf bir OSINT analiz karti uretir.",
    parameters={
        "type": "OBJECT",
        "properties": {
            "event_summary": {
                "type": "STRING",
                "description": "Olayin kendi cumlelerinle 2-3 cumlelik ozeti. Kaynaktan birebir alinti yapma.",
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
                "description": "0-100 arasi: bu sinyalin ticaret kararina temel olacak kadar guvenilir olma derecesi",
            },
            "already_priced_in": {
                "type": "BOOLEAN",
                "description": "Son fiyat/hacim hareketine bakildiginda bilginin piyasaya zaten yansimis olma ihtimali",
            },
            "reasoning_steps": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
                "description": "Karara adim adim nasil varildigini aciklayan kisa, sirali cumleler (denetim izi icin)",
            },
            "risk_flags": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
                "description": "Dikkat edilmesi gereken riskler: dusuk hacim, tek kaynak, olasi manipulasyon vb.",
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
        lines.append("HABERLER:")
        for n in news_items:
            lines.append(f"- [{n.get('created_at')}] {n.get('headline')} (kaynak: {n.get('source')}, url: {n.get('url')})")
    if filings:
        lines.append("\nRESMI SEC BASVURULARI:")
        for f in filings:
            lines.append(f"- [{f.get('filed_at')}] {f.get('form')} - {f.get('company')} (url: {f.get('url')})")
    if not lines:
        lines.append("(Bu sembol icin son donemde OSINT kaynagi bulunamadi.)")
    return "\n".join(lines)


def build_decision_card(symbol: str, news_items: List[Dict], filings: List[Dict],
                         price_context: Dict) -> Dict:
    """
    Gemini'i bir arastirma analisti gibi calistirip yapisal bir karar karti dondurur.
    Donen dict, DECISION_CARD_FUNCTION semasina uyar + 'symbol' ve 'sources' eklenir.
    """
    sources_text = _format_sources(news_items, filings)

    prompt = f"""Sen dikkatli, sekpetik bir finansal arastirma analistisin. Asagida {symbol}
hissesi icin toplanan OSINT (acik kaynak istihbarati) verisini ve son fiyat/hacim
baglamini goreceksin. Gorevin bunlari degerlendirip yapisal bir karar karti uretmek.

Kurallar:
- Kaynaklardan BIREBIR alinti yapma, kendi cumlelerinle ozetle.
- Eger veri zayifsa (tek kaynak, eski tarih, dusuk hacim) bunu risk_flags icinde belirt
  ve confidence_score'u dusuk tut.
- already_priced_in alanini price_context'teki yuzde degisim ve hacim oranina bakarak degerlendir:
  buyuk bir fiyat hareketi zaten gerceklesmisse haber byuk olasilikla fiyatlanmistir.
- reasoning_steps, baska bir insanin senin mantik zincirini takip edebilecegi kadar acik olmali.

OSINT KAYNAKLARI:
{sources_text}

FIYAT/HACIM BAGLAMI:
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

    raise RuntimeError("Gemini yapisal bir karar karti dondurmedi.")
