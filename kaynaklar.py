"""Resmî Gazete, AİHM HUDOC ve YÖK Ulusal Tez Merkezi araçları."""
import io
import json
import re
import zipfile
from datetime import date
from typing import Literal
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree as ET

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader

RG = "https://www.resmigazete.gov.tr"
HUDOC = "https://hudoc.echr.coe.int"
YOK = "https://tez.yok.gov.tr/UlusalTezMerkezi/"
TIMEOUT = httpx.Timeout(25, connect=8)


def page(text, start):
    if start < 0 or not text.strip():
        raise ValueError("Başlangıç negatif veya belge metni boş.")
    if start >= len(text):
        raise ValueError("Başlangıç belge uzunluğunu aşıyor.")
    end = start + 16000
    return {"metin": text[start:end], "toplam_karakter": len(text),
            "sonraki_baslangic": end if end < len(text) else None}


async def fetch(url, **kwargs):
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.get(url, **kwargs)
        response.raise_for_status()
        return response


def rg_date(tarih):
    day = date.fromisoformat(tarih)
    stamp = day.strftime("%Y%m%d")
    return stamp, f"{RG}/eskiler/{day:%Y/%m}/"


async def resmi_gazete_fihrist(tarih: str, mukerrer: int = 0, ikincil_kaynak: bool = True) -> dict:
    """Tarihli RG fihristi (YYYY-MM-DD). Resmî erişim başarısızsa isteğe bağlı, tarihi doğrulanmış LEXPERA listesi."""
    stamp, root = rg_date(tarih)
    if not 0 <= mukerrer <= 9:
        raise ValueError("Mükerrer sıra numarası 0–9 arasında olmalı.")
    issue = stamp + (f"M{mukerrer}" if mukerrer else "")
    url = (root + issue + ".htm") if mukerrer else (RG + "/fihrist?tarih=" + tarih)
    try:
        soup = BeautifulSoup((await fetch(url)).content, "html.parser")
        items = {}
        for a in soup.select("a[href]"):
            link = urljoin(url, a["href"])
            name = urlsplit(link).path.split("/")[-1]
            if not re.fullmatch(re.escape(issue)+r"-[0-9]+\.(?:htm|html|pdf)", name, re.I):
                continue
            title = " ".join(a.stripped_strings).strip("–- ")
            if title and urlsplit(link).hostname in ("resmigazete.gov.tr", "www.resmigazete.gov.tr"):
                items[name] = {"baslik":title,"belge":name,"kaynak":root+name}
        if not items:
            raise LookupError("İstenen sayı için resmî belge bağlantısı bulunamadı.")
        return {"tarih":tarih,"mukerrer":mukerrer,"resmi_kaynak":True,"kaynak":url,"belgeler":list(items.values())}
    except (httpx.HTTPError,LookupError) as exc:
        if not ikincil_kaynak or mukerrer:
            raise RuntimeError(f"Resmî fihrist doğrulanamadı: {url} ({type(exc).__name__})") from exc
    # Yalnızca başlığındaki yayın günü istenen tarihle eşleşen listeyi kullan.
    secondary = "https://www.lexpera.com.tr/resmi-gazete"
    soup = BeautifulSoup((await fetch(secondary)).content,"html.parser")
    heading = soup.select_one(".publication-list-title")
    day = date.fromisoformat(tarih).strftime("%d.%m.%Y")
    if not heading or day+"/" not in heading.get_text():
        raise LookupError(f"{tarih} tarihli sayı doğrulanamadı. Resmî fihrist: {url}")
    items = []
    for a in soup.select(".publication-list-item a[href]"):
        path = a["href"]
        if re.fullmatch(r"/resmi-gazete/metin/[a-z0-9-]+",path):
            items.append({"baslik":a.get_text(" ",strip=True),"belge":"lexpera:"+path.split("/")[-1],
                          "kaynak":urljoin(secondary,path)})
    if not items:
        raise LookupError("İkincil fihrist boş veya sayfa biçimi değişmiş.")
    return {"tarih":tarih,"sayi_basligi":heading.get_text(strip=True),"resmi_kaynak":False,
            "kaynak":secondary,"resmi_fihrist":url,"uyari":"İkincil kaynak; resmî siteden teyit edilemedi.","belgeler":items}


