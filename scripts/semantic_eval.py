"""Bağımsız Türkçe pasaj sıralama deneyi. Bütün kayıtlar kurmacadır.

Künyeler, yayımlanmış içtihat veya hukukî tavsiye değildir. Sorular, hedefler,
kabul eşikleri ve karşıt örnekler model çalıştırılmadan önce belirlendi.
Her soru aynı aday havuzunu kullanır. Sıralayıcı soruyu ve yalnız pasajları görür.
"""
import hashlib
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

# Komut proje kökünden: python scripts/semantic_eval.py
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from semantik import similarities


PASSAGES = {
    "ihbar_yetersiz": "Bir kimsenin isimsiz telefonla uyuşturucu sattığının bildirilmesi üzerine evine girilmiştir. Bu haber başka hiçbir veriyle desteklenmemiştir. Konuta girilmesine izin veren değerlendirme bu nedenle isabetli bulunmamıştır.",
    "ihbar_destekli": "İsimsiz telefon üzerine ekip adreste gözlem yapmış ve paket teslimini görüntülemiştir. Bildirim somut gözlemlerle desteklendiğinden konuta girilmesini gerektiren nedenlerin bulunduğu kabul edilmiştir.",
    "ozgurluk": "Kişinin cezaevinde tutulmasına devam eden kararlar incelenmiştir. Merci her defasında aynı matbu ibareleri tekrarlamış, sanığın şahsi durumunu veya daha hafif bir tedbirin neden yetmeyeceğini açıklamamıştır.",
    "iletisim": "Abonenin görüşmelerinin dinlenmesine izin verilirken neden başka yolla bilgi edinilemediği gösterilmemiştir. Karardaki matbu ibareler bu eksikliği gidermemektedir.",
    "beyan": "Müdafi hazır olmadan karakolda alınan anlatım, duruşmada hâkim huzurunda açıkça benimsenmiştir. Heyet bu teyidin önceki beyanın değerlendirilmesine etkisini tartışmıştır.",
    "tanik": "Suçlamanın başlıca dayanağı bir kişinin yazılı anlatımıdır. Savunmaya bu kişiye soru yöneltme ve güvenilirliğini sınama imkânı hiçbir aşamada tanınmamıştır.",
    "telefon": "Ölen kişiyle son konuşmanın sanığın hattından yapılması dışında failliğe işaret eden bir veri bulunmamaktadır. Hat aboneliği tek başına o görüşmeyi kimin yaptığını ortaya koymamaktadır.",
    "dijital": "Ele geçirilen diskin ilk kopyasıyla incelemeye sunulan kopyanın özet değerleri birbirini tutmamaktadır. Aradaki teslimlerde cihazın kimin elinde kaldığı da kayda geçirilmemiştir.",
    "teshis": "Mağdura karakolda yalnızca sanığın fotoğrafının gösterildiği anlaşılmıştır. Benzer kişilerin arasından seçim yapma fırsatı verilmediği için işlemin yönlendirici etkisi tartışılmıştır.",
    "konusmama": "Heyet, sanığın sorulara yanıt vermekten kaçınmasını onun aleyhine bir belirti olarak kullanmıştır. Bu davranışın suçlamayı destekleyen olgulardan sayılamayacağı değerlendirilmiştir.",
    "malvarligi": "Soruşturma boyunca hesabın kullanıma kapalı tutulması nedeniyle kişinin geçimini nasıl sürdüreceği ve işlemin süresi birlikte değerlendirilmemiştir. Malvarlığı üzerindeki tedbirin ağırlığı tartışılmıştır.",
    "karsi_oy": "Karşıoy yazısında üye, yalnızca parmak izine dayanılmasını yetersiz bulmuş ve çoğunluğun vardığı sonuca katılmadığını belirtmiştir.",
    "cogunluk": "Heyet çoğunluğu parmak izinin olayın diğer delilleriyle örtüştüğünü ve mahkûmiyete yeterli olduğunu belirtmiştir.",
    "kayit": "Mahkeme, savunma tanığının ses kaydı ile zabıt arasında farklılık bulunduğu iddiası üzerine kaydın aslının getirtilmesine karar vermiştir.",
}

