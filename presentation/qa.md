# Jüri soruları ve kısa cevaplar

Kanıt ayrımı: bu cevaplar repo ve 17 Ekim 2026 hackathon notlarına dayanır. Yeni zincir işlemi veya ücretli servis yayını yapılmadı.

## Kriptografi

**Neden EIP-191?**

Prototipte Python ve Solidity'nin aynı payload'ı doğruladığı yolu kullandık. `abi.encode` içinde sembol hash'i, yön, risk skoru, güvenli tutar, zaman, chainId ve kontrat adresi var. EIP-712 daha açık tür ve alan ayrımı için sonraki adım, bugün uygulanmadı.

**Replay nasıl engelleniyor?**

Kontrat başarılı niyetin `digest` değerini `used` içinde tüketir; ikinci kullanım `AlreadyUsed` olur. Ağ ve kontrat adresi payload'a bağlıdır. AlreadyUsed şu anda `eth_call` ile doğrulandı, gerçek tx hash'i **[BEKLİYOR]**.

**İmza kimin adına, hangi emre bağlı?**

Sembol ve yön imzada, emir tutarı ve çağıran adres imzada yok. Güvenli tutar sınırı uygulanır ve ilk geçerli kullanım digest'i tüketir. Müşteri kimliği veya müşteri bazlı nonce bağlama prototipte yok; bu bir entegrasyon sınırıdır.

**Oracle'a neden güveneyim, anahtarı çalınırsa?**

Tek oracle mevcut güven varsayımı. Owner `pause` ile durdurabilir, `setOracle` ile anahtarı döndürebilir; bunun zamanında yapılması gerekir. Çoklu bağımsız oracle ve eşik imza sonraki adım, bugün yok.

**Bonferroni tam olarak neyi garanti ediyor?**

20 parite için nominal α=0,05 üzerinden iki yönlü z eşiği yaklaşık 3,023 hesaplanır. Geçerli tekil testler varsayımı altında aile düzeyindeki yanlış alarm sınırını hedefler; robust z dağılımının ampirik kalibrasyonunu, tüm metrikleri ve zaman boyunca oranı doğruladığımızı iddia etmiyoruz. MAD sıfırsa z ölçülemez, sıfır riskmiş gibi sunulmaz.

**İmza taze ama piyasa verisi bayat olursa?**

İmza üretiminde piyasa verisi 120 saniyeyi aşarsa veya alınamazsa imza yok. Kontrat ayrı olarak imzanın 300 saniyelik geçerliliğini kontrol eder. Bu iki pencere aynı şey değil; önceden verilmiş imza veri kesildikten sonra da pencere içinde geçerli kalabilir.

**LLM'in “RED” demesi zincirde zorunlu mu?**

Uygulama kararı yalnızca daha muhafazakâr birleşir, fakat kontrat LLM karar etiketini doğrulamaz. Veri yeterliyse RED/BOL kararlarında da imzalı sayılar üretilebilir; zincir bu sayıların eşiklerini uygular. Entegratör uygulama kararını da dikkate almalı; bütün LLM sıkılaştırmalarının zincirde zorlandığını söylemiyoruz.

## OKX

**ATK'yı nerede kullanıyorsunuz?**

Canlı ticker, orderbook, candles ve instruments verilerinde. Bütün piyasa verisi ATK CLI'dan, `OKX_SITE=tr` ve `--json` ile geliyor; doğrudan OKX REST/WS çağrısı yok. Emir yetkili profil ve gerçek OKX emir icrası bu prototipin parçası değil.

**OKX.ai'de çalışan ürün mü?**

Henüz listelenmedi. README'de giriş/çıkış JSON sözleşmesi var ve yalnızca “A2MCP'ye uyarlanabilir şema” diyoruz. Çalışan Python girişi var, MCP/HTTP servisinin ve ödeme katmanının hazır olduğunu iddia etmiyoruz.

**İş modeli ne?**

Agent geliştiricileri ve bireylere temel kontrol ücretsiz, gerçek zamanlı/API erişimi ücretli servis olarak tasarlandı. Fiyat ve ödeme isteği **[DOĞRULANACAK]**. HTTP 402 ile çağrı başına ödeme sonraki adım.

**Maliyet ve gecikme?**

