# Arf konuşmacı notları

Hedef toplam: 420 saniye (7 dakika), canlı demo dahil. Gerçek süre prova ile doğrulanacak.

## 1. Arf — 35 sn

Arf, AI trading agent'lar için işlem öncesi icra ve likidite kalkanı; tek kişilik takım olarak OKX Agent Trade Kit ile topladığım piyasa verisini Avalanche üzerindeki devre kesiciye bağlıyorum. Cahit Arf ve Arf değişmezine gönderme yapan adı, sistemin koruduğu tek koşulu hatırlatıyor: hiçbir emir tahtanın taşıyabileceğinden büyük olamaz. Bugün önce icra maliyetinin tutarla nasıl değiştiğini, ardından çalışan karar akışını ve en önemlisi veri bozulduğunda ne olduğunu göstereceğim; iddialarımda geçmiş gerçek zincir işlemlerini, canlı ölçümü ve simülasyonu ayrı tutacağım.

## 2. Tahta emri kaldırabilecek mi? — 40 sn

ATK ile binlerce trading agent yazılacak; tahtanın emri kaldırıp kaldıramayacağını bilmeyen agent kendini batırır, çünkü aynı paritede tutar büyüdükçe icra maliyeti doğrusal artmaz. Hackathon ölçüm notundaki BIGTIME örneğinde bin USDT için kayma on virgül sekiz baz puanken on bin USDT için bin iki yüz seksen dört baz puan; tutar on kat, kayma oranı yüz kattan fazla büyüyor. Bunlar geçmiş bir tahta anının ölçümleri, canlı fiyat veya garanti değil; agent'ın her emir öncesinde güncel likiditeyi sorgulaması tam bu yüzden gerekli.

## 3. Her emirden önce icra karnesi — 40 sn

Agent check_execution çağrısına sembolü, alış veya satış yönünü ve USDT tutarını verir; Arf deterministik risk skorunu, güvenli tutarı ve gerekiyorsa bölme önerisini üretir. Veri taze ve yeterliyse oracle bu sayıları imzalar, Avalanche kontratı da imzalı sınırı aşan niyeti reddeder; bölme hesabı hem agent'ta hem kontratta tutarın güvenli tutara bölümünün yukarı yuvarlanmasıdır. Buradaki değişmez imzalı güvenli tutarla sınırlıdır, gelecekteki tahta dolumunu garanti etmez ve prototip kontrat OKX'te emir yürütmez; güvenli tutar sıfırsa bölme önerisi de yoktur.

## 4. Veriden zincire — 40 sn

Mimari ATK CLI ile başlıyor; tüm piyasa verisi TR sitesi ve JSON çıktısı üzerinden gelirken logger yirmi paritenin epizodik hafızasını altmış saniye aralıkla tutuyor. Metrikler anlık tahtayı geçmiş medyan derinlikle karşılaştırıyor, piyasa rejimi için robust z hesaplıyor ve kayma sınırından güvenli tutarı çıkarıyor; LLM bu araçları çağırıyor ama sayısal sonucu yeniden yazamıyor. İmza yalnızca yeterli ve taze veriyle üretiliyor, kontrat ise imza ve tutar sınırını denetliyor; yüz yirmi saniyelik piyasa veri eşiği ile kontratın üç yüz saniyelik imza geçerlilik penceresi ayrı kontroller.

## 5. LLM planlar, metrikler hesaplar — 40 sn

Planlayıcının scan_market, get_candles, get_orderbook, compute_metric ve sign_score araçları var; hangi kanıta bakacağını seçmesi agentic tarafı oluşturuyor, karar izinden de bu seçimi gösterebiliyorum. Sayılar deterministik, sign_score argümansız ve karar birleştirme sırası veri yetersiz, red, böl, onay şeklinde; LLM uygulama kararını yalnızca daha muhafazakâr yapabilir. Ana sağlayıcı Anthropic, ardından Gemini ve deterministik plan geliyor; dürüst sınır şu ki kontrat LLM etiketini değil imzalı sayıları denetler, dolayısıyla entegratör uygulama kararını da uygulamalı ve her LLM sıkılaştırmasının zincirde zorlandığını iddia etmiyorum.