# Hedefler ve eşikler, scores veya modelden alınan bir etiket kullanılarak üretilmez.
QUERIES = [
    ("Q01", "karşıt", "Doğrulanmamış tek bir ihbarla ev aramasını haklı bulmayan pasajı getir.", "ihbar_yetersiz"),
    ("Q02", "karşıt", "Habercinin sözüne ek olarak kolluğun kendi tespitine dayanarak aramayı yerinde gören pasaj hangisi?", "ihbar_destekli"),
    ("Q03", "tedbir", "Tutukluluğu uzatırken şüpheliye özgü gerekçe sunulmamasını eleştiren metin hangisi?", "ozgurluk"),
    ("Q04", "tedbir", "Telefon takibinde son çare koşulunun neden gerçekleştiğini açıklama sorununu bul.", "iletisim"),
    ("Q05", "yeniden ifade", "Poliste avukatsız verilen ifadenin yargıç önünde tekrarlanmasını konu alan bölüm hangisi?", "beyan"),
    ("Q06", "yeniden ifade", "Sanığın kendisini suçlayan şahsı sorgulama olanağından yoksun kalmasına ilişkin örneği bul.", "tanik"),
    ("Q07", "yeniden ifade", "Arayan numaranın kime ait olduğundan failin kimliğine doğrudan geçilemeyeceğine ilişkin bölüm hangisi?", "telefon"),
    ("Q08", "yeniden ifade", "Sayısal delilin sonradan değiştirilip değiştirilmediği denetlenemiyorsa hangi pasaj ilgilidir?", "dijital"),
    ("Q09", "yeniden ifade", "Görgü sahibine tek bir yüz sunmanın hatalı kişi belirlemeye yol açması nerede tartışılıyor?", "teshis"),
    ("Q10", "yeniden ifade", "Susma hakkının kullanılmasından suçluluk çıkarımı yapılmasını eleştiren pasajı bul.", "konusmama"),
    ("Q11", "tedbir", "Banka parasına uzun süre el konmasının ölçülülüğünü inceleyen bölüm hangisi?", "malvarligi"),
    ("Q12", "aidiyet", "İz bulgusunun yeterli olmadığı görüşünü karşıoy sahibinin dile getirdiği pasaj hangisi?", "karsi_oy"),
]

# Sabit, hedef sırasından bağımsız aday dizilimi. Eşit skorlarda iki yöntem de aynı sırayı kullanır.
IDS = sorted(PASSAGES, key=lambda key: hashlib.sha256(key.encode()).digest())
TEXTS = [PASSAGES[key] for key in IDS]


def words(text):
    return re.findall(r"[^\W\d_]+", text.lower().replace("i\u0307", "i"))


def lexical(question, texts):
    """BM25 kelime taban çizgisi (k1=1.2, b=0.75); çekim eki normalizasyonu uygulanmaz."""
    docs = [Counter(words(t)) for t in texts]
    average = sum(sum(doc.values()) for doc in docs) / len(docs)
    scores = [0.0] * len(docs)
    for term in set(words(question)):
        frequency = sum(term in doc for doc in docs)
        idf = math.log1p((len(docs) - frequency + 0.5) / (frequency + 0.5))
        for i, doc in enumerate(docs):
            norm = 1.2 * (0.25 + 0.75 * sum(doc.values()) / average)
            scores[i] += idf * 2.2 * doc[term] / (doc[term] + norm)
    return scores


def rank(scores, gold):
    if len(scores) != len(IDS) or not all(math.isfinite(float(score)) for score in scores):
        raise ValueError("Her aday için sonlu bir skor gerekir.")
    ranking = sorted(range(len(scores)), key=lambda i: -scores[i])
    return ranking.index(IDS.index(gold)) + 1


def metrics(ranks):
    return {
        "top1": sum(rank == 1 for rank in ranks),
        "top3": sum(rank <= 3 for rank in ranks),
        "mrr": round(sum(1 / rank for rank in ranks) / len(ranks), 4),
    }


def main():
    semantic_ranks, lexical_ranks = [], []
    for code, kind, query, target in QUERIES:
        sr = rank(similarities(query, TEXTS), target)
        lr = rank(lexical(query, TEXTS), target)
        semantic_ranks.append(sr)
        lexical_ranks.append(lr)
        print(f"{code} | {kind} | hedef={target} | semantik_sıra={sr} | BM25_sıra={lr}", flush=True)
    semantic, baseline = metrics(semantic_ranks), metrics(lexical_ranks)
    print(json.dumps({"soru": len(QUERIES), "aday": len(IDS), "sentetik": True,
                      "semantik": semantic, "BM25": baseline}, ensure_ascii=False))
    # Ölçüm tanı amaçlıdır; küçük sentetik örnek gerçek karar başarısını kanıtlamaz.
    if (semantic["top1"] < 8 or semantic["top3"] < 10 or semantic["mrr"] < 0.75
            or semantic["mrr"] < baseline["mrr"]):
        sys.exit("Pilot kabul eşiği karşılanmadı.")


if __name__ == "__main__":
    main()