Proje kayıtlarında LLM koşusu yaklaşık 3 istek ve token tablosuyla yaklaşık $0,001 maliyet; sahneler LLM ile yaklaşık 9–12 saniye, LLM'siz yaklaşık 3 saniye. Zincir onayı yaklaşık 1,7–2,3 saniye. Bunlar örnek koşu ölçümleri, uçtan uca 2 saniye veya servis garantisi demiyoruz.

## Avalanche DevRel

**Neden Fuji / C-Chain?**

Testnet üzerinde gerçek işlem makbuzlarını, onayı ve revert yolunu göstermek için Fuji'yi kullandık. C-Chain'in EVM ortamında mevcut Solidity, OpenZeppelin ve Python imza araçlarıyla ilerledik. Bu tercih için başka ağlardan daha hızlı/ucuz olduğuna dair karşılaştırmalı ölçüm sunmuyoruz.

**Mainnet veya Avalanche L1 planı nedir?**

Önce oracle güveni ve imza yetkilendirmesi güçlendirilecek, eşikler kalibre edilecek ve icra entegrasyonu doğrulanacak. Mainnet / Avalanche L1 geçişi sonraki adım; bugün deploy yalnızca Fuji'de. Maliyet, yük ve L1 gereksinimi **[DOĞRULANACAK]**.

**Kontrat gerçekten trade yapıyor mu?**

Kontrat niyetin imzasını ve sınırlarını doğrular, `IntentApproved` üretir veya revert eder. Kendisi OKX üzerinde emir yürütmez. Kontrolü zorunlu çağıran bir icra entegrasyonu gerekir; dışarıdan verilen tüm emirleri engellediği iddiası yok.

**Hangi revert'ler gerçekten zincirde?**

Gerçek tx kayıtlarında ExceedsSafeSize ve BadSigner var, IntentApproved da gerçek tx ile kaydedildi. AlreadyUsed ve StaleScore şimdilik `eth_call`; hash'ler **[BEKLİYOR]**. Diğer kontrollerin kontrat/test kapsamını gerçek tx kanıtıyla karıştırmıyoruz.

## Startup / ürün

**Müşteri kim, neden ödesin?**

ATK ile agent geliştiren ekip ve birey, her emir öncesinde likidite ve icra maliyeti kontrolü ister. Servisin değeri tek çağrıda ölçüm, karar izi ve zincirde doğrulanabilir sınır sağlamasıdır. Müşteri görüşmesi, ödeme isteği veya gelir verisi **[DOĞRULANACAK]**.

**Neden sabit emir limiti yetmiyor?**

Tahta ve piyasa rejimi değişiyor. BIGTIME hackathon ölçümünde 1.000 USDT için 10,8 bps, 10.000 USDT için 1284 bps kayma görüldü. Sabit limit yerine o anki tahta üzerinden güvenli tutar hesaplıyoruz; bu örnek her zamanda aynı sonucu vaat etmez.

**Parçalara bölünce kesin güvenli mi?**

Hayır, öneri `ceil(amount / maxSafeSize)` hesabı ve tahtanın yeniden dolacağı varsayımıdır. Dolum hızını ölçmüyoruz; her parça öncesi tekrar kontrol gerekir. Almgren–Chriss icra planı henüz kodlanmadı.

**Eşik 5000 keyfî mi?**

Eşik ve ağırlıklar tasarım tercihleri, kalibre edilmiş parametreler değil. Gün içi gözlenen skor aralığı 323–2841; bu aralık eşik doğruluğunu kanıtlamaz. Eşik zincirde görünür ve owner tarafından parametrik olarak değiştirilebilir.

**En kötü hata neydi?**

Simülasyon yolu bir kez yanlışlıkla gerçek Fuji tx gönderdi. Kayıt saklandı, `dry_run` kilidi eklendi ve 8 güvenlik regresyon testi yazıldı. Bu oturumda toplam 82 Python testi geçti; hata kaydını README'de açıkça gösteriyoruz.

**Demo sahne 3 gerçek kesinti mi?**

Veri kesintisi simülasyonu, açıkça etiketli. Varsayılan ekrandaki kontrat cevabı `eth_call`; aynı yetkisiz imza senaryosu için geçmiş gerçek BadSigner tx bağlantısı ayrı var. Veri kesintisi ile geçmiş on-chain kanıtını aynı canlı olay gibi sunmuyoruz.
