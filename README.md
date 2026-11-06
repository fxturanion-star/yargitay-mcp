# Yargıtay Karar Arama — MCP Sunucusu

Yargıtay kararları Adalet Bakanlığının Bedesten indeksinden aranır. Arama, toplu araştırma, bağlantı testi ve tam metin çağrıları bu kaynağı kullanır. Tarih + daire ile kelimesiz sorgu desteklenir. Eski sayısal kaynak kimliklerini yeniden arayın; yeni kimlikler `bedesten:` ile başlar. Numara aralığı yerine kesin esas/karar numarası kullanılabilir.

## Ek kaynaklar

- `resmi_gazete_fihrist(tarih)` normal sayılar için önce LEXPERA günlük listesini kullanır. Listenin tarihi uyuşmazsa hata verir. Eski tarihleri resmî arşivde aramak için `ikincil_kaynak=false` verin. Mükerrer sayılar resmî arşivden alınır. `resmi_gazete_belgesi` fihristin döndürdüğü kaynaktan belgeyi okur.
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

“En güncel üç CGK kararı” için `yargitay_karar_ara(daire="Ceza Genel Kurulu", en_yeni=true, sayfa_boyutu=3)` kullanılır. Araç Bedesten'in karar tarihi sıralamasını ister ve son satırdan daha yeni günlerdeki kayıtları bağımsız bir tarih sorgusuyla karşılaştırır. Eşit tarihte birden çok karar olabilir. Sıralama indekste yayımlanmış kayıtlara ilişkindir. `emsal_dogrula` çıktısında `kunye_durumu`, belge kimliği ve karar başlığının resmî arama kaydıyla karşılaştırılmasının sonucudur. Önbellek boşken araç karar başlığındaki daire ve K. numarasıyla arama yapar.

Bedesten arama yanıtlarında kararın tarihi bulunur. İndekse eklenme zamanı doğrulanamadığı için “en son eklenen” sırası üretilmez. Emsal aracı, tekil bir alıntının önceki ve sonraki metnini gösterir. Aynı ifade birden çok yerde geçtiğinde eşleşme sayısını verir; belirli bir pasajı veya konuşanı seçmez.

Canlı denetimler üç bağımsız iş olarak çalışır: `core` (19 araç ve dört farklı kararın künyesi), `resmi` (yalnız resmî RG fihristi ve belgesi), `lexpera` (yalnız LEXPERA fihristi ve belgesi). Elle çalıştırmak için örneğin `python test_live.py 2026-11-06 resmi` kullanın. Her iki RG kaynağında da başarı için aynı sayıdan bir belge metninin okunması gerekir.

### Resmî Gazete ve dağıtım tanısı

Resmî fihrist yanıtı eksikse veya 404/410 dönerse araç aynı günün resmî arşiv sayfasını dener. Bağlantı zaman aşımında aynı kaynağa art arda istek göndermez. Başarısız resmî entegrasyon işinin sonunda GitHub günlüğünde DNS, TCP, TLS ve ilk HTTP yanıt baytı süreleri ayrı gösterilir. Proxy kullanılan bir ortamda bu süreler istemcinin gördüğü bağlantıyı ölçer.

Yayımlanan kodu denetlemek için ChatGPT veya Claude'dan `yargitay_baglanti_testi(surum_kontrolu=true)` isteyin. Sunucu GitHub main üzerinde o an görünen commit'in ağaç kaydını alır, çalışan 12 dosyayı içerikleriyle karşılaştırır ve farkların adlarını bildirir. Commit kimliği çalıştırma ortamındaki Git checkout'undan veya Git arşivinin `release-revision` kaydından okunur. İkisi de yoksa dosya karşılaştırması yapılabilir, ancak kesin commit doğrulanamaz. Bu kontrol çalıştırma ortamının OAuth politikasını veya kurulu dolaylı paket sürümlerini kapsamaz.

Her main push'unda `FastMCP Cloud sürüm doğrulaması` işi dağıtımın yetişmesini bekler. İşin korumalı MCP adresini çağırabilmesi için GitHub Actions repository secret olarak `FASTMCP_VERIFY_TOKEN` tanımlayın (bu sunucuya araç çağrısı yapmaya yetkili bir Gateway bearer token). Token eksikse, çalıştırma commit'i bilinmiyorsa veya dosyalar farklıysa doğrulama işi başarısız kalır. Bu iş dağıtım sonrası denetimdir.

### Deneysel semantik içtihat araması

`semantik_ictihat_ara` mevcut kararlardan seçilen küçük bir aday kümesinde çalışır. Örneğin “Somut emare gösterilmeden kişinin konutunda arama yapılmasını hangi kararlar tartışıyor?” sorusunu verin. İstemci 1–3 alternatif Bedesten ifadesi (`arama_ifadeleri`), daire ve tarih aralığı gönderebilir. Varsayılan 3 ayrı karar incelenir. Konutta arama işaretleri bilgi amaçlıdır; belirli sözcüklerin yokluğu pasajı elemez. Aday kümesi üç sorgudan RRF ve sorgu çeşitliliğiyle birleştirilir. Sonuç boşsa aday kümesini veya arama ifadelerini değiştirin.

