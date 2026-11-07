"""İsteğe bağlı sayfalama. Sınırlar kaynak metnin karakter konumlarıdır."""
from hashlib import sha256


def sayfali_belge(belge, baslangic, karakter_sayisi):
    if baslangic == 0 and karakter_sayisi is None:
        return belge
    if baslangic < 0 or (karakter_sayisi is not None and not 1 <= karakter_sayisi <= 20000):
        raise ValueError("Başlangıç negatif olamaz; karakter_sayisi 1–20000 olmalı.")
    metin = belge["metin"]
    if baslangic >= len(metin):
        raise ValueError("Başlangıç metnin sonuna ulaştı veya sonunu aştı.")
    # Sınır verilmezse (null) belgenin başlangıçtan sonraki tamamı döner.
    son = len(metin) if karakter_sayisi is None else min(baslangic + karakter_sayisi, len(metin))
    return {**belge, "metin": metin[baslangic:son], "baslangic": baslangic,
            "toplam_karakter": len(metin), "metin_surumu": sha256(metin.encode("utf-8")).hexdigest()[:24],
            "sonraki_baslangic": son if son < len(metin) else None}
