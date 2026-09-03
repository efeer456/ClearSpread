# Bağlam: Bu proje Claude (claude.ai sohbetinde) tarafından iskelet olarak kuruldu

## Ne, neden

Alpaca AI Trading Agents Hackathon (lablab.ai, "Options Alpha Agents" track).
Deadline: **4 Eylül 2026, 15:00 UTC**. Solo katılım.

Farklılaşma stratejisi: çoğu takım "haber çek → agent yorumlasın → otomatik
trade et" yapıyor. Biz bunun yerine **şeffaflık + insan onayı** eksenine
oturduk: her karar kaynağına, akıl yürütmesine ve güven skoruna kadar
izlenebilir; hiçbir emir insan onayı olmadan gönderilmez; sadece tanımlı
riskli (defined-risk) opsiyon stratejileri (debit spread) öneriliyor.

## Mimari (zaten yazıldı, syntax + import testleri geçti)

- `osint/alpaca_news.py` — Alpaca NewsClient ile ticker bazlı haber
- `osint/sec_edgar.py` — SEC EDGAR full-text search (Form 4 / 8-K), key gerekmiyor
- `agent/market_context.py` — son fiyat/hacim ("fiyata yansımış mı" kontrolü için)
- `agent/reasoning.py` — Claude'u zorunlu tool-call ile yapısal Karar Kartı üretmeye zorluyor
- `agent/options_strategy.py` — sentiment'e göre debit call/put spread önerisi + max kayıp/kazanç
- `trading/executor.py` — SADECE onay sonrası çağrılır, Alpaca paper hesapta MLEG emir gönderir
- `storage/audit_log.py` — SQLite audit trail (test edildi, çalışıyor)
- `app.py` — Streamlit arayüzü (Approve/Reject + Denetim İzi sekmesi)

Kod, gerçek Alpaca/Anthropic ağ erişimi olmayan bir sandbox'ta yazıldığı için
**hiçbir modül gerçek API'ye karşı çalıştırılıp doğrulanmadı**. Sadece
`ast.parse` ile syntax kontrolü ve sahte anahtarlarla import testi yapıldı.

## Bilinen riskler / önce kontrol edilecekler

1. **Alpaca paper hesabında options trading seviyesi onaylı mı?** Değilse
   hemen başvur (Dashboard → Configure) — bu tek gerçek bloke edici risk.
2. `alpaca-py` sürümüne göre bazı sınıf/alan isimleri değişmiş olabilir
   (`OptionChainRequest`, `OptionLegRequest`, `PositionIntent`, `NewsClient`
   alanları). İlk çalıştırmada import hataları çıkarsa, kurulu `alpaca-py`
   sürümünü (`pip show alpaca-py`) kontrol edip gerekirse alan adlarını
   güncelle.
3. `osint/sec_edgar.py` sembol yerine şirket adıyla arıyor (full-text search
   API böyle çalışıyor). Basit tutuldu — ticker'dan şirket adına daha sağlam
   bir eşleme gerekirse `https://www.sec.gov/files/company_tickers.json`
   kullanılabilir.
4. `agent/options_strategy.py`'daki strike/expiry seçim mantığı basit
   (spot'a en yakın + width_pct kadar uzak). Gerçek chain verisiyle test edip
   gerekirse ayarla.

## Öncelik sırası (kalan süre kısıtlı)

1. `.env` doldur, her modülü tek başına çalıştırıp gerçek veri dönüyor mu bak
   (`python -m osint.alpaca_news`, `python -m osint.sec_edgar`,
   `python -m agent.market_context`).
2. `agent/reasoning.py` ve `agent/options_strategy.py`'ı gerçek verilerle test et.
3. `streamlit run app.py` ile uçtan uca bir tur at, hataları düzelt.
4. Paper hesapta gerçekten küçük bir emir gönderip `trading/executor.py`'ı doğrula.
5. Zaman kalırsa: gerçek `alpaca-mcp-server`'ı entegre etmek (stretch goal,
   README'de detaylı) — hackathon duyurusunun vurguladığı senaryo tam bu.
6. Submission metni + demo videosu.

## Nasıl devam edilir

Bu dosyayı okuduktan sonra sırayla: (a) `.env` kurulumu için kullanıcıya
sor/yardım et, (b) her modülü gerçek anahtarlarla tek tek test et, (c)
çıkan hataları alan adı/versiyon uyuşmazlığı açısından düzelt, (d) Streamlit
uygulamasını çalıştırıp uçtan uca doğrula.
