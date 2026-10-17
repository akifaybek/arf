# CLAUDE.md — Arf

_Arf — AI trading agentlar için işlem öncesi icra ve likidite kalkanı._
Ad: Cahit Arf ve Arf değişmezine gönderme. Kontrat tek bir değişmezi korur:
hiçbir emir tahtanın taşıyabileceğinden (maxSafeSize) büyük olamaz.

Her oturumun başında bu dosyayı ve STATUS.md'yi oku. Teslim: bugün 19:00.

## Ne yapıyoruz
AI trading agentlar için işlem ÖNCESİ icra ve likidite kalkanı. Agent emir
vermeden önce: tahta bu emri kaldırır mı, veri taze mi? Cevap imzalı bir
risk skoru + maxSafeSize olarak Avalanche Fuji'deki kontrata gider; kontrat
güvenli tutarı aşan veya imzasız/bayat niyeti reddeder (fail-closed).

Konumlandırma: Arf = OKX.ai'de listelenebilir, ücretli işlem öncesi icra
servisi. Ana arayüz:
`check_execution(symbol, side, size)` → {riskScore, maxSafeSize,
execution_plan, signed_attestation, reasoning}. side ∈ {buy, sell}:
alışta ask tarafı, satışta bid tarafı yürünür.

Ayrışma: Bu bir kaldıraç/likidasyon koruyucu DEĞİL. Tek soru: "Bu emir bu
tahtada kaça patlar, en fazla ne kadarlık emir güvenli?"

## Dil kuralı (kod, log, UI, README)
- "icra maliyeti", "likidite", "kayma", "piyasa rejimi", "epizodik hafıza" kullan.
- ASLA: "manipülasyon", "wash trading tespiti", "öğrenme" (hafıza için).

## Mimari (dosyalar)
1. `atk_client.py` — OKX Agent Trade Kit CLI (`okx`) subprocess sarmalayıcı:
   ticker, orderbook, candles, instruments. Her yanıta `fetched_at` (unix sn).
   CLI hata/timeout verirse exception değil, `{"ok": False, "error": ...}` döner.
2. `pick_pairs.py` — 20 USDT SPOT parite seçer (24s hacme göre alt-orta dilim),
   `pairs.json`'a yazar. Gün boyu SABİT kalır.
3. `logger.py` — 60 sn'de bir her parite için mid, spread, ±%2 alış/satış
   derinliği (USDT), 24s hacim → `memory.db` (SQLite). Arka planda çalışır.
4. `metrics.py` — DETERMİNİSTİK, LLM hesap yapmaz:
   robust z (log-getiri, log-hacim; median/MAD), Bonferroni (20 parite),
   kayma @1k ve @10k USDT (tahta yetmezse `fills=False`), hacim kalitesi
   (24s hacim / ±%2 derinlik), hafızaya göre derinlik değişimi,
   `max_safe_size` (kayma < %1 olan en büyük tutar).
5. `agent.py` — LLM function-calling planlayıcı. Araçlar: scan_market,
   get_candles, get_orderbook, compute_metric, sign_score. Bütçe: 12 araç
   çağrısı. Çıktı: {hipotez, metrikler, kanıt, güven, karar,
   max_safe_size, split_suggestion}. split_suggestion deterministik:
   parts = ceil(amount / max_safe_size), "10k$ yerine zamana yayılmış
   1k$'lık 10 parça" gibi. max_safe_size = 0 ise bölme önerisi yok, "bu
   tahtada güvenli tutar yok".
   LLM'e serbest metin/kullanıcı girdisi gitmez; sadece yapısal piyasa verisi.
   Final skor ve maxSafeSize deterministik formülden gelir; LLM sayıları
   değiştiremez; çelişkide muhafazakâr olan kazanır.
   Veri > 120 sn eskiyse → `INSUFFICIENT_DATA`, imza YOK.
6. `signer.py` + `contracts/RiskCircuitBreaker.sol` (Fuji, chainId 43113, OZ v5):
   - payload = `abi.encode(bytes32 symbolHash, uint8 side, uint256 riskScore,
     uint256 maxSafeSize, uint256 timestamp, uint256 chainid, address contract)`
     side: 0=buy, 1=sell (alış onayı satışta kullanılamasın diye imzada).
     — `encodePacked` YOK. `symbolHash = keccak256(bytes("BTC-USDT"))`.
   - Birimler: maxSafeSize USDT × 1e6 (6 ondalık); riskScore 0–10000.
   - EIP-191: `MessageHashUtils.toEthSignedMessageHash` + `ECDSA.recover`.
   - Kontroller: signer == oracle, tazelik ≤ 300 sn,
     riskScore ≤ riskThreshold, amount ≤ maxSafeSize. Aksi revert:
     `BadSigner`, `StaleScore`, `RiskTooHigh(score, threshold)`,
     `NoSafeSize()` (maxSafeSize == 0),
     `ExceedsSafeSize(amount, maxSafeSize, suggestedParts)`
     (suggestedParts = ceil(amount / maxSafeSize), sıfıra bölme yok).
   - riskScore yüksek = riskli. `riskThreshold` public, `setRiskThreshold`
     onlyOwner + event.
   - Ownable + Pausable + `setOracle` (+ event).
   - Python↔Solidity byte uyumu sabit test vektörüyle kanıtlanır.
