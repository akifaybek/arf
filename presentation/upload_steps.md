# Google Slaytlar'a yükleme ve teslim

## Sunum bağlantısını oluştur

1. Tarayıcıda [Google Drive](https://drive.google.com) aç ve hesabına gir.
2. Sol üstte **Yeni** düğmesine, ardından **Dosya yükleme** seçeneğine tıkla.
3. Dosya seçicide **Cmd+Shift+G** tuşlarına bas. `/Applications/arf/presentation` yazıp Enter'a bas.
4. **Arf.pptx** dosyasını seç ve **Aç** düğmesine bas. Yüklemenin bitmesini bekle.
5. Drive'daki dosyaya sağ tıkla → **Birlikte aç** → **Google Slaytlar**.
6. Sunumu açtıktan sonra 10 slaytı sırayla kontrol et. Okların yönüne, Türkçe karakterlere ve 8. slayttaki işlem bağlantılarına bak. Son slaytta teşekkür, GitHub ve web simülasyonu bağlantıları var. Konuşmacı notları alt panelde görünmüyorsa **Görünüm → Konuşmacı notlarını göster** seçeneğini aç; gerekirse `speaker_notes.md` dosyasından kopyala.
7. Sağ üstte **Paylaş** düğmesine bas.
8. **Genel erişim** altında **Kısıtlı** menüsünü aç → **Bağlantıya sahip olan herkes** seç.
9. Yetkiyi **Görüntüleyen** bırak. **Bağlantıyı kopyala**, ardından **Bitti** düğmesine bas.
10. **Cmd+Shift+N** ile gizli pencere aç, bağlantıyı yapıştır ve oturum açmadan sunumun açıldığını kontrol et. Hesap politikası herkese erişimi engelliyorsa izin veren hesabı kullan.
11. `presentation/form_answers.md` içindeki `[GOOGLE SLAYTLAR LİNKİ]` yerine kopyaladığın bağlantıyı yapıştır. README'deki aynı alanı da güncelle.

Form Google Slaytlar/Canva bağlantısı istiyor; yerel PPTX dosya yolunu sunum bağlantısı alanına yazma.

## Yeniden üretme

`build_deck.py` yalnızca presentation klasörüne yazar ve proje modüllerini yüklemez. `python-pptx` varsa proje ana dizininde:

```bash
python presentation/build_deck.py
```

Eksikse, etkin sanal ortamda `python -m pip install python-pptx` çalıştır, ardından üretim komutunu tekrar çalıştır. Bu teslim mevcut paket bulunan Codex belge Python ortamıyla üretildi; proje bağımlılık dosyası değiştirilmedi.

`validation.json` başlıkları ve not uzunluklarını, `speaker_notes.md` bütün konuşma metnini içerir. Toplam hedef 7 dakikadır; canlı demo sırasında bekleme dahil gerçek süreyi kronometreyle prova et.

## Teslim öncesi

- Builder Hub e-postası, ad soyad ve sunum bağlantısını form metnine ekle.
- Video yüklendiyse README'deki `[LİNK EKLENECEK]` alanını güncelle.
- Repo bağlantısını ve sunum/video paylaşımını gizli pencerede açarak denetle.
- Hackathon takvimi: 17:45 kod dondurma, 19:00 form teslimi, 20:00 finalist sunumları; saatler Türkiye saati. Güncel organizatör duyurusu varsa onu esas al.
