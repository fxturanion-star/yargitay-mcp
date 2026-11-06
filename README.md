# Yargıtay Karar Arama — MCP Sunucusu

Yargıtay kararları Adalet Bakanlığının Bedesten indeksinden aranır. Arama, toplu araştırma, bağlantı testi ve tam metin çağrıları bu kaynağı kullanır. Tarih + daire ile kelimesiz sorgu desteklenir. Eski sayısal kaynak kimliklerini yeniden arayın; yeni kimlikler `bedesten:` ile başlar. Numara aralığı yerine kesin esas/karar numarası kullanılabilir.

## Ek kaynaklar

- `resmi_gazete_fihrist(tarih)` yayımları tarihli sayıdan getirir. Resmî erişim sağlanamazsa yalnızca tarihi eşleşen açık LEXPERA günlük listesi kullanılabilir. Varsayılan yalnızca resmî kaynaktır. LEXPERA için açıkça `ikincil_kaynak=true` verin. Mükerrer sayılar ayrı sorgulanır. `resmi_gazete_belgesi` fihristin verdiği belge koduyla metni getirir.
- `aihm_ara` HUDOC kararlarını koleksiyon, ülke, dil, başvuru no, ifade ve tarihle arar. `aihm_karar_getir` seçilen dil kaydının tam metnini sayfalayarak verir. İngilizce arama için ENG, Fransızca için FRE, kayıtlı Türkçe çeviriler için TUR.
- `yoktez_ara` YÖK kataloğunda tez adı, yazar, danışman, konu, anahtar kelime, özet veya tez numarasıyla arar. `yoktez_detay` açık özet, atıf ve varsa YÖK'ün sunduğu PDF bağlantısını verir.
## Kurulum — Seçenek A: FastMCP Cloud (önerilen, kişisel kullanımda ücretsiz)

1. github.com'da hesap açın (varsa geçin) ve bu klasörü **private repo** olarak
   yükleyin (tüm Python modüllerini ve requirements.txt dosyasını dahil edin).
2. https://fastmcp.cloud adresine GitHub ile giriş yapın.
3. "New Server" → repo'yu seçin → Entrypoint: `server.py:mcp` → Deploy.
4. ~1 dk içinde adres alırsınız: `https://<sunucu-adiniz>.fastmcp.app/mcp`

## Kurulum — Seçenek B: Kendi sunucunuz / Render / Railway (Docker)

```bash
docker build -t yargitay-mcp .
# Kendi kimlik sağlayıcınızın RS256 ayarları jwt.env içinde olmalı.
docker run --env-file jwt.env -e MCP_HOST=0.0.0.0 -p 127.0.0.1:8000:8000 yargitay-mcp
# MCP adresi: http://<host>:8000/mcp  (HTTPS için ters proxy gerekir)
```

Ortam değişkenleri: `PORT` (varsayılan 8000), `MCP_PATH` (varsayılan `/mcp`).

## claude.ai'ye bağlama (tüm cihazlarda çalışması için)

1. claude.ai → **Ayarlar → Bağlayıcılar (Connectors)** → **Özel bağlayıcı ekle**.
2. Ad: `Yargıtay Karar Arama`, URL: `https://<sunucu-adiniz>.fastmcp.app/mcp`.
3. Kaydedin; her sohbette bağlayıcıyı etkinleştirerek kullanın.

> Not: Kimlik doğrulaması olmayan bir bağlayıcıda URL'yi bilen herkes sunucuyu
> kullanabilir. Veriler kamuya açık olduğundan risk düşüktür; yine de URL'yi
> paylaşmayın. İsterseniz FastMCP Cloud üzerinde OAuth açılabilir.

## Yerel test

```bash
pip install -r requirements.txt
python test_mock.py        # ağsız MCP arama → metin testi
python -m unittest discover   # hata ve sınır durumları
python test_live.py YYYY-MM-DD  # erişilebilir bir RG tarihiyle 21 aracın canlı testi
MCP_TRANSPORT=stdio python server.py   # stdio modunda (tek makine) çalıştırma
```

## Hukuki not

Kararlar Yargıtay'ın kamuya açık platformundan alınır; kişisel veri içerebilen
karar metinlerinin işlenmesinde KVKK ve platformun kullanım koşullarına uyum
kullanıcının sorumluluğundadır.

Kanun araması, madde ve tam metin araçları mevzuat.gov.tr erişim hatasında Adalet Bakanlığının Bedesten kaynağını kullanır. Belge kimliği kanun türü, numarası ve tertibiyle eşleştirilir. İkincil arama yolunda başlık ve içerik birleştirildiğinde toplam kesin olarak hesaplanamıyorsa `toplam` boş döner.

## Karar ve mevzuat kaynakları

`mevzuat_genel_ara` Bakanlığın indeksindeki mevzuatı sayfalayarak arar. Türü boş bırakınca farklı mevzuat türleri birlikte aranır; mülga kayıtlar da çıkabilir. `mevzuat_belgesi_getir` sonuçtaki belge kimliğiyle metni ve resmî bağlantıyı getirir. Uzun belgelerde sonraki_baslangic değerini kullanın. Yürürlük durumunu ve değişiklik notlarını kaynak belge üzerinden doğrulayın.

## Ceza araştırması ve atıf doğrulama

- `aym_ara` Anayasa Mahkemesi bireysel başvurularını tarar. `aym_paragraf_getir` başvuru numarası veya arama kimliğiyle resmî metinde tekil olarak bulunan numaralı paragrafı verir. Belirsiz numara için kaynak sayfasına başvurun.
- `emsal_dogrula` iki aşamalıdır. Önce önermeyi ve kararı verip metni okuyun (uzun metinde sayfalayın). Ardından metinden alıntı, pasajın sahibi, gerekçe ve destek derecesini iletin. Sunucu boşlukları normalleştirerek alıntıyı kaynak metinle karşılaştırır. Önerme hakkında hukuki değerlendirme ve pasajın aidiyeti sohbet modeline aittir. Karşıoy ve alıntılanan başka karar, çoğunluk görüşüyle karıştırılmamalıdır.

### Uzun belgeleri ekonomik okuma

Tek madde için `mevzuat_madde_getir`, tek AYM paragrafı için `aym_paragraf_getir` kullanın. Yargıtay araştırmasında önce az sayıda künye isteyin. Kararı veya kanunu okumak için `yargitay_karar_metni` ve `mevzuat_kanun_metni_getir` araçlarına isteğe bağlı `karakter_sayisi` (1–20000) verilebilir. Örneğin ilk 4.000 karakter için `{"kanun":"CMK","karakter_sayisi":4000}` gönderin. Devamı gerektiğinde aynı parametrelerle yanıttaki `sonraki_baslangic` değerini `baslangic` olarak gönderin. Sayfaları birleştirirken her yanıtta aynı `metin_surumu` değerini arayın; değer değişirse metni baştan okuyun. Son sayfada `sonraki_baslangic` `null` olur. Yargıtay kararı varsayılan 4.000 karakterlik sayfa döndürür; bütün karar için `karakter_sayisi=null` gönderin. Kanun aracının tam metin varsayılanı korunur. Toplu aramada `pencere` yalnızca bir pasaj gösterir; kararın bütününe dayalı değerlendirme için tam metne başvurun.
