# PR3 üretim öncesi kontrolleri

İncelenen main `1bc1dc95d19ea06818a1e96c2ee76f1015928bb8`, PR3 başlangıç head `d9e735a1436a561265bbb054148690691fa98ae1`.

## Gerçek imaj

CI, PR'ın tam head SHA'sını checkout ederek `docker build --build-arg RELEASE_REVISION=...` çalıştırır. Sonraki adım `--network none` ile gerçek imaj içinde build SHA'sını, bütün çalışma dosyalarının hosttan bağımsız hesaplanan SHA256 özetlerini,22 araçlık MCP kataloğunu, istemci/sunucu şema eşitliğini ve normal daire-listesi çağrısını kontrol eder. İmaj kaynak/model değişiklikleri içermez; yalnız mevcut Dockerfile'ın gerçek build'i ve dağıtım öncesi testi eklenmiştir.

## Devralınan başarısızlık ve regresyon

Sabit12 sorunun soru kimlikleri ve veri/eşik betiği SHA256 ile donduruldu. `quality_regression.py` mevcut E5 sonuçlarını temel sürümün soru başına sıralarıyla karşılaştırır. Herhangi bir gerileme ayrı hatadır. Başlangıçtaki6/12 Top1,10/12 Top3 ve.6903 MRR aynen sürerse yeni regresyon yoktur, fakat eski kalite kabul testi başarısız kalır. Sabit kabul işi silinmedi veya etkisizleştirilmedi. Branch-protection ve zorunlu kontrol politikası bu çalışmada değiştirilmedi.

## Cloud yapılandırması

Bağlı MCP'nin güncel tanısı main'in13 dosyasıyla eşleştiğini, fakat çalışan commit SHA'sının null olduğunu gösterdi. `FASTMCP_VERIFY_TOKEN` için kullanılabilir bir kimlik bilgisi yok; token oluşturulmadı. CI imajında doğru SHA damgasının sınanması, yönetilen FastMCP Cloud'un aynı imajı veya build ayarlarını kullandığını kanıtlamaz. Üretim doğrulaması için Gateway'de yetkili token ve gerçek build SHA'sı hâlâ gereklidir. PR henüz üretime uygulanmış sayılmaz.

## Kısa deneme

`scripts/preflight_semantic.py` üç ayrı resmî kaydı kullanır: CGK2025/151, CGK2019/18 (49.854 karakter) ve1. Ceza Dairesi2024/1416. Kayıtların canlı edinimi ayrı adımdır. Gerçek imajdaki model testi bu kayıtlarla ağ kapalıyken çalışır. Her iki semantik çağrı yolu, eski pencere/tam çağrıları, sayfalı kaynak metni ve kaynak karakter aralığı karşılaştırılır. Künye, karar tarihi, metin SHA256 ve resmî URL bağımsız referansa sabitlenmiştir. Hukuki ilgi veya çoğunluk aidiyeti doğrulaması yapıldığı iddia edilmez.

Yerel kayıt denemesinde ilk model çağrısı dâhil CGK1,837s, uzun karar0,639s, ceza dairesi0,548s; uyumluluk yolu sırasıyla.675/.645/.582s bulundu. Peak RSS669,73MiB. Bu süreler ağsız kaynak yeniden oynatması ve yerel işlem için geçerlidir. CI'deki gerçek Docker build/çalıştırma sonuçları PR Checks alanında ayrı adımlardadır.

Yerel46 test geçti. Değerlendirme verisi, E5 modeli, kabul eşikleri, üretim araçları ve arama varsayılanları değiştirilmedi. Sonraki adım, teknik kontroller ile açık bilimsel/yapılandırma eksiklerini birlikte değerlendirerek birleştirme kararı vermektir.
