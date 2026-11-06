import time
import unittest

from passage_selection import _terms, _windows, bm25_scores, select_passages


QUESTION = "Somut emare bulunmadan konutta arama yapılabilir mi?"
TARGET = "Kolluk görevlisinin meskene girmesi ve ikamet edilen yeri araması için somut belirtiler gösterilmemiştir."


def fixture(position, length=160000):
    neutral = ("Temyiz isteminde harç hesabı ile vekâlet ücretinin miktarı tartışıldı. " * 4000)[:length]
    at = int(length * position)
    return neutral[:at] + "\n" + TARGET + "\n" + neutral[at:], at+1


def old_passages(text):
    last = max(0, len(text)-680)
    count = min(20, 1+(last+499)//500)
    return [(last*i//max(1,count-1), text[last*i//max(1,count-1):last*i//max(1,count-1)+680]) for i in range(count)]


def recall_benchmark():
    positions = (0.071, 0.173, 0.291, 0.413, 0.537, 0.643, 0.763, 0.881, 0.947, 0.983)
    results = {}
    for name, selector in (("before", lambda text:old_passages(text)),
                           ("after", lambda text:select_passages(text, QUESTION))):
        hits = selected = scanned = 0
        started = time.perf_counter()
        for position in positions:
            text, offset = fixture(position)
            passages = selector(text)
            hits += any(start <= offset and start+len(excerpt) >= offset+len(TARGET) for start, excerpt in passages)
            selected += len(passages)
            scanned += len(_windows(text)) if name == "after" else len(passages)
        results[name] = {"hits": hits, "cases":len(positions), "selected":selected,
                         "scanned_windows":scanned, "seconds":time.perf_counter()-started}
    return results


class PassageSelectionTests(unittest.TestCase):
    def test_late_and_middle_synonymous_reasons_are_kept(self):
        for position in (0.413, 0.947):
            text, offset = fixture(position)
            passages = select_passages(text, QUESTION)
            self.assertTrue(any(start <= offset and start+len(excerpt) >= offset+len(TARGET) for start, excerpt in passages))
            self.assertLessEqual(len(passages),20)
            self.assertTrue(all(excerpt == text[start:start+len(excerpt)] and len(excerpt)<=680 for start,excerpt in passages))

    def test_no_lexical_match_still_has_coverage(self):
        text = "Borç miktarı hesaplandı. " * 5000
        passages = select_passages(text,"Tanıkla yüzleşme hakkı",limit=8)
        self.assertEqual(len(passages),8)
        self.assertEqual(passages[0][0],0)
        self.assertGreater(passages[-1][0],len(text)*0.95)

    def test_windows_cover_whole_source_and_keep_explicit_sections(self):
        text = "Açıklama. " * 200 + "\nKARŞI OY\n" + "Katılmıyorum. " * 200
        windows = _windows(text)
        marker = text.index("KARŞI OY")
        self.assertFalse(any(start < marker-1 and end > marker+10 for start,end in windows))
        self.assertEqual(windows[0][0],0)
        self.assertEqual(windows[-1][1],len(text))
        self.assertTrue(all(next_start <= end+50 for (_,end),(next_start,_) in zip(windows,windows[1:])))

    def test_home_synonyms_use_known_inflections_only(self):
        self.assertEqual(_terms("ev evde evinde evlerinden", expand=True), ["konut"] * 4)
        self.assertEqual(_terms("evet evren evrensel evrak", expand=True),
                         ["evet", "evren", "evrensel", "evrak"])

    def test_standard_bm25_and_bounds(self):
        scores = bm25_scores("arama", ["arama arama", "temyiz harcı"])
        self.assertGreater(scores[0], scores[1])
        self.assertEqual(select_passages("", QUESTION),[])
        self.assertEqual(select_passages("Kısa metin",QUESTION),[(0,"Kısa metin")])
        with self.assertRaises(ValueError):
            select_passages("metin", QUESTION,37)


if __name__ == "__main__":
    unittest.main()
