# Şeffaf & İnsan-Onaylı OSINT Opsiyon Ajanı

**Alpaca AI Trading Agents Hackathon** (lablab.ai) — *Options Alpha Agents* track için.

## Fikir

Çoğu ekip "haberi çek → agent yorumlasın → otomatik trade et" akışını kuruyor.
Bu proje bilinçli olarak farklı bir yerde duruyor: **hız yerine denetlenebilirlik**.

- Her karar; hangi OSINT kaynağına (Alpaca News + SEC EDGAR Form 4/8-K), hangi
  akıl yürütme adımlarına ve hangi güven skoruna dayandığı açıkça gösterilen bir
  **"Karar Kartı"** olarak üretilir.
- Agent asla kendi başına emir göndermez. Her opsiyon stratejisi, kullanıcı
  **Approve** demeden çalıştırılmaz.
- Sadece **tanımlı riskli** (defined-risk) stratejiler önerilir (debit call/put
  spread) — max kayıp önceden bilinir, "naked" opsiyon satışı desteklenmez.
- Her adım (kaynak → analiz → insan kararı → emir) SQLite'ta değişmez şekilde
  loglanır ve "Denetim İzi" sekmesinde bir zaman çizelgesi olarak gösterilir.

## Mimari

```
osint/alpaca_news.py     -> Alpaca NewsClient ile ticker bazlı haber
osint/sec_edgar.py       -> SEC EDGAR full-text search (Form 4 / 8-K)
alpaca_cli.py            -> Resmi Alpaca CLI (github.com/alpacahq/cli) subprocess sarmalayıcısı
agent/market_context.py  -> "fiyata zaten yansımış mı?" için son fiyat/hacim (Alpaca CLI: data bars)
agent/reasoning.py       -> Gemini, zorunlu function-call ile yapısal Karar Kartı üretir
agent/options_strategy.py-> Sentiment'e göre debit spread önerisi (Alpaca CLI: data option chain)
trading/executor.py      -> SADECE onay sonrası: Alpaca CLI (order submit --order-class mleg)
storage/audit_log.py     -> SQLite: karar + insan aksiyonu + emir geçmişi
app.py                   -> Streamlit arayüzü (Approve/Reject + Denetim İzi)
```

Hackathon kuralı gereği (Alpaca'nın MCP server'ı veya CLI'sinin kullanılması zorunlu),
piyasa verisi ve emir gönderme dahil tüm trading akışı doğrudan `alpaca-py` SDK'sı
yerine resmi **Alpaca CLI**'ye subprocess çağrılarıyla yapılıyor (`alpaca_cli.py`).
`alpaca-py` sadece `osint/alpaca_news.py`'da haber çekmek için kullanılıyor (OSINT
katmanı, trading katmanı değil).

## Kurulum

```bash
pip install -r requirements.txt
cp .env.example .env   # sonra kendi anahtarlarinizi girin
streamlit run app.py
```

Gereken anahtarlar:
- **Alpaca paper trading** API key/secret (dashboard → Paper Trading → API Keys).
  Opsiyon işlemleri için hesabınızda options trading seviyesinin onaylı olması gerekir.
- **Gemini API key** (aistudio.google.com/apikey)
- SEC EDGAR için key gerekmez, sadece gerçek bir iletişim bilgisi (`SEC_EDGAR_USER_AGENT`)
  istiyorlar (fair-access politikası).

Ayrıca **Alpaca CLI**'nin kurulu olması gerekir:
```bash
go install github.com/alpacahq/cli/cmd/alpaca@latest   # ya da: brew install alpacahq/tap/cli
```
PATH'e ekliyse `.env`'de `ALPACA_CLI_PATH=alpaca` yeterli; değilse tam yolu verin
(Windows için hazır binary: [GitHub Releases](https://github.com/alpacahq/cli/releases)).

## Bilinçli sınırlamalar (2 günlük hackathon kapsamı)

- Strateji seti şu an sadece **debit call/put spread**. Iron condor, credit
  spread gibi stratejiler zaman kalırsa `agent/options_strategy.py`'a eklenebilir.
- SEC EDGAR araması sembol yerine şirket adıyla yapılıyor (full-text search
  API'si böyle çalışıyor); ticker → şirket adı eşlemesi basit tutuldu, gerekirse
  `company_tickers.json` ile geliştirilebilir.
- ~~Stretch goal: MCP/CLI entegrasyonu~~ — tamamlandı: tüm trading/data akışı
  artık `alpaca-py` SDK yerine resmi Alpaca CLI üzerinden çalışıyor (`alpaca_cli.py`).

## Demo akışı (jüri için)

1. "Denetim İzi" sekmesi boşken başla.
2. Bir sembol seç, "OSINT Topla ve Analiz Et" butonuna bas → Karar Kartı ekranda
   kaynaklarıyla, akıl yürütmesiyle ve güven skoruyla birlikte belirir.
3. Önerilen stratejiyi incele, kontrat adedini ayarla.
4. Approve veya Reject'e bas → sonucu "Denetim İzi" sekmesinde göster.
5. Vurgu cümlesi: *"Bu ajan hiçbir zaman sizin onayınız olmadan piyasaya
   dokunmuyor — ve attığı her adım geriye dönük olarak denetlenebilir."*
