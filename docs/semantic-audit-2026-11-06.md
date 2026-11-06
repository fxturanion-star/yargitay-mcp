# Semantik arama ve yazılım denetimi, 6 Kasım 2026

## A. İncelenen sürüm ve başlangıç

Başlangıç main commit'i `1bc1dc95d19ea06818a1e96c2ee76f1015928bb8`, 22 MCP aracı. Kaynaklar, tüm Python modülleri, giriş noktaları, Docker ve iki workflow incelendi. Aynı yerel Python3.12.14 ortamında30 mevcut test geçti. Sabit12 soruluk değerlendirme tekrarlandı: E5 Top1=6/12, Top3=10/12, MRR=.6903; kabul betiği exit1. Baseline kodu ve test script'i değiştirilmeden karşılaştırıldı.

Başlangıç GitHub koşusu [42276912924](https://github.com/fxturanion-star/yargitay-mcp/actions/runs/42276912924): çevrimdışı ve çekirdek başarılı. Semantik kaynak/pasaj testi başarılı, aynı işteki kalite eşiği başarısız. Resmî RG ReadTimeout, LEXPERA ConnectTimeout. Bulut doğrulama [42276913073](https://github.com/fxturanion-star/yargitay-mcp/actions/runs/42276913073) FASTMCP_VERIFY_TOKEN eksikliğiyle başarısız.

## B. Sorunlar

| Önem | Konum | Neden ve etki |
|---|---|---|
| Yüksek | semantik._passages | Uzun metindeki20 eşit aralıklı pencere gerekçeleri kaçırabiliyor. |
| Yüksek | semantik kayıt fonksiyonu | Kaynak istekleri model kapasite kabulünden önce yapılıyor. Eşzamanlı sorgular gereksiz ağ/bellek tüketiyor. |
| Yüksek | _home_search katı elemesi | Aynı konuyu farklı sözcüklerle anlatan pasaj kaybolabiliyor. |
| Orta | Aday birleştirme | İlk sıraları dönüşümlü alıp kesmek, farklı sorgularda tekrar bulunan güçlü adayları kaybedebiliyor. |
| Orta | Soru tokenizasyonu |1200 karakterlik soru256 token'ı aşınca sonundaki sınırlama/olumsuzluk sessizce kırpılabiliyor. |
| Orta | Model/kaynak hataları | Ham istisna URL'si geçici imzalı model URL'sini açığa çıkarabilir; indirmede yalnız hareketsizlik süresi var. |
| Yapılandırma | verify_cloud | Doğrulama token'ı yok; yönetilen dağıtım commit kimliği bildirmiyor. Kod dosyası eşleşmesi tek başına kesin build kimliği değildir. |
| Dış kaynak | RG / LEXPERA | İstek okumada ve bağlantı kurmada farklı zaman aşımları. Kaynak sağlayıcı/ağ yönlendirmesi ayrımı bu kanıtla kesinleşmez. |

## C. Dar değişiklikler

E5 modeli, sabit revizyon, dosya hash'leri, vektör hesabı, bütün22 araç, mevcut imzalar ve eski pencere/tam yolları korunur. Named semantik araç ve uyumluluk çağrısı aynı fonksiyona gider.

- Pasaj seçimi tüm metni680 karakterlik örtüşen pencerelerle tarar. Yaklaşık%60 BM25 ve açık sözcük eşdeğerleri, %40 metin boyunca kapsama kotası kullanır. Kaynak karakter konumları korunur. Açık satır başlıkları varsa pencereler bölüm sınırında kesilir; düzleştirilmiş HTML'de tüm bölüm sınırlarının çıkarıldığı iddia edilmez.
- Üç sorgu, ayrı künye havuzu ve tam metin bütçesiyle birleştirilir. RRF ve sorgu kapsaması kullanılır. Başlık/snippet bulunmayan künye alanlarından sahte sözcüksel anlam puanı üretilmez. Aynı belge id'si tekilleşir.
- Sözcük yokluğu eleme nedeni olmaktan çıkarıldı. Bilgi amaçlı odak alanı korunur. Son sıralama E5 kosinüsüdür.
- Kaynak sorgusundan önce en fazla iki semantik istek kabul edilir. Ayrı model işçisi/kuyruk sınırı korunur. İstemci iptalinde çalışan model işi bitene kadar slot tutulur. İstemci ayrıldıktan sonra kalan işin istisnası tüketilir.
- Model indirmesinde180s toplam kontrol ve30s I/O sınırı,128MiB sınır, atomik kurulum ve SHA256 kontrolü vardır. Bozuk dosyada başka modele geçilmez. Soru256 token'ı aşarsa hata verilir. Kaynak hataları sınıf/HTTP koduyla sadeleştirilir.
- Bütçeler bağımsız env ayarlarıyla sınırlıdır. Varsayılan metin başına500000 karakter aşılırsa adayın metni kırpılarak kaynak gibi sunulmaz; açık hata verilir.
- Sürüm tanısı dosyalar, build SHA ve MCP katalog/şema fingerprint'lerini ayrı gösterir. Docker build arg'ı git metadata'sı olmayan imaja commit damgası verir.

## D. Aynı koşullarda ölçümler

### Sabit12 soruluk sıralama

| Metrik | Önce | Sonra | Fark |
|---|---:|---:|---:|
| Recall@3 / Top3 |10/12|10/12|0|
| Precision@3 |.2778|.2778|0|
| Top1 |6/12|6/12|0|
| MRR |.6903|.6903|0|

Model sıralayıcısı değiştirilmedi, sabit adaylarda yeni bir anlam doğruluğu kazancı saptanmadı. Eski kabul eşikleri düşürülmedi; betik başarısız kalır.

### Ayrı geliştirme ve holdout

20 geliştirme sorusu ve ayrı20 holdout sorusu, her birinde20 sentetik aday. Sorular karşıt yön, farklı tedbir ve pasaj sahibi çiftleri içerir. Her yönteme aynı havuz verildi. Test metni/etiketleri modeller çalıştırılmadan önce hash'le sabitlendi. Geliştirmede seçilen karakter4 TF-IDF, holdout görülmeden kilitlendi. E5 kaynağı eşzamanlı dosya değişikliğinden etkilenmesin diye baseline kaynağına sabitlendi; değişiklik holdout açılmadan belgelenmiştir. Protokol, ilk ve son manifestler evaluation altında bulunur.

| Holdout | E5 | BM25 | Geliştirmede seçilen karakter4 |
|---|---:|---:|---:|
| Top1 |16/20|14/20|15/20|
| Recall@3 / Top3 |18/20|18/20|20/20|
| Precision@3 |.3000|.3000|.3333|
| MRR |.864167|.807179|.875000|
| NDCG@3 |.856546|.826186|.907732|

Karakter yöntemi MRR'ı az artırırken Top1'i düşürdü; orijinal12 soruda ağır geriledi. Çift gruplarıyla bootstrap MRR farkı95% aralığı [-.083333,.1125]. Üretim sıralayıcısı yapılmadı. BM25+E5, RRF, normalize füzyon ve ucuz ilk5 sözcüksel yeniden sıralama yöntemlerinin geliştirme sonuçları `comparison_report.json` içinde. Başka bir neural modelin dosya/bellek maliyeti eklenmedi; böyle bir modelin daha iyi olduğuna dair bu çalışmada kanıt yok.

### Aday toplama ve uzun metin

| Ölçüm | Önce | Sonra | Sınır |
|---|---:|---:|---|
| Aday hedefinin ilk3'e girmesi |4/8|6/8|Kurmaca sorgu grupları; aynı3 sorgu/3 tam metin bütçesi, metadata satırı3→6/sorgu. Canlı hukuk erişim başarısı değildir. |
|160k karakterli10 kurmaca metinde hedef pasajı tam kapsama |1/10|10/10|Aynı20 embedding pasajı; kaynak dışı istek yok. |
| Bu10 metinde seçilen model pasajı |200|200|Hafif taranan pencere200→3170. |
| Hafif seçim CPU duvar süresi |~.002s|~.596s|Toplam10 metin, yaklaşık+59ms/metin; donanıma ve yüke bağlı. |
|3 gerçek CGK metninde belirlenmiş delil aralığının kapsanması |0/3|3/3|Altı etiketli tam karakter aralığı0/6→6/6. |
| Kendi belgesinde E5 ilk pasajının etiketli aralığı kapsaması |0/3|2/3|Belge seçim başarısı veya hukuki uygunluk metriği değildir. |
|3 belgede tek geçiş, ilk model yüklemesi dâhil |3.139s|3.038s|Ayrı temiz süreçler; tek ölçüm, güven aralığı yok. |
| Bu süreçlerde peak RSS |560.598MiB|560.652MiB|Konteyner toplamı değildir, pratik bellek artışı kanıtlanmadı. |
| Ağsız gerçek belge deneyi kaynak isteği |0|0|Önceden aynı resmî metinler kullanıldı; canlı ağ gecikmesi ölçülmedi. |

Gerçek metinler: CGK2019/18,2019/536,2025/151. Kimlik, hash ve altı etiketin kaynak konumu `real_passage_gold.json` içinde; tam metinler yeniden dağıtılmıyor. Etiketler ajan destekli; hukuk uzmanı onayı yoktur. Eski ilk pasajların üçü de hukuken ilişkili metindir;0/3 sayısı yalnız önceden belirtilen aralıkların TAM kapsanmasına ilişkindir. Yeni2019/536 ilk pasajı alıntılanan daire görüşünü seçebiliyor; aidiyet sorunu sürüyor. Bu ölçüm uzman değerlendirmesine dayalı bir başarı oranı olarak sunulamaz.

## E. Testler ve CI

Yerel44 test, compileall, mevcut MCP arama→metin testi ve bağımlılık tutarlılığı kontrolü geçti. Kapasite, iptal, bozuk model, sahte başlık, geçerli kaynak konumları, katı sözcük elemesinin kaldırılması, kaynak kotası, katalog ve imza test edildi. Docker CLI yok; tam imaj derlemesi bu ortamda çalıştırılmadı.

Canlı kaynak testleri, sabit model kalite kabul işi ve yeni karşılaştırma işi ayrı raporlanır. PR koşusu linki PR'ın Checks alanında bulunur. Mevcut main'in canlı başarıları değişen PR kodunun canlı başarısı olarak kabul edilmez.

## F. Dağıtım

Bu çalışma geliştirme dalı ve PR olarak sunulur; Cloud'a uygulanmış sayılmaz. Başlangıç sürümünde çalışan13 dosya main ile eşleşiyordu, fakat çalışan commit SHA'sı null idi. Token ve build damgası operator tarafından yapılandırılmadan tam otomatik Cloud eşleşmesi doğrulanamaz. Token veya yönetilen ortam ayarı oluşturulmadı. Sürüm kontrolü başarılı dosya eşleşmesi, kesin commit, katalog ve kritik şemaları ayrı değerlendirir.

## G. Kalan riskler ve kabul kriterleri

| Kriter | Durum |
|---|---|
|22 araç, eski modlar, tek semantik uygulama |Yerel regresyon testleriyle doğrulandı. |
|Aday havuzu erişim artışı |Kurmaca senaryoda ölçüldü; canlı genel recall ölçülmedi. |
|Doğru pasajı bulma |Belirlenmiş kaynak aralıkları ve yapısal uzun metinde iyileşti; uzman doğruluğu ölçülmedi. |
|Karşıt görüş/tedbir/aidiyet ayrımı |Yeterli değil; koruyucu false alanları sürer. |
|Resmî kaynak bütünlüğü |Mevcut mekanizma ve yeni tam kaynak konumu testleri korunur. |
|Gerçek bağımsız uzman değerlendirmesi |Ajan destekli3 metin var; hukuk uzmanı incelemesi yok. |
|Performans |Sınırlı örneklerde benzer RSS/inference maliyeti, ek hafif tarama maliyeti ölçüldü. |
|Cloud commit doğrulama |Yapılandırma eksik, tamamlanmadı. |
|Resmî RG/LEXPERA |ReadTimeout/ConnectTimeout ayrı; uygulamanın ayrıştırmasından önce oluşuyor. Kesintinin sahibi kesinleşmedi. |
|Kaynak/kalite/birim/dağıtım raporları |Ayrı işler; kalite eşiği halen başarısız. |
|Gerileme kontrolü |Birimler geçti; üretimde kapsamlı uzun süreli yük testi yok. |

PDF açma ve çıkarma, kaynak metin kayıpları, bilinmeyen görüş biçimleri ve ilk Bedesten sayfasına hiç girmeyen kararlar açık risklerdir. Eşanlamlısız tüm metni sinirsel tarama veya bütün Yargıtay'ı kapsayan vektör indeksi eklenmedi. Soru/karar metni üçüncü taraf embedding servisine gönderilmez.

## H. GitHub çıktısı

PR, bu raporu, ölçüm veri/protokollerini ve dar kapsamlı kod/test değişikliklerini birlikte içerir. Baseline `scripts/semantic_eval.py` aynen korunur. CI linkleri PR üzerinde gösterilir.

## I. Kullanım sonucu

Sistem aday karar bulma, kaynak metni getirme ve aynı kaynaktaki pasajı denetleme için kullanılabilir. Kosinüs puanı hukuki doğruluk, görüşün yönü veya çoğunluğun benimsediği gerekçe anlamına gelmez. Sonraki öncelik bağımsız hukuk uzmanlarının etiketlediği daha geniş gerçek karar havuzudur. Bu çalışma modelin nihai hukuki değerlendirme yaptığı iddiasını desteklemez.
