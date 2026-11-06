"""Kararın tamamını hafifçe tarayıp sınırlı sayıda özgün pasaj seçer.

Sözcüksel sıra bir hukuki doğrulama sağlamaz. Sıfır eşleşmeli bölümler de
kapsama kotasından seçilebilir; çıktı yalnız orijinal karakter dilimleridir.
"""
import math
import re
from collections import Counter


SIZE = 680
STRIDE = 500
# Yalnız açık bölüm başlıkları. Başlık aidiyet/çoğunluk etiketi sayılmaz.
_SECTION = re.compile(r"(?im)^\s*(?:KARŞI\s*OY|KARŞIOY|GEREKÇE|SONUÇ(?:\s+VE\s+İSTEM)?|HÜKÜM)\s*[:\-]?\s*$")
_ASCII = str.maketrans("çğıöşüâîû", "cgiosuaiu")
# Sınırsız "ev..." ön eki evet/evren/evrak gibi sözcükleri de eşleştirir.
_HOME_WORDS = frozenset("""
ev eve evi evde evden evin evini evine evinde evinden evinin
evler evlere evleri evlerde evlerden evlerin evlerini evlerine evlerinde evlerinden evlerinin
evim evime evimi evimde evimden evimin evimiz evimize evimizi evimizde evimizden evimizin
eviniz evinize evinizi evinizde evinizden evinizin
""".split())


def _terms(text, expand=False):
    words = re.findall(r"[^\W\d_]{2,}", text.lower().replace("i\u0307", "i").translate(_ASCII))
    if not expand:
        return words
    result = []
    for word in words:
        if word in _HOME_WORDS or re.fullmatch(r"(?:konut|mesken|ikametgah|ikamet|hane)\w*", word):
            word = "konut"
        elif re.fullmatch(r"ara(?:ma|n|t)\w*", word):
            word = "arama"
        elif word.startswith(("olgu", "emare", "belirti")):
            word = "olgu"
        elif word.startswith(("ihbar", "istihbar", "duyum")):
            word = "ihbar"
        elif word.startswith(("soyut", "subjektif", "kisisel")):
            word = "soyut"
        elif word.startswith("suphe"):
            word = "suphe"
        result.append(word)
    return result


def bm25_scores(question, texts, expand=False):
    """Aynı havuz için BM25. expand yalnız açık sözlük eşdeğerlerini kullanır."""
    query = set(_terms(question, expand))
    if not texts or not query:
        return [0.0] * len(texts)
    lengths, counts = [], []
    frequencies = Counter()
    for text in texts:
        words = _terms(text, expand)
        relevant = Counter(word for word in words if word in query)
        counts.append(relevant)
        lengths.append(len(words))
        frequencies.update(relevant.keys())
    average = sum(lengths) / len(lengths) or 1.0
    idf = {word: math.log(1 + (len(texts) - count + 0.5) / (count + 0.5))
           for word, count in frequencies.items()}
    return [sum(idf[word] * count * 2.2 / (count + 1.2 * (0.25 + 0.75 * length / average))
                for word, count in count_map.items())
            for count_map, length in zip(counts, lengths)]


def _windows(text):
    """Örtüşen pencereler tüm metni kaplar; açık bölüm sınırında kesilir."""
    boundaries = [0] + [match.start() for match in _SECTION.finditer(text) if match.start() > 0] + [len(text)]
    windows = []
    for begin, end in zip(boundaries, boundaries[1:]):
        start = begin
        while start < end:
            stop = min(start + SIZE, end)
            # Kelimeyi bölmeyi sınırlandır; metni değiştirmeden yalnız uçları kaydır.
            if start > begin and not text[start - 1].isspace() and not text[start].isspace():
                space = re.search(r"\s", text[start:min(start + 50, stop)])
                if space:
                    start += space.end()
            if stop < end and not text[stop - 1].isspace() and not text[stop].isspace():
                cut = max(text.rfind(" ", max(start, stop-50), stop), text.rfind("\n", max(start, stop-50), stop))
                if cut > start:
                    stop = cut
            if text[start:stop].strip():
                windows.append((start, stop))
            if stop == end:
                break
            start += STRIDE
    return windows


def select_passages(text, question, limit=20):
    """Tüm pencereleri sözcüksel tarar; yaklaşık %60 ilgi, %40 konum kapsaması seçer.

    En fazla 36 pasaj ve her pasaj en fazla 680 karakterdir. Başlangıç/bitiş
    konumları alınan kaynak metne aittir. Başlık veya metin içi görüşün sahibi
    sınıflandırılmaz. Uzun kararlar için bu sonuç tam bir semantik tarama değildir.
    """
    if not 1 <= limit <= 36:
        raise ValueError("Pasaj sınırı 1–36 olmalı.")
    windows = _windows(text)
    if len(windows) <= limit:
        return [(start, text[start:end]) for start, end in windows]
    excerpts = [text[start:end] for start, end in windows]
    scores = bm25_scores(question, excerpts, expand=True)
    order = sorted(range(len(windows)), key=lambda i: (-scores[i], windows[i][0]))
    chosen = []
    lexical_budget = max(1, (limit * 3) // 5)
    for i in order:
        if scores[i] <= 0 or len(chosen) >= lexical_budget:
            break
        start, end = windows[i]
        if all(max(0, min(end, windows[j][1]) - max(start, windows[j][0]))
               < 0.65 * min(end - start, windows[j][1] - windows[j][0]) for j in chosen):
            chosen.append(i)
    # Kalan kota metnin her konumuna açık kalır; sözcük eşleşmesi zorunlu değildir.
    available = set(range(len(windows))) - set(chosen)
    while available and len(chosen) < limit:
        if not chosen:
            index = min(available, key=lambda i: windows[i][0])
        else:
            index = max(available, key=lambda i: (min(abs(windows[i][0] - windows[j][0]) for j in chosen), -i))
        chosen.append(index)
        available.remove(index)
    return [(windows[i][0], excerpts[i]) for i in sorted(chosen)]
