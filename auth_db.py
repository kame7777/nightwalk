# auth_db.py
import sqlite3
import bcrypt
from datetime import datetime
from pathlib import Path

DB_PATH = "users.db"
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

def get_connection():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

# ---------- ユーザー認証 ----------
def signup(username, email, password):
    conn = get_connection()
    cur = conn.cursor()
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
    try:
        cur.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
            (username, email, password_hash)
        )
        conn.commit()
        return True, None
    except sqlite3.IntegrityError as e:
        if "username" in str(e).lower():
            return False, "そのユーザー名は既に使われています"
        if "email" in str(e).lower():
            return False, "そのメールアドレスは既に使われています"
        return False, "登録に失敗しました"
    finally:
        conn.close()

def login(email_or_username, password):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, username, email, password_hash FROM users WHERE email = ? OR username = ?",
        (email_or_username, email_or_username)
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    uid, username, email, pw = row
    if bcrypt.checkpw(password.encode(), pw):
        return {"id": uid, "username": username, "email": email}
    return None

# ---------- 掲示板 ----------
def save_report(user, text, address, lat, lon, post_type=None, tags=None, image_path=None, polarity=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO reports (user_id, username, text, address, lat, lon, post_type, tags, image_path, polarity, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            user["id"] if user else None,
            user["username"] if user else None,
            text,
            address,
            lat,
            lon,
            post_type,
            tags,
            image_path,
            polarity,
            datetime.utcnow().isoformat(),
        ),
    )
    rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid

def load_reports():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, user_id, username, text, address, lat, lon, post_type, tags, image_path, polarity, created_at FROM reports ORDER BY created_at DESC")
    rows = cur.fetchall()
    conn.close()
    reports = []
    for r in rows:
        reports.append({
            "id": r[0],
            "user_id": r[1],
            "username": r[2],
            "text": r[3],
            "address": r[4],
            "lat": r[5],
            "lon": r[6],
            "post_type": r[7],
            "tags": r[8],
            "image_path": r[9],
            "polarity": r[10],
            "created_at": r[11],
        })
    return reports


def update_report_with_meta(report_id, post_type=None, tags=None, image_path=None, polarity=None):
    conn = get_connection()
    cur = conn.cursor()
    updates = []
    params = []
    if post_type is not None:
        updates.append("post_type = ?")
        params.append(post_type)
    if tags is not None:
        updates.append("tags = ?")
        params.append(tags)
    if image_path is not None:
        updates.append("image_path = ?")
        params.append(image_path)
    if polarity is not None:
        updates.append("polarity = ?")
        params.append(polarity)
    if not updates:
        conn.close()
        return
    params.append(report_id)
    sql = f"UPDATE reports SET {', '.join(updates)} WHERE id = ?"
    cur.execute(sql, params)
    conn.commit()
    conn.close()


def detect_polarity(text, tags_text=None):
    # 簡易ルールベース判定: ポジティブ語/ネガティブ語のカウントで判定
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
        for t in (tags_text or "").split(','):
            tt = t.strip()
            if not tt:
                continue
            for w in positive:
                if w in tt:
                    score += 1
            for w in negative:
                if w in tt:
                    score -= 1
    return "良い方向" if score >= 0 else "悪い方向"