Araç çok dilli E5-small modelini CPU'da çalıştırır. İlk kullanımda sabitlenmiş ONNX modelini ve tokenizer'ı indirip dosya özetlerini doğrular; model verileri diskte yaklaşık 135 MB yer kaplar. Önbellek için `SEMANTIK_MODEL_CACHE` ayarlanabilir. Bedesten'e arama ifadeleri gönderilir; embedding hesabı için soru ve karar metinleri dışarıya gönderilmez. Varsayılan model bütçesi sorgu başına120 pasajdır; seçmeden önce metnin tüm örtüşen pencereleri hafif sözcüksel taramadan geçer. `benzerlik` bir kosinüs puanıdır. Künye doğrulanmazsa aday elenir. Dönen pasaj ve karakter konumları tam metne aittir. Mahkemenin benimsediği görüş ve hukuki uygunluk için çevre metni okuyun ve gerekirse `emsal_dogrula` kullanın.

Bağımsız kalite denetimi: `python scripts/semantic_eval.py`. Değerlendirme 12 sentetik soruyu aynı 14 pasajda BM25 ile karşılaştırır. GitHub'da kalite eşiği ve gerçek kaynak testi ayrı adımlarda gösterilir. Tüm Yargıtay kararlarını kapsayan bir vektör indeksi bu sürümün kapsamı dışındadır.

ChatGPT'nin içe aktardığı katalog yeni aracı göstermiyorsa aynı semantik işlev mevcut toplu araştırma aracından çağrılabilir: `yargitay_toplu_arastirma(aranan_kelime="hukuki soru", metin_bicimi="semantik", metin_sayisi=3, sonuc_sayisi=3)`. Bu yol `semantik_ictihat_ara` ile aynı uygulamaya gider. Sunucunun gerçek araç listesini `yargitay_baglanti_testi(arac_listesi=true)` ile kontrol edin. Bu uyumluluk yolu ChatGPT'nin sakladığı katalog kaydını güncellemez.


### Ölçülen semantik iyileştirme PR'ı

[Denetim raporu](docs/semantic-audit-2026-11-06.md) ölçümleri, ayrı veri kümelerini ve açık kabul kriterlerini içerir. Mevcut12 soruluk test ve eşikleri korunur. Modelin hukuki görüş yönünü veya pasaj aidiyetini bağımsız doğruladığı kabul edilmez.

İsteğe bağlı bütçeler: \`SEMANTIK_CANDIDATE_POOL\` varsayılan18 (en fazla60 tutulan künye), \`SEMANTIK_MAX_DOCUMENTS\` varsayılan6 (en fazla12, aday_sayisi üst sınırı), \`SEMANTIK_PASSAGES_PER_DOC\` varsayılan20 (en fazla36), \`SEMANTIK_MAX_PASSAGES\` varsayılan120 (en fazla240), \`SEMANTIK_MAX_TEXT_CHARS\` varsayılan500000 (en fazla2000000). İlk sonuçta3 karar ve kısa pasajlar önerilir. Toplam model kotası belge sayısına bölünür; künye havuzu büyüse de tam metin sayısı ve model kotası bağımsız sınırlıdır. Soru256 model token'ını aşarsa açık hata verilir. Kaynak veya metin sınırına takılan adaylar hata listesinde görünür.

\`python scripts/candidate_eval.py\` ağsız aday-senaryo testini; \`python scripts/quality_compare.py --stage all\` dondurulmuş geliştirme/holdout karşılaştırmasını çalıştırır. Gerçek karar deneyi için raporda verilen kaynakları ayrı edinip \`python scripts/real_passage_eval.py --source /path/source.json\` kullanın. Bu etiketler ajan destekli olup hukuk uzmanı incelemesinden geçmemiştir. GitHub kalite işi ile canlı kaynak işleri ayrı sonuçlar verir.

Docker için kesin sürüm damgası \`docker build --build-arg RELEASE_REVISION=$(git rev-parse HEAD) -t yargitay-mcp .\` ile verilir. Yönetilen Cloud imajında SHA damgası ve yetkili \`FASTMCP_VERIFY_TOKEN\` ayrı yapılandırılmalıdır. Bu PR canlı Cloud'a uygulanmış kabul edilmez.

PR3 için [üretim öncesi kontrol notu](docs/pr3-preflight-2026-11-06.md) gerçek Docker imaj testini, eski kabul başarısızlığından ayrı regresyon kontrolünü ve üç resmî kayıt üzerinde ağsız MCP/model denemesini açıklar. `python scripts/quality_regression.py` temel sürümle karşılaştırır; eski `scripts/semantic_eval.py` kabul testi ayrıca çalıştırılmalıdır.
