"""Arf sunumunu üretir. Yalnızca bu klasöre yazar; proje modülü yüklemez.

Kullanım: python presentation/build_deck.py
Bağımlılık: python-pptx (proje requirements.txt dosyasından bağımsız).
"""
from pathlib import Path
import json
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

ROOT = Path(__file__).resolve().parent
BG = "101923"
FG = "F4F7FA"
MUTED = "B6C4D1"
CYAN = "62E4CD"
AMBER = "FFC56D"
RED = "FF8E88"
PANEL = "1C2B39"
FONT = "Arial"
CONTRACT = "0xddE4C78F831f082E8AFDF716266bd1338B591159"
GITHUB = "https://github.com/akifaybek/arf"
TX_BAD = "0x0b05e13fa25cb379d62f715820266a32db08250b40b19e2474940b5311ede98e"
prs = Presentation()
prs.slide_width = Inches(13.333333)
prs.slide_height = Inches(7.5)


def rect(s, x, y, w, h, color=PANEL):
    sh = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    sh.fill.solid()
    sh.fill.fore_color.rgb = RGBColor.from_string(color)
    sh.line.fill.background()
    return sh


def text(s, x, y, w, h, value, size=24, color=FG, bold=False, align=PP_ALIGN.LEFT, link=None):
    sh = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = sh.text_frame
    tf.clear()
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0)
    tf.margin_top = tf.margin_bottom = Inches(0.03)
    for i, line in enumerate(value.split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(8)
        r = p.add_run()
        r.text = line
        r.font.name = FONT
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.color.rgb = RGBColor.from_string(color)
        if link:
            r.hyperlink.address = link
    return sh


def slide(title, notes, seconds):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = RGBColor.from_string(BG)
    rect(s, .6, .52, .65, .06, CYAN)
    text(s, .65, .83, 12, .82, title, 38, bold=True)
    text(s, .65, 7.05, 11.6, .27, "Arf  /  OKX Agent Trade Kit × Avalanche  /  17 Ekim 2026", 12, MUTED)
    text(s, 12.15, 7.02, .5, .3, f"{len(prs.slides):02}", 13, MUTED)
    s.notes_slide.notes_text_frame.text = notes
    records.append({"slide": len(prs.slides), "title": title, "target_seconds": seconds,
                    "note_characters": len(notes), "note_words": len(notes.split()), "notes": notes})
    return s


def rows(s, items, y=2.0, step=1.02, size=27):
    for i, item in enumerate(items):
        text(s, .75, y + step*i, .35, .45, "•", size, CYAN)
        text(s, 1.18, y + step*i, 11.25, .85, item, size)


records = []
s = slide("Arf", "Arf, AI trading agent'lar için işlem öncesi icra ve likidite kalkanı; tek kişilik takım olarak OKX Agent Trade Kit ile topladığım piyasa verisini Avalanche üzerindeki devre kesiciye bağlıyorum. Cahit Arf ve Arf değişmezine gönderme yapan adı, sistemin koruduğu tek koşulu hatırlatıyor: hiçbir emir tahtanın taşıyabileceğinden büyük olamaz. Bugün önce icra maliyetinin tutarla nasıl değiştiğini, ardından çalışan karar akışını ve en önemlisi veri bozulduğunda ne olduğunu göstereceğim; iddialarımda geçmiş gerçek zincir işlemlerini, canlı ölçümü ve simülasyonu ayrı tutacağım.", 35)
text(s, .75, 2.0, 11.8, 1.5, "AI trading agent'lar için\nişlem öncesi icra ve likidite kalkanı", 36, bold=True)
text(s, .77, 4.05, 11.8, .6, "OKX Agent Trade Kit × Avalanche", 28, CYAN)
text(s, .77, 5.0, 11.8, .8, "Cahit Arf'a gönderme: tek bir değişmezi korumak.", 23, MUTED)

s = slide("Tahta emri kaldırabilecek mi?", "ATK ile binlerce trading agent yazılacak; tahtanın emri kaldırıp kaldıramayacağını bilmeyen agent kendini batırır, çünkü aynı paritede tutar büyüdükçe icra maliyeti doğrusal artmaz. Hackathon ölçüm notundaki BIGTIME örneğinde bin USDT için kayma on virgül sekiz baz puanken on bin USDT için bin iki yüz seksen dört baz puan; tutar on kat, kayma oranı yüz kattan fazla büyüyor. Bunlar geçmiş bir tahta anının ölçümleri, canlı fiyat veya garanti değil; agent'ın her emir öncesinde güncel likiditeyi sorgulaması tam bu yüzden gerekli.", 45)
text(s, .75, 1.95, 11.8, .65, "Tahtayı bilmeyen agent kendini batırır.", 28)
text(s, .8, 3.0, 5.6, .5, "BIGTIME-USDT  /  1.000 USDT", 23, MUTED)
text(s, .8, 3.65, 5.6, 1.0, "10,8 bps", 54, CYAN, True)
text(s, 7.0, 3.0, 5.5, .5, "BIGTIME-USDT  /  10.000 USDT", 23, MUTED)
text(s, 7.0, 3.65, 5.5, 1.0, "1284 bps", 54, AMBER, True)
text(s, .8, 5.35, 11.8, .7, "10× tutar, 100×+ kayma oranı", 32, bold=True)
text(s, .8, 6.25, 11.8, .4, "ÖLÇÜLEN: hackathon notu, 17 Ekim 2026; canlı tahta değişir.", 16, MUTED)

s = slide("Her emirden önce icra karnesi", "Agent check_execution çağrısına sembolü, alış veya satış yönünü ve USDT tutarını verir; Arf deterministik risk skorunu, güvenli tutarı ve gerekiyorsa bölme önerisini üretir. Veri taze ve yeterliyse oracle bu sayıları imzalar, Avalanche kontratı da imzalı sınırı aşan niyeti reddeder; bölme hesabı hem agent'ta hem kontratta tutarın güvenli tutara bölümünün yukarı yuvarlanmasıdır. Buradaki değişmez imzalı güvenli tutarla sınırlıdır, gelecekteki tahta dolumunu garanti etmez ve prototip kontrat OKX'te emir yürütmez; güvenli tutar sıfırsa bölme önerisi de yoktur.", 40)
text(s, .8, 2.0, 11.8, .65, "check_execution(symbol, side, size)", 30, CYAN, True)
rows(s, ["riskScore + maxSafeSize + bölme önerisi", "EIP-191 imza, Avalanche'ta devre kesici"], y=3.05, step=.9)
rect(s, .75, 5.12, 11.85, 1.2)
text(s, 1.0, 5.35, 11.35, .7, "Değişmez: emir tutarı ≤ maxSafeSize", 32, CYAN, True)

s = slide("Veriden zincire", "Mimari ATK CLI ile başlıyor; tüm piyasa verisi TR sitesi ve JSON çıktısı üzerinden gelirken logger yirmi paritenin epizodik hafızasını altmış saniye aralıkla tutuyor. Metrikler anlık tahtayı geçmiş medyan derinlikle karşılaştırıyor, piyasa rejimi için robust z hesaplıyor ve kayma sınırından güvenli tutarı çıkarıyor; LLM bu araçları çağırıyor ama sayısal sonucu yeniden yazamıyor. İmza yalnızca yeterli ve taze veriyle üretiliyor, kontrat ise imza ve tutar sınırını denetliyor; yüz yirmi saniyelik piyasa veri eşiği ile kontratın üç yüz saniyelik imza geçerlilik penceresi ayrı kontroller.", 45)
boxes = [(0.75, 2.2, 3.25, 1.1, "OKX ATK CLI\nTR / JSON"),
         (5.05, 2.2, 3.25, 1.1, "Epizodik hafıza\n+ metrikler"),
         (9.35, 2.2, 3.25, 1.1, "LLM planlayıcı\n12 araç bütçesi"),
         (9.35, 4.7, 3.25, 1.1, "EIP-191\nimza"),
         (4.55, 4.7, 3.85, 1.1, "RiskCircuitBreaker\nAvalanche Fuji")]
for x, y, w, h, label in boxes:
    rect(s, x, y, w, h)
    text(s, x+.13, y+.12, w-.26, h-.18, label, 23, align=PP_ALIGN.CENTER)
for x1, y1, x2, y2 in [(4.05, 2.75, 4.9, 2.75), (8.35, 2.75, 9.2, 2.75), (10.97, 3.4, 10.97, 4.55), (9.2, 5.25, 8.55, 5.25)]:
    c = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    c.line.color.rgb = RGBColor.from_string(CYAN)
    c.line.width = Pt(3)
    from pptx.oxml.xmlchemy import OxmlElement
    end = OxmlElement("a:tailEnd")
    end.set("type", "triangle")
    c.line._get_or_add_ln().append(end)
text(s, .8, 4.65, 3.3, 1.0, "Veri yok / >120 sn:\nimza yok", 25, RED, True)
text(s, .8, 6.25, 11.8, .4, "Ölçüm ve araç sonuçları karar izinde görünür.", 20, MUTED)

s = slide("LLM planlar, metrikler hesaplar", "Planlayıcının scan_market, get_candles, get_orderbook, compute_metric ve sign_score araçları var; hangi kanıta bakacağını seçmesi agentic tarafı oluşturuyor, karar izinden de bu seçimi gösterebiliyorum. Sayılar deterministik, sign_score argümansız ve karar birleştirme sırası veri yetersiz, red, böl, onay şeklinde; LLM uygulama kararını yalnızca daha muhafazakâr yapabilir. Ana sağlayıcı Anthropic, ardından Gemini ve deterministik plan geliyor; dürüst sınır şu ki kontrat LLM etiketini değil imzalı sayıları denetler, dolayısıyla entegratör uygulama kararını da uygulamalı ve her LLM sıkılaştırmasının zincirde zorlandığını iddia etmiyorum.", 45)
rows(s, ["LLM araç sırasını seçer; sayılar deterministik.", "sign_score argümansız; sayılar değiştirilemez.", "Karar birleştirme yalnızca daha muhafazakâr olabilir.", "Anthropic → Gemini → deterministik yedek."], y=1.95, step=.95, size=26)
text(s, .85, 6.1, 11.7, .65, "Sınır: uygulama karar etiketi imzada yok; kontrat sayıları denetler.", 20, AMBER)

s = slide("Canlı demo: üç sahne", "Şimdi aynı ZBCN-USDT tahtasında önce bin USDT niyetini açıyorum, karar izini ve imzalı güvenli tutarı gösteriyorum; tahta uygunsa sonuç onay, ama tutar ve sonuç canlı veriyle değişebilir. İkinci sahnede on bin USDT güvenli tutarı aştığında ExceedsSafeSize cevabını gösterip agent'ın önerdiği parça sayısıyla kontratın hesabını karşılaştırıyorum; parça sayısını önceden sabitlemiyorum. Üçüncü sahne açıkça veri kesintisi simülasyonu: oracle imza üretmiyor, trader'ın kendi imzası BadSigner alıyor; ekrandaki ön izleme eth_call, alttaki explorer bağlantısı ise geçmiş gerçek işlemin kanıtı, ağ sorunu olursa deterministik yedeğe veya videoya geçiyorum.", 90)
rows(s, ["1.000 USDT: tahta uygunsa ONAY", "10.000 USDT: ExceedsSafeSize, N parçaya böl", "Veri kesintisi SİMÜLASYONU: imza yok, BadSigner"], y=2.0, step=1.08, size=27)
text(s, .85, 5.5, 11.6, .9, "Parça sayısı canlıdır. Agent ile kontratın hesabı birebir aynı.", 25, CYAN)
text(s, .85, 6.45, 11.6, .35, "Varsayılan: eth_call ön izlemesi. Geçmiş gerçek tx kanıtları README'de.", 16, MUTED)

s = slide("Kötü senaryoda ne oluyor?", "Organizatörün sorusunu doğrudan cevaplayayım: veri bozulunca imza yok, yetkisiz imza BadSigner alıyor ve tüketilmiş onay tekrar kullanılınca AlreadyUsed devreye giriyor. Oracle anahtarı çalınırsa owner pause ve setOracle ile müdahale ediyor; yanlış alarm için zincirde parametrik eşik ve nominal Bonferroni düzeltmesi var, ancak gerçek yanlış alarm oranını ölçtüğümü söylemiyorum. LLM'e sadece yapısal veri gidiyor ve sayılar deterministik kalıyor; tek oracle güveni sürüyor, önceden verilmiş imzalar geçerlilik penceresinde kullanılabilir ve acil çıkış yolu yalnızca kavram, bu yüzden çoklu oracle ile eşik imza sonraki adım.", 50)
table = s.shapes.add_table(6, 2, Inches(.8), Inches(1.9), Inches(11.8), Inches(4.55)).table
table.columns[0].width = Inches(4.0)
table.columns[1].width = Inches(7.8)
data = [("Kötü senaryo", "Mevcut karşılık"), ("Oracle anahtarı çalınır", "pause + setOracle"), ("LLM yanlış yorumlar", "Yapısal veri + deterministik sayılar"), ("Yanlış alarm", "Parametrik eşik + Bonferroni"), ("Piyasa verisi kesilir", "İmza yok; yetkisiz imza BadSigner"), ("Onay tekrar kullanılır", "AlreadyUsed; gerçek tx [BEKLİYOR]")]
for ri, pair in enumerate(data):
    for ci, val in enumerate(pair):
        cell = table.cell(ri, ci)
        cell.fill.solid()
        cell.fill.fore_color.rgb = RGBColor.from_string(PANEL if ri else "25483F")
        cell.margin_left = Inches(.18)
        cell.margin_right = Inches(.12)
        cell.margin_top = Inches(.12)
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        cell.text = val
        for p in cell.text_frame.paragraphs:
            for r in p.runs:
                r.font.name = FONT
                r.font.size = Pt(22)
                r.font.bold = ri == 0
                r.font.color.rgb = RGBColor.from_string(FG)
text(s, .85, 6.55, 11.6, .3, "Acil çıkış / reduce-only bypass: yalnızca kavram.", 16, MUTED)

s = slide("Ölçülen kanıt, açık sınırlar", "Zincirde IntentApproved, ExceedsSafeSize ve BadSigner gerçek işlem kayıtlarıyla gösterildi; AlreadyUsed ve StaleScore için elimizde şu anda yalnızca eth_call var, gerçek işlem hash'leri bekliyor. Kayıtlardaki zincir onayı yaklaşık iki saniye, LLM maliyeti koşu başına yaklaşık binde bir dolar ve bunlar örnek koşuların sonuçları; bu oturumda seksen iki Python testi geçti, on dört Solidity testi ise STATUS kaydından geliyor. Yirmi paritelik epizodik hafıza var ama tek oracle ve testnet sınırları sürüyor; ayrıca simülasyonun bir kez istemeden işlem gönderdiğini saklamıyorum, dry_run kilidi ve sekiz güvenlik testiyle bu yol kapatıldı.", 40)
rows(s, ["Gerçek tx: IntentApproved, ExceedsSafeSize, BadSigner", "Yaklaşık 2 sn zincir onayı; yaklaşık $0,001 / LLM koşusu", "Python 82/82 bu oturum; Solidity 14/14 STATUS kaydı", "20 parite epizodik hafıza; kayıt aralığı 60 sn"], y=1.9, step=.95, size=25)
text(s, .85, 5.85, 11.6, .7, "AlreadyUsed / StaleScore: eth_call; gerçek tx [BEKLİYOR].", 21, AMBER)
text(s, .85, 6.5, 11.6, .35, "Sınır: tek oracle, testnet, varsayılan ağırlıklar; dolum hızı ölçülmüyor.", 16, MUTED)

s = slide("Agent'lar için icra kontrolü servisi", "İlk müşteri ATK ile agent geliştiren ekipler ve bireysel kullanıcılar; önerilen model temel kontrolü ücretsiz tutup gerçek zamanlı API erişimini ücretlendirmek, ama ücret ödeme isteği ve gelir henüz doğrulanmadı. Sonraki adım çoklu oracle ve eşik imza, EIP-712 ile daha okunur imzalama, Almgren–Chriss icra planı, ardından OKX.ai listeleme ve çağrı başına ödeme; bunlar bugün kodlanmış özellikler değil, mainnet veya Avalanche L1 geçişi de bu aşamaların sonrasında değerlendirilecek. Bugün gösterebildiğim değer, güncel ATK tahtasından çıkan sayısal sınırın Fuji üzerinde onay veya redde dönüşmesi; repo ve kontrat açık, her emirden önce aynı soruyu soruyoruz: bu tahta bu emri kaldırır mı?​", 30)
rows(s, ["Müşteri: ATK agent geliştiricileri ve bireyler", "Model: temel ücretsiz, gerçek zamanlı/API ücretli", "Kodlanmadı: çoklu oracle, EIP-712, icra planı", "Kodlanmadı: OKX.ai, HTTP 402, mainnet / L1"], y=1.85, step=.82, size=25)
text(s, .85, 5.42, 11.65, .5, GITHUB, 25, CYAN, link=GITHUB)
text(s, .85, 6.04, 11.65, .65, "Fuji kontratı\n" + CONTRACT, 20, MUTED,
     link="https://explorer-test.avax.network/c-chain/address/" + CONTRACT)

# Konuşma uzunluğuna göre prova payı; sahne 6 canlı tıklama/bekleme içerir.
for record, seconds in zip(records, [35, 40, 40, 40, 40, 90, 45, 40, 50]):
    record["target_seconds"] = seconds

out = ROOT / "Arf.pptx"
prs.save(out)
(ROOT / "speaker_notes.md").write_text(
    "# Arf konuşmacı notları\n\nHedef toplam: 420 saniye (7 dakika), canlı demo dahil. Gerçek süre prova ile doğrulanacak.\n\n" +
    "\n\n".join(f"## {r['slide']}. {r['title']} — {r['target_seconds']} sn\n\n{r['notes']}" for r in records) + "\n",
    encoding="utf-8")

# Dosyayı tekrar açarak başlık ve notları doğrula.
check = Presentation(out)
assert len(check.slides) == 9
assert abs(check.slide_width / check.slide_height - 16 / 9) < .001
for i, (s, expected) in enumerate(zip(check.slides, records), 1):
    titles = [sh.text for sh in s.shapes if sh.has_text_frame]
    assert expected["title"] in titles
    notes = s.notes_slide.notes_text_frame.text
    assert notes == expected["notes"]
    print(f"{i}. {expected['title']} | not: {len(notes)} karakter, {len(notes.split())} kelime")
    for sh in s.shapes:
        assert sh.left >= 0 and sh.top >= 0
        assert sh.left + sh.width <= check.slide_width + 100
        assert sh.top + sh.height <= check.slide_height + 100
summary = {"slides": len(check.slides), "aspect": "16:9", "notes_words": sum(r["note_words"] for r in records),
           "target_seconds_including_demo": sum(r["target_seconds"] for r in records), "slides_detail": records}
(ROOT / "validation.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Üretildi: {out}; toplam {summary['notes_words']} not kelimesi, hedef {summary['target_seconds_including_demo']} sn")