7. EK-1 (çekirdekten sonra) `execution.py` — execution_plan:
   Almgren–Chriss kapalı form (x_j = X·sinh(κ(T−t_j))/sinh(κT)),
   etki için karekök yasası (impact ∝ σ·√(size/volume)). σ ve hacim
   logger'dan; etki katsayısı ve risk iştahı VARSAYIM olarak sabitlenir ve
   README'de varsayım diye yazılır. Çıktı: parça sayısı, zaman aralıkları,
   tahmini maliyet. Hazır olunca split_suggestion'ın yerini alır; hazır
   değilse ceil(amount/maxSafeSize) kalır. Kontrat değişmez: zincirde
   kontrol edilen anlık maxSafeSize'dır.
8. EK-2 (çekirdekten sonra) `mcp_server.py` — tek araç `check_execution`,
   açık JSON schema giriş/çıkış. README'de "OKX.ai servis tanımı" bölümü.
   A2MCP formatı resmi dokümanla doğrulanmadıysa "uyumlu" deme,
   "A2MCP'ye uyarlanabilir şema" de.
9. `app.py` — Streamlit tek ekran: sol karar izi + bütçe barı, orta
   metrikler, sağ trader paneli + Snowtrace linkleri.

## Kodlama kuralları
- Küçük adım. Her adımı ÇALIŞTIR ve çıktısını göster; çalışmayanı "bitti" sayma.
- Veri SADECE ATK CLI'dan. OKX REST/WS'i doğrudan çağırma. Sadece SPOT.
- Tüm okx çağrıları OKX_SITE=tr ile yapılır; çıktı için --json kullanılır.
- Gizli bilgi sadece `.env`'de (`.env.example` commit edilir, `.env` gitignore'da).
- Python 3.11+, bağımlılıklar `requirements.txt`'te.
- Her çalışan adımdan sonra küçük bir commit (açıklayıcı mesaj).
- Her adım sonunda STATUS.md'yi güncelle (bitti / devam / açık sorun).
- Ölçülen ile varsayılanı ayır; doğrulamadığın CLI bayrağını "doğrulandı" diye yazma.
- Bir şey 15 dk'dan uzun takılırsa dur, durumu raporla.

## Kötü senaryolar (kodda karşılığı olmalı, README'de bölüm olarak)
- Oracle anahtarı çalınır → pause + setOracle. Sonraki adım: çoklu bağımsız
  oracle (eşik imza / multisig).
- LLM halüsinasyonu / prompt injection → LLM'e sadece piyasa verisi, skor
  deterministik, çelişkide muhafazakâr olan kazanır.
- Yanlış alarm → eşik parametrik ve zincirde görünür; anomali testlerinde
  Bonferroni ile aile bazında yanlış alarm oranı nominal olarak sınırlı.
- Veri kesilir / bayat → INSUFFICIENT_DATA, imza yok, kontrat reddeder.
- Acil çıkış (reduce-only bypass) → SADECE kavram, KODLANMAZ.

## Sunum mesajı (README girişi buna uysun)
ATK ile binlerce trading agent yazılacak; tahtanın emri kaldırıp
kaldıramayacağını bilmeyen agent kendini batırır. Arf her emirden
önce icra maliyetini ATK verisiyle ölçer, imzalar, Avalanche'taki devre
kesiciye bağlar. Veri bozulunca işlemi kapalı bırakır (fail-closed).

## Sadece sunumda "sonraki adım" (KODLANMAZ)
Çağrı başına ödeme (HTTP 402), OKX.ai'ye gerçek listeleme, çoklu oracle /
eşik imza, EIP-712.

## Yapılmayacaklar
Gerçek emir (onaysız asla), OKX API'yi doğrudan çağırmak, SWAP/türev,
Dune/on-chain ek veri, OKX.ai kaydı, anahtarı repoya koymak.
ATK'yı emir yetkili profille bağlamak.

## Kesme sırası (gecikirsek, baştan kes)
1$ trade → replay → EK-2 mcp_server → EK-1 Almgren–Chriss → trader LLM'i.
Streamlit kalır, React yok.
ASLA kesilmez: LLM planlayıcı döngüsü, imzalı skor + Fuji kontratı,
revert sahnesi, fail-closed sahnesi.
