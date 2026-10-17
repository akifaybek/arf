# STATUS — Arf

Son güncelleme: 2026-10-17 13:15 — Claude (hisse tokeni filtresi + book_truncated)

## Adımlar
| # | Adım | Durum | Not |
|---|------|-------|-----|
| 0 | Proje iskeleti (git, venv, .env.example) | bitti | commit cfc5a4e |
| 1 | ATK CLI kurulum + doğrulama | bitti | 1.4.8, TR sitesi; commit 5a1b43d |
| 2 | atk_client.py | bitti | hatalı paritede ok=False, çökme yok; commit 2d20e0a |
| 3 | pick_pairs.py → pairs.json | bitti | hisse/ETF tokenleri hariç, 20 parite yeniden seçildi (13:14) |
| 4 | logger.py arka planda | bitti | başlangıç: 2026-10-17 13:14:45, PID 20574, tur ~15 s |
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
  Bayrağın adı artık `book_truncated` (True = 400 seviye ±%2'ye ulaşmadı,
  raporlanan derinlik ALT SINIR). Eski ad `covers_band` idi (anlamı tersti).
  - BTC-USDT (sz=400): ask yalnız **+0.121%**, bid **−0.261%** →
    `book_truncated=True`. Çok likit paritelerde 400 seviye dar bir banda
    sıkışıyor; ±%2 derinlik ALT SINIR olarak raporlanmalı.
  - GOAT-USDT: +331% / −99.9% → `book_truncated=False` (sığ tahta, geniş seviyeler)
  - THETA-USDT: +163% / −99.9% → False
  - CTC-USDT: ask 55 bid 400 seviye → False
  Yani `book_truncated=True` sığlık değil, **likit paritede kırpılma** işareti.
  Bu yüzden metriklerde "kırpıldı" bayrağı taşınacak.
- **Hisse/ETF tokenleri (ÖLÇÜLDÜ, 2026-10-17):** `instruments --instType SPOT`
  çıktısında `instCategory` dağılımı `{1: 1013, 3: 167, 4: 4}`. `instCategory="3"`
  olan 167 kaydın 143'ü `-USDT` ve hepsi `X` önekli (XAAPL, XSPY, XTSLA…).
  Bunlar ABD borsa seansına bağlı (`openType=pre_quote`, `contTdSwTime` dolu);
  seans kapalıyken tahta donar ve likidite rejimi ölçümü kirlenir →
  `pick_pairs.py` içinde HARİÇ TUTULUYOR. 443 live -USDT paritenin 141'i bu
  filtreyle düştü (seçim anında live olanlar), kalan 302.
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

## Logger
- Komut: `nohup caffeinate -i .venv/bin/python logger.py > logger.log 2>&1 &`
- PID: 20574 (caffeinate 20576) — başlangıç 2026-10-17 13:14:45 (yerel, +03)
- Önceki çalıştırma: PID 16027, 13:03–13:13, 240 satır (12 tur) → DB
  `memory_v1.db` olarak saklandı (silinmedi, eski şema `covers_band` ile).
- DB: `memory.db` (yeni şema, `book_truncated`), tablo `snapshots`,
  index `idx_snapshots_inst_ts (inst, ts)`
- Tur süresi ÖLÇÜLDÜ: ~15.5 s (20 parite × 1 orderbook + 1 tickers) → 60 s aralığı rahat
- Durum kontrolü: `.venv/bin/python logger.py --status`

## Açık sorunlar
- `state` alanının `live` dışındaki değerleri TR'de hiç görülmedi → filtre
  pratikte etkisiz ama korunuyor.

## Kapanan sorunlar
- **Hisse tokenleri (KAPANDI 13:14):** `instCategory=3` filtresi eklendi,
  pariteler yeniden seçildi. Eski seçimdeki `XMSFT-USDT`, `XAPLD-USDT`,
  `XEWY-USDT` artık listede yok.

## Kararlar / sapmalar
- Hacim alanı olarak `volCcy24h` (USDT) kullanılıyor; `vol24h` baz cinsinden.
- `orderbook --sz` her çağrıda 400 (ölçülen üst sınır).
- Bayrak adı `covers_band` → **`book_truncated`** (anlam ters çevrildi:
  True = 400 seviye ±%2'ye ulaşmadı, raporlanan derinlik ALT SINIR).
  atk_client, pick_pairs, logger ve DB şeması güncellendi; eski DB
  `memory_v1.db` olarak duruyor.
- Hisse/ETF tokenleri (`instCategory="3"`) seçimden hariç.
- Yüzdelik %40–70 dilimi: filtreden geçen 295 paritenin 118..206 arası (88
  parite); 20 parite eşit aralıkla (deterministik `round(i*step)`).
- Yeni 20 parite (13:14, hacim 51K–358K USDT): ATOM, NES, ZBCN, 2Z, UMA,
  OKSOL, AVNT, OFC, KAITO, ENS, ENJ, RE, VELODROME, FLOKI, WCT, SOPH, ROBO,
  API3, IRYS, BIGTIME (hepsi `-USDT`, hepsi `book_truncated=False`).
