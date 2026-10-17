# Arf konuşmacı notları

10 slayt. Hedef 7 dakika, canlı demo dahil. Süre prova ile doğrulanacak.

## 1. Arf — 30 sn

Arf, AI trading agent'lar için işlem öncesi icra ve likidite kalkanı; ATK verisini Avalanche üzerindeki bir devre kesiciye bağlıyorum. Adı Cahit Arf ve Arf değişmezine gönderme yapıyor, çünkü sistem tek bir değişmezi koruyor: emir tutarı imzalı güvenli tutarı aşamaz. Bu sunumda problemi, kurduğum akışı ve kötü senaryoda ne olduğunu göstereceğim; canlı uygulama yerelde, internetteki paylaşılabilir sürüm ise açıkça etiketlenmiş kayıtlı bir simülasyon.

## 2. Aynı tahta. Çok farklı icra maliyeti. — 35 sn

ATK ile binlerce trading agent yazılacak; tahtanın emri kaldırıp kaldıramayacağını bilmeyen agent kendini batırır. Hackathon ölçüm notundaki BIGTIME örneğinde bin USDT için kayma on virgül sekiz baz puanken on bin USDT için bin iki yüz seksen dört baz puan; tutar on kat, kayma oranı yüz kattan fazla büyüyor. Bunlar 17 Ekim tarihli tek bir tahta örneği, canlı fiyat veya genel performans garantisi değil; bu nedenle kontrolün her emirden önce tekrarlanması gerekiyor.

## 3. Bir emir için tek değişmez. — 30 sn

Arf’ın sorduğu soru basit: bu emir bu tahtada kaça patlar ve en fazla ne kadarlık emir güvenli? check_execution sembolü, yönü ve tutarı alır; deterministik risk skorunu, güvenli tutarı ve gerekiyorsa bölme önerisini üretir, taze sonuç oracle tarafından imzalanır ve kontrat bu sınırı uygular. Buradaki güvenli tutar anlık tahta ölçümüdür, gelecekteki dolum garantisi değildir ve kontrat OKX üzerinde kendisi emir yürütmez.

## 4. ATK verisinden Fuji kontrolüne. — 40 sn

Piyasa verisi ATK CLI’dan TR sitesi ve JSON çıktısıyla geliyor; logger yirmi paritenin epizodik hafızasını altmış saniye aralıkla tutuyor. Deterministik metrikler kaymayı ve derinliği hesaplıyor, geçmiş medyanla piyasa rejimini karşılaştırıyor, LLM de bu araçların kullanımını planlıyor. Sonuç EIP-191 ile imzalanıp Fuji’de denetleniyor; piyasa verisi için yüz yirmi saniyelik eşik ve kontrattaki üç yüz saniyelik imza penceresi ayrı kontroller.

## 5. LLM planlar. Sayılar deterministik. — 40 sn

Agentic taraf, hangi kanıta hangi araçla bakılacağını seçen LLM planlayıcı; scan_market, get_candles, get_orderbook, compute_metric ve argümansız sign_score araçlarını kullanıyor. Sayılar deterministik hesaplanıyor, karar birleştirmede yalnızca daha muhafazakâr öneri kazanıyor ve sağlayıcılar çalışmazsa deterministik yedek plan devreye giriyor. Dürüst sınır şu: kontrat LLM karar etiketini değil imzalı sayıları denetler, dolayısıyla entegratör uygulama kararını da uygulamalı; serbest kullanıcı metni LLM’e gönderilmez.

## 6. Üç sahnede çalışan sistem. — 85 sn

Şimdi yerel uygulamada önce bin USDT niyetini açıp karar izini, güvenli tutarı ve imzayı gösteriyorum; tahta uygunsa sonuç onay, canlı veri değiştiğinde sonuç da değişebilir. Sonra on bin USDT niyetinde güvenli tutar aşılırsa ExceedsSafeSize ve N parçaya bölme önerisini karşılaştırıyorum; N’yi önceden sabitlemiyorum, agent ve kontrat aynı yukarı yuvarlama hesabını kullanıyor. Üçüncü sahne açıkça veri kesintisi simülasyonu: oracle imza üretmiyor ve trader’ın kendi imzası BadSigner alıyor; varsayılan yerel kontrat cevabı eth_call ön izlemesi, gerçek işlem kanıtları ayrı ve internet sürümü yalnızca kayıtlı örnekleri gösteriyor.

## 7. Veri bozulursa imza yok. — 45 sn

Kötü senaryoda önce veri kesintisini gösteriyorum: imza yok, yetkisiz imza BadSigner alıyor; replay’de ise kontrat önce tazeliğe baktığı için eski kullanılmış onay StaleScore, geçerlilik penceresindeki kullanılmış onay AlreadyUsed alıyor ve iki yol da gerçek tx ile kaydedildi. Oracle anahtarı çalınırsa owner pause ve setOracle ile müdahale edebiliyor, ama tek oracle güveni devam ediyor. LLM için yapısal veri ve deterministik sayılar, yanlış alarm için parametrik eşik ve nominal Bonferroni düzeltmesi var; gerçek yanlış alarm oranını ölçtüğümü söylemiyorum ve acil çıkış yolu yalnızca kavram.

## 8. Zincirde doğrulandı. — 45 sn

Ana kanıt listesinde yedi gerçek işlem var: IntentApproved kayıtları ve demo kapsamındaki ExceedsSafeSize, BadSigner, AlreadyUsed ve StaleScore kontrolleri; taze replay için bir USDT hazırlık işlemi ayrıca kullanıldı. Tablodaki işlem kimlikleri tıklanabilir, Python testlerinin güncel sayısı seksen yedi ve Solidity için on dört test kaydı var; burada Python koşuları ortam dosyası okunmadan, açık kontrat adresiyle doğrulandı, Solidity sayısı STATUS kaydından geliyor. Yaklaşık iki saniye zincir onayı ve koşu başına yaklaşık 0,001 USD LLM maliyeti proje kayıtlarına dayanıyor, bütün uygulamanın iki saniyede tamamlandığı anlamına gelmiyor; tek oracle ve testnet sınırları devam ediyor, risk ağırlıkları tasarım tercihi.

## 9. Bugün çalışan. Sonra geliştirilecek. — 45 sn

Bugün yerelde çalışan canlı ATK ve imzalı skor akışı, Fuji kontratı ve paylaşılabilir bir internet simülasyonu var; internet sürümü kayıtlı örnekler kullanıyor, yeni veri veya imza üretmiyor. Hedef müşteri ATK ile agent geliştiren ekipler ve bireyler, tasarlanan iş modeli temel kontrolü ücretsiz tutup gerçek zamanlı API erişimini ücretlendirmek ama fiyat ve ödeme isteği henüz doğrulanmadı. Çoklu oracle, eşik imza, EIP-712, Almgren–Chriss icra planı, OKX.ai listeleme ve çağrı başına ödeme sonraki adımlar; bunları bugün kodlanmış özellik gibi sunmuyorum.

## 10. Teşekkürler. — 25 sn

Teşekkür ederim, Arf’ın amacı her emirden önce tahtanın taşıyabileceği tutarı görünür ve doğrulanabilir kılmak. GitHub bağlantısında kaynak kod ve gerçek işlem kanıtları, internet bağlantısında ise kayıtlı verilerle çalışan etkileşimli simülasyon var. Canlı sistemi yerelde göstermeye ve sorularınızı cevaplamaya hazırım.