## 6. Canlı demo: üç sahne — 90 sn

Şimdi aynı ZBCN-USDT tahtasında önce bin USDT niyetini açıyorum, karar izini ve imzalı güvenli tutarı gösteriyorum; tahta uygunsa sonuç onay, ama tutar ve sonuç canlı veriyle değişebilir. İkinci sahnede on bin USDT güvenli tutarı aştığında ExceedsSafeSize cevabını gösterip agent'ın önerdiği parça sayısıyla kontratın hesabını karşılaştırıyorum; parça sayısını önceden sabitlemiyorum. Üçüncü sahne açıkça veri kesintisi simülasyonu: oracle imza üretmiyor, trader'ın kendi imzası BadSigner alıyor; ekrandaki ön izleme eth_call, alttaki explorer bağlantısı ise geçmiş gerçek işlemin kanıtı, ağ sorunu olursa deterministik yedeğe veya videoya geçiyorum.

## 7. Kötü senaryoda ne oluyor? — 45 sn

Organizatörün sorusunu doğrudan cevaplayayım: veri bozulunca imza yok, yetkisiz imza BadSigner alıyor ve tüketilmiş onay tekrar kullanılınca AlreadyUsed devreye giriyor. Oracle anahtarı çalınırsa owner pause ve setOracle ile müdahale ediyor; yanlış alarm için zincirde parametrik eşik ve nominal Bonferroni düzeltmesi var, ancak gerçek yanlış alarm oranını ölçtüğümü söylemiyorum. LLM'e sadece yapısal veri gidiyor ve sayılar deterministik kalıyor; tek oracle güveni sürüyor, önceden verilmiş imzalar geçerlilik penceresinde kullanılabilir ve acil çıkış yolu yalnızca kavram, bu yüzden çoklu oracle ile eşik imza sonraki adım.

## 8. Ölçülen kanıt, açık sınırlar — 40 sn

Zincirde IntentApproved, ExceedsSafeSize ve BadSigner gerçek işlem kayıtlarıyla gösterildi; AlreadyUsed ve StaleScore için elimizde şu anda yalnızca eth_call var, gerçek işlem hash'leri bekliyor. Kayıtlardaki zincir onayı yaklaşık iki saniye, LLM maliyeti koşu başına yaklaşık binde bir dolar ve bunlar örnek koşuların sonuçları; bu oturumda seksen iki Python testi geçti, on dört Solidity testi ise STATUS kaydından geliyor. Yirmi paritelik epizodik hafıza var ama tek oracle ve testnet sınırları sürüyor; ayrıca simülasyonun bir kez istemeden işlem gönderdiğini saklamıyorum, dry_run kilidi ve sekiz güvenlik testiyle bu yol kapatıldı.

## 9. Agent'lar için icra kontrolü servisi — 50 sn

İlk müşteri ATK ile agent geliştiren ekipler ve bireysel kullanıcılar; önerilen model temel kontrolü ücretsiz tutup gerçek zamanlı API erişimini ücretlendirmek, ama ücret ödeme isteği ve gelir henüz doğrulanmadı. Sonraki adım çoklu oracle ve eşik imza, EIP-712 ile daha okunur imzalama, Almgren–Chriss icra planı, ardından OKX.ai listeleme ve çağrı başına ödeme; bunlar bugün kodlanmış özellikler değil, mainnet veya Avalanche L1 geçişi de bu aşamaların sonrasında değerlendirilecek. Bugün gösterebildiğim değer, güncel ATK tahtasından çıkan sayısal sınırın Fuji üzerinde onay veya redde dönüşmesi; repo ve kontrat açık, her emirden önce aynı soruyu soruyoruz: bu tahta bu emri kaldırır mı?​
