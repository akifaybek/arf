# STATUS — Arf

Son güncelleme: 2026-10-17 15:10 — Claude (Fuji entegrasyonu: chain.py + 4 canlı senaryo)

## Adımlar
| # | Adım | Durum | Not |
|---|------|-------|-----|
| 0 | Proje iskeleti (git, venv, .env.example) | bitti | commit cfc5a4e |
| 1 | ATK CLI kurulum + doğrulama | bitti | 1.4.8, TR sitesi; commit 5a1b43d |
| 2 | atk_client.py | bitti | hatalı paritede ok=False, çökme yok; commit 2d20e0a |
| 3 | pick_pairs.py → pairs.json | bitti | hisse/ETF tokenleri hariç, 20 parite yeniden seçildi (13:14) |
| 4 | logger.py arka planda | bitti | başlangıç: 2026-10-17 13:14:45, PID 20574, tur ~15 s |
| 5 | RiskCircuitBreaker.sol + signer.py + test vektörü | bitti | `forge test`: 14/14 geçti; Python↔Solidity digest aynı |
| 6 | Fuji deploy + chain.py entegrasyonu | bitti | 0xddE4C7…591159; 4 senaryo canlı doğrulandı (2 tx) |
| 7 | metrics.py + test_metrics.py + scan_demo.py | bitti | `pytest`: 34/34 geçti; demo adayı 6 parite |
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

## Kontrat (CANLI — Fuji)
- Ağ: Avalanche Fuji (chainId **43113**)
- Adres: **0xddE4C78F831f082E8AFDF716266bd1338B591159**
- Deploy tx: 0x8f757f33eb3e627c3a69d6f4333be0dba200ae8f717e97698f2bc62d8e25bad7
  (blok 59597359, Remix ile deploy edildi — solc 0.8.35, evm cancun, optimizer 200)
- Owner: 0xbe965C314D2655360142b05DF34c760e08980F68
- Oracle: 0x3267103eB5d4F4F6350d0D03327De7637a56d385
- Trader (demo): 0x5D07498C9Aa3F85c996Dae68e819d8b6AAF8233D (1 AVAX)
- riskThreshold: 5000 · paused: false · MAX_AGE: 300 · MAX_FUTURE: 60
  (hepsi zincirden okundu, `chain.py` EXPECTED ile birebir uyuştu)
- Explorer (tx): `https://explorer-test.avax.network/c-chain/tx/<hash>`

### Fuji'de ölçülen (fuji_smoke.py, 2026-10-17 ~15:0x)
| # | Senaryo | Sonuç | Gas | Onay |
|---|---|---|---|---|
| a | amount 800 / maxSafeSize 1000 | **CONFIRMED**, IntentApproved(amount=800000000) | 60.831 | **1923 ms** |
| b | aynı imza 2. kez (eth_call) | `AlreadyUsed(digest=0x7459…d690)` | — | — |
| c | amount 10000 (force_onchain) | **REVERTED_ONCHAIN**, `ExceedsSafeSize(10000000000, 1000000000, 10)` | 150.000 | **1937 ms** |
| d | timestamp = şimdi−400 (eth_call) | `StaleScore(1792239392, 1792239790)` | — | — |

- tx a: `0x7bef94f297de147acf74dce1139eca659e982e2ae51a51f013b2d89071ba5173`
- tx c: `0x175eaee2cdce982ad58988c3d73bb08944bf3d62fbcf91dcab1a973b8f4bf0e5`
- **Cancun yolu Fuji'de ÇALIŞTI** (adım 5'teki varsayım kapandı): tx a onaylandı,
  yani `MessageHashUtils` + `ECDSA.recover` zincirde yürüdü. OZ 5.6.1 `mcopy`
  içeren derleme Fuji tarafından kabul edildi.
- **Canlı digest byte uyumu:** `attestationDigest` (Fuji) ile `signer.py`
  (Python) aynı girdiler için birebir aynı:
  `0x745918c2f042764f7867bfdb7eb396090c7fb6c90742ff882ac5ed522102d690`
  (ZBCN-USDT, buy, risk 3000, maxSafe 1e9, canlı timestamp).
  Ayrıca `test/vector_fuji.json` (sabit girdiler, canlı adres):
  `0xadf82b9099ad37b46aff3b88684ac3618721d121e987cf706b0a6d3d23fc261c`
  — zincirden okunan değerle aynı.

