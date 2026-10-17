# STATUS — Arf

Son güncelleme: <saat> — <kim>

## Adımlar
| # | Adım | Durum | Not |
|---|------|-------|-----|
| 1 | ATK CLI kurulum + doğrulama | yapılacak | |
| 2 | atk_client.py | yapılacak | |
| 3 | pick_pairs.py → pairs.json | yapılacak | |
| 4 | logger.py arka planda | yapılacak | başlangıç saati: |
| 5 | RiskCircuitBreaker.sol + test vektörü | yapılacak | |
| 6 | Fuji deploy | yapılacak | |
| 7 | metrics.py | yapılacak | |
| 8 | agent.py döngüsü | yapılacak | |
| 9 | signer.py → kontrat uçtan uca | yapılacak | |
| 10 | Trader niyeti + revert sahnesi | yapılacak | |
| 11 | Fail-closed sahnesi | yapılacak | |
| 12 | (ops.) mcp_server.py | yapılacak | |
| 13 | Streamlit app.py | yapılacak | |
| 14 | README + yedek video + prova | yapılacak | |

## Doğrulanmış ATK komutları
ATK sürümü 1.4.8 (343e3ffb). Tüm çağrılar `OKX_SITE=tr` + `--json`.
Süreler tek ölçüm (soğuk/sıcak ayrımı yapılmadı).

| Komut | Süre (ms) | Çıktı şekli | Önemli alanlar / birim |
|---|---|---|---|
| `OKX_SITE=tr okx market ticker BTC-USDT --json` | 767 | 1 elemanlı liste | `last`, `askPx/askSz`, `bidPx/bidSz`, `vol24h` (BAZ), `volCcy24h` (USDT), `ts` (ms) |
| `OKX_SITE=tr okx market tickers SPOT --json` | 738 | 1184 kayıtlı liste | ticker ile aynı alanlar; 443 tanesi `-USDT` |
| `OKX_SITE=tr okx market orderbook BTC-USDT --sz 400 --json` | 782 | 1 elemanlı liste: `asks`, `bids`, `ts`, `seqId` | seviye = `[fiyat, miktar(BAZ), "0", emir_sayısı]` |
| `... --sz 100` / `--sz 50` | 534 / 526 | — | istenen seviye sayısı aynen döner |
| `OKX_SITE=tr okx market candles BTC-USDT --bar 1m --limit 60 --json` | 528 | 60 elemanlı liste | `[ts(ms), o, h, l, c, vol(BAZ), volCcy(USDT), volCcyQuote, confirm]`, sıralama YENİDEN→ESKİYE, `confirm` 0=açık bar |
| `OKX_SITE=tr okx market instruments --instType SPOT --json` | 676 | 1184 kayıt | `state`, `baseCcy`, `quoteCcy`, `minSz`, `lotSz`, `tickSz` |

### ÖLÇÜLEN bulgular
- **Hacim alanı birimi (ÖLÇÜLDÜ):** `volCcy24h` = USDT (quote), `vol24h` = baz.
  BTC-USDT: `last × vol24h = 378,825,267` vs `volCcy24h = 379,004,744` → oran 0.9995
  (fark VWAP ≠ son fiyat). Kullanılacak alan: **`volCcy24h`**.
- **`orderbook --sz` üst sınırı (ÖLÇÜLDÜ): 400.** `--sz 401`, `500`, `1000`, `5000`
  hepsi `Error: Parameter sz error. Code: 51000` veriyor. Kullanılacak: `--sz 400`.
- **Seviye miktarı birimi (ÖLÇÜLDÜ): BAZ varlık.** BTC ask seviyesi `0.09365591`,
  ticker `askSz = 0.09047928` ile aynı mertebe. USDT derinlik = fiyat × miktar.
- **±%2 bant kapsaması (ÖLÇÜLDÜ, KRİTİK):** 400 seviye her zaman ±%2'ye ULAŞMIYOR.
  - BTC-USDT (sz=400): ask yalnız **+0.121%**, bid **−0.261%** → `covers_band=False`.
    Çok likit paritelerde 400 seviye dar bir banda sıkışıyor; ±%2 derinlik
    ALT SINIR (kırpılmış) olarak raporlanmalı.
  - GOAT-USDT: +331% / −99.9% → `covers_band=True` (sığ tahta, geniş seviyeler)
  - THETA-USDT: +163% / −99.9% → True
  - CTC-USDT: ask 55 bid 400 seviye, → True
  Yani `covers_band=False` sığlık değil, **likit paritede kırpılma** işareti.
  Bu yüzden metriklerde "kırpıldı" bayrağı taşınacak.
- **KRİTİK ÖLÇÜM: TR'de `state=live` + `-USDT` SPOT parite sayısı = 443.**
  `instruments --instType SPOT` dönen 1184 kaydın tamamı `state=live`
  (tek değer: `live`, başka state yok). 443'ünün hepsi `tickers SPOT`'ta da var.
- Hacim dağılımı (volCcy24h, USDT): %0 BTC 379M · %10 XLM 2.47M · %40 GOAT 182K ·
  %55 THETA 75K · %70 CTC 28K · %90 KNC 3.3K · %99 XSHOP 27.

### DOĞRULANAMADI / VARSAYIM
- `--sz` sınırının 400 olması ölçüldü; bunun ATK mı OKX API mı kaynaklı olduğu
  DOĞRULANAMADI (hata kodu 51000 OKX'ten geliyor gibi görünüyor).
- `state` alanının `live` dışındaki olası değerleri DOĞRULANAMADI (TR'de hiç örnek yok).
- Süreler tek ölçüm; gün içi değişkenlik ölçülmedi.

## Kontrat
- Ağ: Avalanche Fuji (43113)
- Adres:
- Oracle adresi:
- Snowtrace:
- Deploy tx:

## Açık sorunlar
-

## Kararlar / sapmalar
-
