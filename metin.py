"""İsteğe bağlı sayfalama. Sınırlar kaynak metnin karakter konumlarıdır."""
from hashlib import sha256


def sayfali_belge(belge, baslangic, karakter_sayisi):
    if baslangic == 0 and karakter_sayisi is None:
        return belge
    boyut = 4000 if karakter_sayisi is None else karakter_sayisi
    if not 1 <= boyut <= 20000 or baslangic < 0:
        raise ValueError("Başlangıç negatif olamaz; karakter_sayisi 1–20000 olmalı.")
    metin = belge["metin"]
    if baslangic >= len(metin):
        raise ValueError("Başlangıç metnin sonuna ulaştı veya sonunu aştı.")
    son = min(baslangic + boyut, len(metin))
    return {**belge, "metin": metin[baslangic:son], "baslangic": baslangic,
            "toplam_karakter": len(metin), "metin_surumu": sha256(metin.encode("utf-8")).hexdigest()[:24],
            "sonraki_baslangic": son if son < len(metin) else None}