### RPC durumu (ÖLÇÜLDÜ, 2026-10-17 hotspot)
| Uç nokta | Sonuç |
|---|---|
| `api.avax-test.network` (.env'deki FUJI_RPC_URL) | **429 Too Many Requests** — hotspot'ta da açılmadı |
| `avalanche-fuji-c-chain-rpc.publicnode.com` | **43113, çalışıyor** (tüm tx'ler buradan gitti) |
| `endpoints.omniatech.io/.../fuji/public` | Cloudflare bloğu |
| `api.zan.top/.../fuji/public` | 403, "request origin required" |
| `rpc.ankr.com/avalanche_fuji` | API anahtarı istiyor |

`chain.py` adayları sırayla dener, 429/timeout'ta sonrakine geçer, seçileni
**maskelenmiş host** olarak loglar (bir RPC URL'i API anahtarı taşıyabilir).

### Araç zinciri (ÖLÇÜLEN)
| Bileşen | Sürüm | Not |
|---|---|---|
| forge | 1.7.1-Homebrew | `forge --version` |
| solc | 0.8.35 | foundry.toml'da sabit; svm önbelleğinde hazırdı (indirme yok) |
| @openzeppelin/contracts | 5.6.1 | `npm install @openzeppelin/contracts@5` |
| eth-account / eth-abi | 0.14.0 / 6.0.0 | requirements.txt'te sabit |
| solc (flatten doğrulaması) | 0.8.36 (homebrew) | tek dosya hali bağımsız derlendi, 0 hata |

- `evm_version = "cancun"` **zorunlu (ÖLÇÜLDÜ)**: OZ 5.6.1 `utils/Bytes.sol`
  içinde `mcopy` kullanıyor, `paris` ile derleme Error 7755 veriyor.
  Fuji'nin cancun opcode desteği DOĞRULANMADI (varsayım) — deploy'da sorun
  çıkarsa mcopy kullanmayan daha eski bir OZ 5.x'e inilir.
- OZ v5 yolları node_modules'teki gerçek kaynaktan doğrulandı:
  `access/Ownable.sol` (pragma ^0.8.24, `constructor(address initialOwner)`),
  `utils/Pausable.sol`, `utils/cryptography/{ECDSA,MessageHashUtils}.sol`
  (`toEthSignedMessageHash(bytes32)`, `recover(bytes32,bytes)`).
- **forge-std KULLANILMIYOR:** npm'deki `forge-std` paketi üçüncü taraf
  ("Unofficial NPM distribution", v1.1.2, 1 yıldan eski), `forge install` ise
  git'e yazar. Yerine `test/Cheats.sol` içinde asgari `Vm` arayüzü var;
  bildirimler forge 1.7.1 ikilisinin gömülü cheatcode tablosundan çıkarıldı
  (`strings -a $(which forge) | grep -oE "function sign\([^;]*;"`), cheatcode
  adresi de aynı ikiliden doğrulandı.

### Python ↔ Solidity byte uyumu (ÖLÇÜLDÜ)
Sabit vektör: `test/vector.json` (YGG-USDT, buy, riskScore 4200,
maxSafeSize 1000 USDT = 1e9 birim, timestamp 1760000000, chainId 43113).
- Python digest  : `0xb244ca6490a662b1efa6736b947e00f0dafbbdd069b06dafeb0dcd02a66733e9`
- Solidity digest: `0xb244ca6490a662b1efa6736b947e00f0dafbbdd069b06dafeb0dcd02a66733e9`
- Python'un imzası `executeIntent`'te kabul edildi; `used[digest]` true oldu.
- Negatif kontrol yapıldı: digest'in son nibble'ı bozulunca test FAIL,
  imzanın son byte'ı bozulunca `ECDSAInvalidSignature()` → test bağlayıcı.
- Vektör, testin deploy adresi için üretilir:
  `CREATE(0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC, nonce 0)` =
  `0x663F3ad617193148711d28f5334eE4Ed07016602`. Test, deploy ettiği adresi
  vektördeki `contract` alanıyla karşılaştırır; sapma olursa açık mesajla
  kırılır (`signer.py --vector` ile yenilenir). `--contract` ile başka adres
  için de vektör üretilebilir.

### Testler (14/14 geçti, `forge test -vv`)
`test_DigestMatchesPython`, `test_HappyPath`, `test_RevertExceedsSafeSize`
(suggestedParts=10 doğrulandı), `test_RevertStale`, `test_RevertFutureTimestamp`,
`test_RevertBadSigner`, `test_RevertReplay`, `test_RevertRiskTooHigh`,
`test_RevertNoSafeSize`, `test_RevertBadSide`, `test_PauseBlocks`,
`test_SetOracleOnlyOwner`, `test_SetOracleRotates` (eski oracle imzası
artık `BadSigner`), `test_SetRiskThresholdOnlyOwner`.

## Metrikler (adım 7 — metrics.py)

### ÖLÇÜLEN
- `pytest -v`: **34 test, 34 geçti** (`test_metrics.py`). Ağ yok, ATK çağrısı
  yok, `memory.db`'ye dokunulmaz — hafıza ve tahta her testte enjekte edilir.
- **Bonferroni eşiği hesaplandı (sabit yazılmadı):**
  `bonferroni_threshold(alpha=0.05, m=20)` = **3.023341**
  (`NormalDist().inv_cdf(1 - 0.05/40)`; düzeltmesiz m=1 için 1.959964).
- **İç tutarlılık (canlı tahtada, iki yönde):** `max_safe_size` dönen tutarda
  `walk_book` kaymayı **tam 100.000 bps** ölçüyor — ZBCN/BIGTIME/SOPH,
  buy ve sell. Seviye içi miktar kapalı formle çözülüyor (interpolasyon değil).
- Sentetik tahtada elle doğrulanabilir cevap: ask 100/101/102 ×1, bid 99/98/97
  ×1, mid 99.5 → `max_safe_size(buy, %1)` = **199.0 USDT** (hedef fiyat
  100.495; 101 seviyesinden alınan miktar 99/101 baz).

### Demo taraması (scan_demo.py, alış tarafı, 2026-10-17 ~14:50)
20 paritenin 6'sı demo koşulunu sağlıyor (1.000 ≤ maxSafeSize < 10.000 USDT):
NES (7.120), ZBCN (3.588), OFC (6.739), VELODROME (8.586), SOPH (1.158),
BIGTIME (6.216). Diğer 14'ü 10k'yı da kaldırıyor (RE-USDT 186K'ya kadar).
- Seçilen 2 aday: **ZBCN-USDT** (maxSafe 3.588, risk 2684, parça@10k=3,
  sınırlara pay 2.79x) ve **BIGTIME-USDT** (maxSafe 6.216, risk 323,
  parça@10k=2, pay 1.61x).
- Tahta dakikalar içinde oynuyor: aynı pariteler birkaç dakika sonra
  ZBCN 3.394 / BIGTIME 6.467 ölçüldü. Demo anında yeniden taranmalı.
- Hiçbir paritede `maxSafeSize` ALT SINIR değil (tahta %1 kaymaya ulaşmadan
  bitmiyor) → `book_truncated` ile birlikte bu durum demo sırasında da
  izlenecek.

### VARSAYIMLAR (ölçülmüş değil, tasarım tercihi; hepsi tek yerde)
- `RISK_WEIGHTS` (toplam 1.0): kayma 0.35, derinlik düşüşü 0.20, anomali z
  0.15, spread 0.15, dolmama 0.15.
- `RISK_SCALES` (bileşeni 1.0 yapan "tavan" değerler): kayma 200 bps,
  derinlik yarıya inmesi (0.50), spread 100 bps.
- `LIMITED_MEMORY_PENALTY = 1000` (0–10000 skalasında): hafıza 30 noktadan
  azsa z bileşenleri hesaplanmaz, skora muhafazakâr sabit eklenir.
- `MIN_MEMORY_POINTS = 30`, `MEMORY_LOOKBACK = 120` örnek (~2 saat).
- `DEFAULT_MAX_SLIP_BPS = 100` (%1) — CLAUDE.md madde 4'ten.
- Kayma MID'e göre ölçülür, **yarım spread dahil** (agent bunu "piyasa
  emriyle anında al/sat maliyeti" olarak okur).
- `volume_quality` raporlanır ama risk skoruna **girmez** (skor bileşenleri
  CLAUDE.md'de kayma/derinlik/anomali/spread olarak sayılmış).
- `scan_demo.py` aday sıralaması: önce `riskScore ≤ 5000`, sonra 1k/10k
  sınırlarına en büyük pay.

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
- **RPC tek bacakta:** sadece publicnode çalışıyor. `.env`'e
  `FUJI_RPC_URLS=https://avalanche-fuji-c-chain-rpc.publicnode.com` satırı
  eklenmeli (Akif ekleyecek); şu an komut satırından geçiliyor. Demo günü
  bu uç nokta da düşerse yeni aday aranması gerekir.
- Revert eden tx sabit 300.000 gas limitiyle gidiyor ve **150.000 gas**
  harcanmış görünüyor (yarısı). Sahne için sorun değil, ama "revert ucuz"
  denemez; neden yarısı olduğu DOĞRULANMADI.
- `test/vector_fuji.json` canlı adres için üretildi ama imzası **anvil test
  anahtarıyla** (bilerek: gerçek oracle imzası repoya girmez) → o dosyadaki
  imza Fuji'de `BadSigner` verir, digest'i ise zincirle birebir aynı.

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
- Kontratta CLAUDE.md madde 6'ya EK olarak iki şey var (adım 2 talimatından):
  `used[digest]` tekrar kullanım engeli (`AlreadyUsed`) ve `MAX_FUTURE = 60`
  sn ileri zaman payı (saat sapması; aşılırsa `StaleScore`).
- `maxSafeSize` USDT→1e6 çevrimi AŞAĞI yuvarlar (yukarı yuvarlamak güvenli
  tutarı şişirirdi).
- Yeni 20 parite (13:14, hacim 51K–358K USDT): ATOM, NES, ZBCN, 2Z, UMA,
  OKSOL, AVNT, OFC, KAITO, ENS, ENJ, RE, VELODROME, FLOKI, WCT, SOPH, ROBO,
  API3, IRYS, BIGTIME (hepsi `-USDT`, hepsi `book_truncated=False`).
