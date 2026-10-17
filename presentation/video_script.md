# Arf yedek demo videosu

Hedef kayıt süresi **2–3 dakika**. Aşağıdaki süreler çekim planıdır, ölçülmüş performans değildir. Üç sahne sırası korunur; canlı tahta aynı kararları vermeyebilir.

## Kayıttan önce

1. macOS'te sağ üstte Denetim Merkezi → **Odak** → **Rahatsız Etme** seç. E-posta, mesaj ve ortam dosyası pencerelerini kapat.
2. Demo zaten açıksa tarayıcıdaki Arf sekmesine geç. Açık değilse Terminal'i aç, aşağıdaki komutları ayrı ayrı yazıp her satırda Enter'a bas:

   ```bash
   cd /Applications/arf
   source .venv/bin/activate
   streamlit run app.py
   ```

3. Terminalin gösterdiği yerel adresi tarayıcıda aç. Terminali arka plana al.
4. Solda **Parite** alanını `ZBCN-USDT` bırak. **LLM kullan** açık, **Zincire gönder** kapalı olsun. Bu çekim yeni tx göndermez; ekrandaki kontrat cevapları `eth_call` ön izlemesidir.
5. README'deki gerçek **BadSigner** işlem bağlantısını ikinci sekmede aç. Üçüncü sekmede GitHub reposunu aç: [akifaybek/arf](https://github.com/akifaybek/arf).
6. **Cmd+Shift+5** tuşlarına bas. Alttaki çubukta **Tüm Ekranı Kaydet** simgesini seç. **Seçenekler → Mikrofon** altında kendi mikrofonunu seç; kayıt yerini **Masaüstü** yap. **Kaydet** düğmesine bas.

## Çekim sırası

| Hedef süre | Ekranda yapılacak | Söylenecek |
|---|---|---|
| 0:00–0:20 | Arf başlığını ve soldaki ayarları göster. İmleci **Zincire gönder** kutusuna götür. | “Arf, AI trading agent'lar için işlem öncesi icra ve likidite kalkanı. ATK tahtasından icra maliyetini ölçüyor, güvenli tutarı imzalıyor ve Avalanche Fuji'deki devre kesiciye bağlıyor. Bu kayıtta zincire gönderim kapalı, kontrat cevaplarını ön izlemede göstereceğim.” |
| 0:20–0:55 | **Sahne 1: 1.000 USDT** düğmesine bas. Koşu bitince soldaki araç izini, ortadaki riskScore ve maxSafeSize'ı göster. | “Agent önce araçları seçiyor, sayıları deterministik metrikler hesaplıyor. Bu tahtada bin USDT için sonucu ve imzayı görüyoruz. Güvenli tutar anlık, sabit bir değer değil.” |
| 0:55–1:30 | **Sahne 2: 10.000 USDT** düğmesine bas. Bölme önerisiyle sağdaki `ExceedsSafeSize` ve `suggestedParts` alanlarını göster. | “Tutarı on bin USDT'ye çıkarıyorum. Güvenli tutar aşılırsa kontrat ExceedsSafeSize diyor. Agent'ın önerdiği parça sayısıyla kontratın hesabı birebir aynı; parçalar arasında tahtanın yeniden dolduğunu varsayıyoruz, dolum hızını ölçmüyoruz.” |
| 1:30–2:05 | **Sahne 3: veri kesintisi (SİMÜLASYON)** düğmesine bas. Kırmızı simülasyon etiketi, `VERI_YETERSIZ`, imza yok ve `BadSigner` cevabını göster. | “Bu sahne veri kesintisi simülasyonu, gerçek bir piyasa kesintisi iddiası değil. Veri yoksa oracle imzalamıyor. Trader kendi imzasıyla zorladığında kontrat BadSigner ile reddediyor.” |
| 2:05–2:30 | İkinci sekmedeki geçmiş gerçek BadSigner tx'ini ve ağın Fuji olduğunu göster. Ardından GitHub sekmesine geç. | “Az önceki ekran eth_call ön izlemesiydi. Bu bağlantı aynı kötü senaryonun geçmiş gerçek Fuji işlem kanıtı. Prototip tek oracle ve testnet üzerinde; repo, diğer işlem kanıtları ve varsayımlar açık.” |
| 2:30–2:40 | GitHub README girişini göster. | “Arf'ın tek değişmezi: hiçbir emir tahtanın taşıyabileceğinden büyük olamaz.” |

Kayıt bitince üst menü çubuğundaki **kare durdur** simgesine tıkla veya **Cmd+Control+Esc** tuşlarına bas. Kaydı açıp sesin ve yazıların okunurluğunu kontrol et. İstersen QuickTime'da **Düzenle → Kısalt** ile baştaki ve sondaki beklemeyi kes, **Dosya → Kaydet** seç.

## Canlı koşul farklıysa

- LLM gecikirse soldaki **LLM kullan** kutusunu kapat ve ilgili sahneye yeniden bas. “Şimdi deterministik yedek plan çalışıyor” de; bu koşuyu LLM koşusu olarak sunma.
- Sahne 1/2 beklenen kararı vermezse “Tahta değiştiği için karar değişti” de. Gerçek sayıları oku; ONAY/BOL sonucunu olmuş gibi anlatma. Önceden kaydedilmiş örneği ve README'deki gerçek tx kanıtını göster.
- RPC erişilemezse canlı zincir cevabı iddia etme. Geçmiş gerçek işlemin bağlantısına geç. Kayıt 3 dakikayı aşarsa beklemeleri kısalt, sonuçları değiştirme.

## YouTube'a liste dışı yükleme

1. [YouTube](https://www.youtube.com) aç ve hesabına gir.
2. Sağ üstte **Oluştur** kamera simgesine, sonra **Video yükle** seçeneğine tıkla.
3. **Dosya seç** düğmesine bas. Masaüstündeki ekran kaydını seç → **Aç**.
4. Başlık: **Arf — ATK × Avalanche Fuji demo**. Açıklamaya repo bağlantısını ve “Sahne 3 veri kesintisi simülasyonudur, kontrat ön izlemeleri eth_call'dur” yaz.
5. **Kitle** alanını içeriğe uygun seç. Bu teknik demo çocuklar için özel hazırlanmadıysa **Hayır, çocuklara özel değil** seç.
6. Video öğeleri ve kontroller sayfalarında **İleri** düğmesine bas.
7. **Görünürlük → Liste dışı** seç. Son düğme arayüzde **Kaydet** veya **Yayınla** görünebilir; ona bas.
8. İşlemenin tamamlanmasını bekle. Video bağlantısını kopyala; gizli pencerede açıp görüntü ve sesi kontrol et.
9. Bağlantıyı README'deki `[LİNK EKLENECEK]` alanına yapıştır. Formda video alanı varsa aynı bağlantıyı kullan.

Menü adları hesap diline göre değişebilir. Liste dışı bağlantıyı bilen herkes videoyu izleyebilir.
