import osmnx as ox
from functools import lru_cache

# -----------------------
# ジオコーディング
# -----------------------
@lru_cache(maxsize=None)
def geocode_cached(query):
    return ox.geocode(query)

# -----------------------
# 投稿のポジネガ判定
# -----------------------
def detect_polarity(text, tags_text=None):
    positive = ["安全", "明る", "広い", "問題ない", "安心", "見通し良"]
    negative = ["暗", "怖", "危", "怪しい", "人通り少", "危険", "狭い"]

    score = 0
    txt = (text or "").lower()

    for w in positive:
        if w in txt:
            score += 1
    for w in negative:
        if w in txt:
            score -= 1

    if tags_text:
        for t in tags_text.split(","):
            t = t.strip()
            for w in positive:
                if w in t:
                    score += 1
            for w in negative:
                if w in t:
                    score -= 1

    return "良い方向" if score >= 0 else "悪い方向"
