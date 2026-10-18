# Zincir kanıtları ve doğrulama

Bu belge, 17 Ekim 2026 tarihli Fuji işlem kayıtlarını, örnek ölçümleri ve test kapsamını toplar. Performans değerleri tarihli örnek koşulardır; güncel piyasa durumu veya servis garantisi olarak kullanılmamalıdır.

[Ana sayfa](../README.md) · [Teknik mimari](architecture.md)

## Fuji dağıtımı ve imza biçimi

| Alan | Değer |
|---|---|
| Ağ | Avalanche Fuji C-Chain, testnet, chainId `43113` |
| Kontrat | [`0xddE4C78F831f082E8AFDF716266bd1338B591159`](https://explorer-test.avax.network/c-chain/address/0xddE4C78F831f082E8AFDF716266bd1338B591159) |
| Deploy | [Deploy işlemi](https://explorer-test.avax.network/c-chain/tx/0x8f757f33eb3e627c3a69d6f4333be0dba200ae8f717e97698f2bc62d8e25bad7) |
| Derleme kaydı | Remix, solc 0.8.35, OpenZeppelin 5.6.1 |
| Risk eşiği | `5000`, owner `setRiskThreshold` ile değiştirebilir |
| İmza tazeliği | `MAX_AGE=300` sn, `MAX_FUTURE=60` sn |
| Yönetim | Ownable, Pausable, `pause`, `unpause`, `setOracle` |

İmzalanan özet: `keccak256(abi.encode(symbolHash, side, riskScore, maxSafeSize, timestamp, chainid, contract))`, ardından EIP-191. `symbolHash=keccak256(bytes(symbol))`, `side: 0=buy, 1=sell`. Kontrat tutarları **USDT × 10^6** tamsayısıdır; dönüşüm aşağı yuvarlar. Skor 0–10000 aralığındadır, yüksek skor daha yüksek risktir. Python–Solidity byte uyumu sabit test vektörüyle sınanır.

### Doğrulanmış işlem tablosu

Aşağıdaki yedi gerçek işlem, başarılı onayları ve demo kapsamındaki dört reddetme kontrolünü (`ExceedsSafeSize`, `BadSigner`, `AlreadyUsed`, `StaleScore`) içerir. Bağlantılar Fuji explorer üzerindeki işlemlere gider. Hata adları uygulamanın işlem çözümleme kayıtlarından alınmıştır; explorer arayüzü yalnızca başarısızlık durumunu gösterebilir.

| Olay / kontrol | İşlem bağlantısı ve kanıt düzeyi |
|---|---|
| IntentApproved, ilk zincir kontrolü | [0x7bef94f2…ba5173](https://explorer-test.avax.network/c-chain/tx/0x7bef94f297de147acf74dce1139eca659e982e2ae51a51f013b2d89071ba5173) · gerçek tx |
| IntentApproved, agent 1.000 USDT | [0xa5798d59…aacbbe](https://explorer-test.avax.network/c-chain/tx/0xa5798d597f00a46e36c93a48f4423d46a18faf082d2006562140e4bd5eaacbbe) · gerçek tx |
| ExceedsSafeSize, ilk zincir kontrolü | [0x175eaee2…bf0e5](https://explorer-test.avax.network/c-chain/tx/0x175eaee2cdce982ad58988c3d73bb08944bf3d62fbcf91dcab1a973b8f4bf0e5) · gerçek tx |
| ExceedsSafeSize, agent 10.000 USDT | [0x80aeb849…667a6](https://explorer-test.avax.network/c-chain/tx/0x80aeb84999c64df29bec84dccedd6addb3b1c22adac4e69abd74fc29eb2667a6) · gerçek tx |
| BadSigner, veri kesintisi sahnesinde yetkisiz imza | [0x0b05e13f…de98e](https://explorer-test.avax.network/c-chain/tx/0x0b05e13fa25cb379d62f715820266a32db08250b40b19e2474940b5311ede98e) · gerçek tx |
| AlreadyUsed, taze onayın ikinci kullanımı | [0xa1ad9514…f99a80](https://explorer-test.avax.network/c-chain/tx/0xa1ad95144f813310c2b6c96457b35be32f71c3290f53d632f2b46baffbf99a80) · gerçek tx |
| StaleScore, eski ve kullanılmış onay | [0x0b290257…233a3](https://explorer-test.avax.network/c-chain/tx/0x0b29025776a1f03d8304fd01144ebe88741fe1d760ec405e5b8ebac9b91233a3) · gerçek tx |

Ana listeye ek hazırlık işlemi: **IntentApproved, 1 USDT**, [0x0b4cfc04…d23530](https://explorer-test.avax.network/c-chain/tx/0x0b4cfc04d3c91d5fe0fe09667d66eb07ef1bc630c8cec6b13ab47fe07ad23530). Bu onay tüketilip 3 saniye sonra yeniden gönderilerek AlreadyUsed kanıtlandı.

Geçmiş hata kaydı ayrıca korunur: simülasyon yolundan istenmeden gönderilen IntentApproved, [0x82f9fd48…f702b](https://explorer-test.avax.network/c-chain/tx/0x82f9fd48642b5f0777d85b724762294f634530ee9b38999e9f7eb4837fcf702b). Hata düzeltildi; bu işlem ana 7 tx sayısına dahil değildir.

Diğer kontrat kontrolleri: `RiskTooHigh`, `NoSafeSize`, `BadSide`, `ZeroAddress`. Bunların gerçek tx ile doğrulandığı iddia edilmez. `used[digest]` aynı onayın ikinci kullanımını engeller. Ağ ve kontrat adresinin imzaya katılması başka ağ/kontrat üzerinde kullanımını sınırlar.

## Hata durumları

| Senaryo | Mevcut karşılık | Sınır |
|---|---|---|
| Oracle anahtarı çalınır | Owner `pause`, ardından `setOracle` kullanır | Müdahale gerekir; tek oracle güven varsayımı sürer |
| LLM yanlış yorumlar veya yönlendirilmeye çalışılır | Yapısal veri, deterministik sayılar, argümansız imza aracı, muhafazakâr karar birleştirme | Uygulama karar etiketi zincirde imzalanmıyor |
| Yanlış alarm | Zincirde parametrik risk eşiği, Bonferroni düzeltmesi | Robust z için dağılım kalibrasyonu ampirik olarak kanıtlanmadı |
| Piyasa verisi kesilir/bayatlar | `INSUFFICIENT_DATA`, imza yok | Önceden verilmiş imza kontratın 300 sn penceresinde geçerli kalabilir; tüm eski imzalar anında iptal olmaz |
| Aynı imza yeniden kullanılır | Önce tazelik kontrolü: eski onay `StaleScore`; 300 sn penceresinde tüketilmiş onay `AlreadyUsed` | İki katman da gerçek tx ile ölçüldü |

**İki katmanlı replay koruması:** kontrat tazelik kontrolünü replay kontrolünden önce yapar. Bu yüzden eski bir onay, daha önce kullanılmış olsa da `StaleScore` ile reddedilir; 300 saniyelik geçerlilik penceresindeki kullanılmış onay ise `AlreadyUsed` ile reddedilir. İşlem kaydında eski onay yaklaşık 1655 sn yaşındaydı; taze onay hazırlık işleminden 3 sn sonra tekrar gönderildi. Her iki yol da zincirde gerçek tx ile ölçüldü.

**Acil çıkış / reduce-only bypass yalnızca kavramdır, kodlanmadı.**

## Tarihli örnek ölçümler

Piyasa ve gecikme ölçümleri 17 Ekim 2026 tarihli proje kayıtlarına dayanır. Süreler örnek koşulardır; ölçüm sayısı ve ağ koşulları genelleme yapmaya yeterli değildir.

| Ölçüm | Sonuç | Kaynak / kapsam |
|---|---|---|
| Zincir onayı | Yaklaşık 1,5–2,3 sn | Fuji işlem kayıtları; yeni replay/tazelik kanıtları dahil, zincir kontrolü yaklaşık 2 sn ekliyor |
| LLM istek ve maliyeti | Yaklaşık 3 istek, $0,001/koşu | 17 Ekim koşu kaydı, token sayısından proje fiyat tablosuyla tahmin; güncel tarife iddiası değil |
| LLM ile sahne süresi | Yaklaşık 9–12 sn | Demo kaydı; ayrı agent koşusu 12,919 sn |
| LLM'siz sahne süresi | Yaklaşık 3 sn | Hackathon ölçüm notu; sahne/ağ koşulları değişir |
| BIGTIME-USDT, 1.000 USDT | 10,8 bps kayma | Hackathon ölçüm notu |
| BIGTIME-USDT, 10.000 USDT | 1284 bps kayma | Hackathon ölçüm notu: 10× tutar, 100× üzerinde kayma oranı |
| ZBCN-USDT, 1.000 USDT | `ONAY`, skor yaklaşık 523, güvenli tutar yaklaşık 5.200–5.460 USDT, kayma yaklaşık 13 bps | Son hackathon ölçüm notu; canlı tahtada değişir |
| Gün içi skor aralığı | 323–2841; eşik 5000 | Hackathon ölçüm notu; eşik zincirde parametrik |
| Epizodik hafıza | 20 parite, 60 sn aralık | Logger yapılandırması; çalışan sürecin güncel durumu ayrıca kontrol edilmelidir |
| Python testleri | **87 geçti / 87** | Ağsız test koşusu; ortam dosyası yüklemesi kapalı ve açık kontrat adresi ortam değişkeninden verilmişti. Gerçek `.env` yükleme entegrasyonu bu koşuda sınanmadı |
| Solidity testleri | 14 geçti / 14 | 17 Ekim geliştirme kaydı; bu dokümantasyon düzenlemesinde yeniden çalıştırılmadı |

## Testleri çalıştırma

Python bağımlılıkları kurulduktan sonra:

```bash
python -m pytest -q
```

Solidity testleri için Foundry ve npm bağımlılıkları gerekir:

```bash
npm ci
forge test -vv
```

`test/vector.json` Python ve Solidity imza özetlerinin byte düzeyinde uyumunu sınar. `test/vector_fuji.json` Fuji kontrat adresine ait sabit bir test vektörüdür; içindeki test imzası canlı oracle imzası değildir.

## ATK adaptöründe doğrulanan veri biçimi

17 Ekim 2026 tarihinde ATK CLI 1.4.8 ile gözlenen davranış:

- Emir tahtası için `--sz 400` kullanılır; daha büyük değerler denemelerde reddedildi.
- Tahta seviyelerindeki miktar baz varlık birimindedir. USDT derinliği `fiyat × miktar` ile hesaplanır.
- Ticker alanı `volCcy24h` quote varlık hacmini, `vol24h` baz varlık hacmini gösterir.
- 400 seviye her zaman ±%2 fiyat aralığını kapsamaz. `book_truncated` bu sınırlamayı taşır.
- Mumlar yeniden eskiye sıralı gelir; `confirm=0` tamamlanmamış mumu gösterir.