async def resmi_gazete_belgesi(belge: str, baslangic: int = 0) -> dict:
    """Fihristin döndürdüğü arşiv dosya adıyla yayım metnini oku."""
    if belge.startswith("lexpera:"):
        slug=belge.removeprefix("lexpera:")
        if not re.fullmatch(r"[a-z0-9-]{1,400}",slug):
            raise ValueError("İkincil fihristteki belge kodunu kullanın.")
        url="https://www.lexpera.com.tr/resmi-gazete/metin/"+slug
        soup=BeautifulSoup((await fetch(url)).content,"html.parser")
        article=soup.select_one(".document-content-wrapper")
        if not article:
            raise LookupError("İkincil kaynaktan açık metin alınamadı.")
        return {"resmi_kaynak":False,"kaynak":url,**page(article.get_text(" ",strip=True),baslangic)}
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})(?:M[1-9])?-\d+\.(?:htm|html|pdf)", belge, re.I)
    if not m:
        raise ValueError("Fihristteki belge adını kullanın.")
    _, root = rg_date("-".join(m.groups()))
    url = root + belge
    r = await fetch(url)
    if r.content.startswith(b"%PDF"):
        text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(r.content)).pages)
    else:
        soup = BeautifulSoup(r.content,"html.parser")
        for tag in soup(["head","script","style","nav","footer"]):
            tag.decompose()
        text = soup.get_text(" ",strip=True)
        if not re.search(r"resm[îi]\s+gazete",text,re.I) or not re.search(r"madde|karar|tebliğ|yönetmelik",text,re.I):
            raise LookupError("Resmî yayım metni doğrulanamadı.")
    return {"resmi_kaynak":True,"kaynak":url, **page(text,baslangic)}


def literal(value):
    return '"' + value.replace('\\','\\\\').replace('"','\\"') + '"'


async def aihm_ara(ifade: str = "", ulke: str = "", dil: str = "ENG", basvuru_no: str = "",
                   ilk_tarih: str = "", son_tarih: str = "", sayfa: int = 1, adet: int = 10,
                   koleksiyon: Literal["JUDGMENTS","DECISIONS"]="JUDGMENTS") -> dict:
    """HUDOC kararlarını karar tarihi azalan sırada ara. Ülke TUR, dil ENG/FRE/TUR; tarihler YYYY-MM-DD."""
    if not re.fullmatch("[A-Z]{3}", dil) or (ulke and not re.fullmatch("[A-Z]{3}",ulke)):
        raise ValueError("Üç harfli dil/ülke kodu kullanın.")
    if not 1<=adet<=50 or sayfa<1:
        raise ValueError("Sayfa veya adet geçersiz.")
    terms = ["(contentsitename:ECHR)",f"(documentcollectionid2:{literal(koleksiyon)})",f"(languageisocode:{literal(dil)})"]
    if ifade.strip():
        terms.append(f"({literal(ifade.strip())})")
    for key,val in (("respondent",ulke),("appno",basvuru_no)):
        if val:
            terms.append(f"({key}:{literal(val)})")
    if ilk_tarih or son_tarih:
        lo=date.fromisoformat(ilk_tarih).isoformat()+"T00:00:00" if ilk_tarih else "*"
        hi=date.fromisoformat(son_tarih).isoformat()+"T23:59:59" if son_tarih else "*"
        if ilk_tarih and son_tarih and lo > hi:
            raise ValueError("Başlangıç tarihi bitiş tarihinden sonra olamaz.")
        terms.append(f"(kpdate:[{lo} TO {hi}])")
    params={"query":" AND ".join(terms),"select":"itemid,docname,appno,kpdate,languageisocode,documentcollectionid2,doctype,respondent",
            "sort":"kpdate Descending","start":(sayfa-1)*adet,"length":adet}
    data=(await fetch(HUDOC+"/app/query/results",params=params)).json()
    if not isinstance(data.get("results"),list) or not isinstance(data.get("resultcount"),int):
        raise RuntimeError("HUDOC sonuç listesi doğrulanamadı.")
    records=[]
    for result in data["results"]:
        row=result["columns"]
        records.append({**row,"kaynak":HUDOC+"/eng?i="+row["itemid"]})
    return {"toplam":data["resultcount"],"sayfa":sayfa,"sonuclar":records}


async def aihm_karar_getir(karar_id: str, baslangic: int = 0) -> dict:
    """HUDOC aramasındaki yayın kimliğiyle kararın orijinal dildeki metnini oku."""
    if not re.fullmatch(r"\d{3}-\d{1,12}",karar_id):
        raise ValueError("HUDOC itemid gereklidir.")
    r=await fetch(HUDOC+"/app/conversion/docx/",params={"library":"ECHR","id":karar_id,"filename":"decision.docx"})
    with zipfile.ZipFile(io.BytesIO(r.content)) as doc:
        xml=ET.fromstring(doc.read("word/document.xml"))
    ns="{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    text="\n".join("".join(t.text or "" for t in p.iter(ns+"t")) for p in xml.iter(ns+"p"))
    return {"id":karar_id,"kaynak":HUDOC+"/eng?i="+karar_id,**page(text,baslangic)}


