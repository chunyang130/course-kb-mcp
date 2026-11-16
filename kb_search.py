"""知識庫載入與檢索（BM25＋同義詞擴充），與 course-qa-rag 專案使用相同的方法。"""
import glob, math, os, re
from collections import Counter


def tokenize(text):
    """英文、數字取整個詞；中文連續字串切成兩字一組（bigram），單一個中文字就保留單字。"""
    text = text.lower().replace(",", "")
    tokens = re.findall(r"[a-z]+|\d+(?:\.\d+)?", text)
    for run in re.findall(r"[一-鿿]+", text):
        tokens += [run] if len(run) == 1 else [run[i:i + 2] for i in range(len(run) - 1)]
    return tokens


class BM25:
    def __init__(self, docs, k1=1.5, b=0.75):
        self.k1, self.b = k1, b
        self.tfs = [Counter(tokenize(d)) for d in docs]
        self.lens = [sum(tf.values()) for tf in self.tfs]
        self.avg = sum(self.lens) / len(self.lens)
        df = Counter(t for tf in self.tfs for t in tf)
        n = len(docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def scores(self, query):
        q = tokenize(query)
        out = []
        for tf, ln in zip(self.tfs, self.lens):
            s = 0.0
            for t in q:
                if t in tf:
                    f = tf[t]
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * ln / self.avg))
            out.append(s)
        return out


# 同義詞擴充：學員的說法 → 文件裡的用詞。關鍵字檢索認不出同義詞，所以在搜尋前補上文件用語
SYNONYMS = {
    "錯過": "缺課", "沒去上": "缺課", "請假": "缺課", "補上": "補課",
    "暫停": "保留學籍", "停課": "保留學籍", "先停": "保留學籍", "休學": "保留學籍",
    "打折": "優惠 折", "便宜": "優惠", "多少錢": "價 費用", "學費": "價",
    "幾點": "時間", "開門": "營業時間",
}


def expand(question):
    extra = [v for k, v in SYNONYMS.items() if k in question]
    return question + (" " + " ".join(extra) if extra else "")


class KnowledgeBase:
    def __init__(self, kb_dir):
        self.docs = {}      # name -> (title, full text)
        self.chunks = []
        for path in sorted(glob.glob(os.path.join(kb_dir, "*.md"))):
            name = os.path.splitext(os.path.basename(path))[0]
            text = open(path, encoding="utf-8").read()
            m = re.search(r"^# (.+)$", text, flags=re.M)
            title = re.sub(r"（.*?）", "", m.group(1)).strip() if m else name
            self.docs[name] = (title, text)
            for i, sec in enumerate(re.split(r"^## ", text, flags=re.M)[1:], 1):
                heading, _, body = sec.partition("\n")
                self.chunks.append({"id": f"{name}#{i}", "doc": name, "heading": heading.strip(),
                                    "text": f"{title}－{heading.strip()}\n{body.strip()}"})
        self.index = BM25([c["text"] for c in self.chunks])

    def document_names(self):
        return list(self.docs)

    def document_text(self, name):
        return self.docs[name][1]

    def outline(self):
        return [(n, t, [c["heading"] for c in self.chunks if c["doc"] == n]) for n, (t, _) in self.docs.items()]

    def search(self, query, k=4):
        ranked = sorted(zip(self.index.scores(expand(query)), self.chunks), key=lambda x: -x[0])
        return [dict(c, score=round(s, 2)) for s, c in ranked[:k] if s > 0]