async def yoktez_ara(ifade: str, alan: Literal["tümü","tez adı","yazar","danışman","konu","anahtar kelime","özet","tez no"]="tez adı",
                     sayfa: int=1, adet: int=10) -> dict:
    """YÖK Ulusal Tez Merkezi kamuya açık kataloğunda ara; kurumdaki ilk sonuç kümesini sayfalar."""
    if len(ifade.strip())<3 or not 1<=adet<=50 or sayfa<1:
        raise ValueError("En az üç karakter, pozitif sayfa ve 1–50 sonuç gerekir.")
    fields={"tez adı":1,"yazar":2,"danışman":3,"konu":4,"anahtar kelime":5,"özet":6,"tümü":7,"tez no":8}
    async with httpx.AsyncClient(timeout=TIMEOUT,follow_redirects=True) as client:
        (await client.get(YOK)).raise_for_status()
        r=await client.post(YOK+"SearchTez",data={"neden":ifade,"nevi":str(fields[alan]),"islem":"1","tur":"0","izin":"0"})
        r.raise_for_status()
    soup=BeautifulSoup(r.content,"html.parser",from_encoding="utf-8")
    cards=soup.select(".result-card[data-kayitno][data-tezno]")
    if not cards and "sonuç bulunamadı" not in soup.get_text(" ",strip=True).lower():
        raise RuntimeError("YÖK sonuç sayfası doğrulanamadı.")
    meta={}
    match=re.search(r"const\s+referenceData\s*=\s*(\{.*?\})\s*;",r.text,re.S)
    if match:
        try:
            meta=json.loads(re.sub(r",\s*([}\]])",r"\1",match[1]))
        except ValueError:
            pass
    rows=[]
    for card in cards[(sayfa-1)*adet:sayfa*adet]:
        title=card.select_one(".card-title")
        num=re.search(r"Tez No:\s*(\d+)",card.get_text(" ",strip=True))
        if not title or not num:
            raise RuntimeError("YÖK künyesi okunamadı.")
        key,token=card["data-kayitno"],card["data-tezno"]
        rows.append({"tez_no":num[1],"baslik":title.get_text(" ",strip=True),"kayit":key,"belge":token,
                     "kunye":meta.get(card.get("data-index"),{}).get("meta",{}),
                     "kaynak":YOK+f"tezDetay.jsp?id={key}&no={token}"})
    return {"kaynak_sayfasindaki_kayit":len(cards),"sayfa":sayfa,"sonuclar":rows}


async def yoktez_detay(kayit: str, belge: str) -> dict:
    """Arama sonucundaki kayıt ve belge anahtarlarıyla YÖK'ün açık özeti, danışman ve atıf bilgisini getir."""
    if not all(re.fullmatch(r"[\w=-]{1,160}",x,flags=re.ASCII) for x in (kayit,belge)):
        raise ValueError("Aramadan dönen kayıt ve belge anahtarları gereklidir.")
    url=YOK+"tezBilgiDetay.jsp"
    r=await fetch(url,params={"kayitNo":kayit,"tezNo":belge})
    data=r.json()
    keys=("trOzet","enOzet","danisman","yer","apa_ref","anahtarKelimeTr")
    if not any(data.get(k) for k in keys):
        raise LookupError("YÖK kayıt ayrıntısı doğrulanamadı.")
    pdf_url = None
    pdf_status = "bağlantı bulunamadı"
    try:
        availability=await fetch(YOK+"getTezPdf.jsp",params={"kayitNo":kayit,"tezNo":belge})
        link=BeautifulSoup(availability.content,"html.parser").select_one("a[href^='TezGoster?key=']")
        if link:
            pdf_url=urljoin(YOK,link["href"])
            pdf_status = "bağlantı bulundu"
    except httpx.HTTPError:
        pdf_status = "kaynağa erişilemedi"
    return {**{k:BeautifulSoup(str(data.get(k) or ""),"html.parser").get_text(" ",strip=True) for k in keys},
            "acik_pdf":pdf_url,"pdf_durumu":pdf_status,"kaynak":YOK+f"tezDetay.jsp?id={kayit}&no={belge}"}


def register(mcp):
    for fn in (resmi_gazete_fihrist,resmi_gazete_belgesi,aihm_ara,aihm_karar_getir,yoktez_ara,yoktez_detay):
        mcp.tool(fn,annotations={"readOnlyHint":True})
