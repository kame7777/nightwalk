import streamlit as st
import osmnx as ox
import networkx as nx
import folium
from folium.plugins import MarkerCluster, HeatMap
from streamlit_folium import folium_static
from shapely.geometry import Point
import traceback
import pandas as pd
from functools import lru_cache
import glob
import sqlite3
import bcrypt
from datetime import datetime
import uuid
from shapely.geometry import LineString
from pathlib import Path
from utils import geocode_cached, detect_polarity



st.set_page_config(
    page_title="NightWalk",
    page_icon="🌙",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown(
    """
    <style>
    [data-testid="stSidebarNav"] {
        display: none;
    }
    </style>
    """,
    unsafe_allow_html=True
)


from sidebar import render_sidebar
render_sidebar()



def safe_graph_from_place(place):
    import osmnx as ox
    try:
        # 通常の place → polygon 取得
        return ox.graph_from_place(place, network_type="walk")
    except Exception:
        try:
            # geocode → bbox 取得
            geocode = ox.geocode_to_gdf(place)
            bounds = geocode.total_bounds  # [west, south, east, north]
            west, south, east, north = bounds

            # ★ OSRMnx v1.1〜1.2 は位置引数の graph_from_bbox を使用する必要がある
            return ox.graph_from_bbox(north, south, east, west, network_type="walk")

        except Exception as e:
            raise RuntimeError(f"フォールバック bbox も失敗: {e}")
        
# pyproj を使って緯度経度 -> 投影座標に変換する
try:
    from pyproj import Transformer, CRS
except Exception:
    Transformer = None

# -----------------------
# --- データベース設定 ---
# -----------------------
DB_PATH = "users.db"
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

def get_connection():
    # check_same_thread=False にしておくと Streamlit のマルチスレッドで便利
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    conn = get_connection()
    cur = conn.cursor()
    # ユーザーテーブル
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        email TEXT UNIQUE,
        password_hash BLOB
    )
    """)
    # 投稿（掲示板）テーブル
    cur.execute("""
    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        text TEXT,
        address TEXT,
        lat REAL,
        lon REAL,
        post_type TEXT,
        tags TEXT,
        image_path TEXT,
        polarity TEXT,
        created_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)
    # Ensure additional columns exist for older DBs
    cur.execute("PRAGMA table_info(reports)")
    cols = [r[1] for r in cur.fetchall()]
    # Add missing columns if necessary
    extra_cols = {
        'post_type': 'TEXT',
        'tags': 'TEXT',
        'image_path': 'TEXT',
        'polarity': 'TEXT'
    }
    for col, coltype in extra_cols.items():
        if col not in cols:
            try:
                cur.execute(f"ALTER TABLE reports ADD COLUMN {col} {coltype}")
            except Exception:
                pass
    conn.commit()
    conn.close()

init_db()

# -----------------------
# --- ユーザ認証関数 ---
# -----------------------
def signup(username, email, password):
    conn = get_connection()
    cur = conn.cursor()
    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    try:
        cur.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
            (username, email, password_hash)
        )
        conn.commit()
        return True, None
    except sqlite3.IntegrityError as e:
        # 一意制約違反（重複）
        if "username" in str(e).lower():
            return False, "そのユーザー名は既に使われています。"
        if "email" in str(e).lower():
            return False, "そのメールアドレスは既に使われています。"
        return False, "登録に失敗しました（重複等）。"
    except Exception as e:
        return False, str(e)
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
    user_id, username, email, password_hash = row
    # password_hash は bytes で保存されている
    if isinstance(password_hash, str):
        password_hash = password_hash.encode("utf-8")
    try:
        if bcrypt.checkpw(password.encode("utf-8"), password_hash):
            return {"id": user_id, "username": username, "email": email}
        else:
            return None
    except Exception:
        return None

# -----------------------
# --- 掲示板DB操作 ---
# -----------------------
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

# -----------------------
# --- ジオコーディング & CSV読み込み ---
# -----------------------
from pathlib import Path
import pandas as pd
import streamlit as st

@st.cache_data(show_spinner=False)
def load_crime_data():
    base = Path(__file__).parent
    csv_path = base / "data" / "crime_geocoded.csv"

    if not csv_path.exists():
        return []

    df = pd.read_csv(csv_path)
    return list(zip(df["lat"], df["lon"]))


# -----------------------
# --- OSM 街灯取得 ---
# -----------------------
import requests

OVERPASS_URLS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter"
]

def load_street_lamps_bbox(place):
    try:
        south, west, north, east = place


        query = f"""
        [out:json][timeout:120];
        (
          node["highway"="street_lamp"]({south},{west},{north},{east});
          node["man_made"="street_lamp"]({south},{west},{north},{east});
          node["amenity"="street_lamp"]({south},{west},{north},{east});
        );
        out body;
        """

        last_error = None

        for url in OVERPASS_URLS:
            try:
                r = requests.post(url, data=query, timeout=180)
                if r.status_code == 200:
                    data = r.json()
                    lamps = []
                    for el in data.get("elements", []):
                        if "lat" in el and "lon" in el:
                            lamps.append((el["lat"], el["lon"], el.get("tags", {})))
                    return lamps
                else:
                    last_error = f"{url} → HTTP {r.status_code}"
            except Exception as e:
                last_error = f"{url} → {e}"

        raise RuntimeError(last_error)

    except Exception as e:
        raise RuntimeError(f"Overpass API 取得失敗: {e}")


# -----------------------
# --- OSM コンビニ取得 ---
# -----------------------
def load_convenience_stores_bbox(place):
    try:
        south, west, north, east = place

        query = f"""
        [out:json][timeout:120];
        (
          node["shop"="convenience"]({south},{west},{north},{east});
          way["shop"="convenience"]({south},{west},{north},{east});
        );
        out center;
        """

        last_error = None

        for url in OVERPASS_URLS:
            try:
                r = requests.post(url, data=query, timeout=180)
                if r.status_code == 200:
                    data = r.json()
                    stores = []
                    for el in data.get("elements", []):
                        lat = el.get("lat") or el.get("center", {}).get("lat")
                        lon = el.get("lon") or el.get("center", {}).get("lon")
                        if lat and lon:
                            stores.append((lat, lon, el.get("tags", {})))
                    return stores
                else:
                    last_error = f"{url} → HTTP {r.status_code}"
            except Exception as e:
                last_error = f"{url} → {e}"

        raise RuntimeError(last_error)

    except Exception as e:
        raise RuntimeError(f"Overpass API 取得失敗: {e}")
    
# -----------------------
# --- OSM 交番取得 ---
# -----------------------
def load_koban_bbox(place):
    try:
        south, west, north, east = place

        query = f"""
        [out:json][timeout:120];
        (
          node["amenity"="police"]({south},{west},{north},{east});
          way["amenity"="police"]({south},{west},{north},{east});
          node["police"]({south},{west},{north},{east});
          way["police"]({south},{west},{north},{east});
        );
        out center;
        """

        last_error = None
        for url in OVERPASS_URLS:
            try:
                r = requests.post(url, data=query, timeout=180)
                if r.status_code == 200:
                    data = r.json()
                    kobans = []
                    for el in data.get("elements", []):
                        lat = el.get("lat") or el.get("center", {}).get("lat")
                        lon = el.get("lon") or el.get("center", {}).get("lon")
                        if lat and lon:
                            kobans.append((lat, lon, el.get("tags", {})))
                    return kobans
                else:
                    last_error = f"{url} → HTTP {r.status_code}"
            except Exception as e:
                last_error = f"{url} → {e}"

        raise RuntimeError(last_error)
    except Exception as e:
        raise RuntimeError(f"Overpass API 取得失敗: {e}")




# -----------------------
# --- Streamlit UI ---
# -----------------------
st.title("🌙 Night Walk - 夜道安全ルートナビ")


# --- メインUI ---
st.markdown(
    "出発地と目的地を入力し、検索モードを選択してルートを検索します。\n"
    "**安全ルートモード**は、犯罪発生地点を避けるようなルートを探索します（現在はデモ版です）。"
)

route_mode = st.radio("検索モード", ("最短ルート", "安全ルート"), index=1)

origin = st.text_input("出発地", "大宮駅, 埼玉")
destination = st.text_input("目的地", "さいたま新都心駅, 埼玉")
place = st.text_input("検索エリア", "さいたま市, 埼玉, Japan")
zoom = st.slider("地図のズーム", 13, 18, 15)



# --- 地図とルート検索 ---
if st.button("ルートを検索"):
    if Transformer is None:
        st.error("pyproj が必要です。 `pip install pyproj` を実行してください。")
        st.stop()

    if not all([origin, destination, place]):
        st.warning("出発地、目的地、エリアをすべて入力してください。")
        st.stop()

    try:
        # --- データ準備 ---
        st.info("OSM グラフと犯罪データを準備しています...")

        # 安全版 graph_from_place
        G = safe_graph_from_place(place)

        crime_locations = load_crime_data()



        # --- 座標変換 ---
        try:
            orig_latlon = geocode_cached(origin)
            dest_latlon = geocode_cached(destination)
        except Exception as e:
            st.error(f"住所変換エラー: {e}")
            st.stop()

        G_proj = ox.project_graph(G)
        crs_proj = G_proj.graph.get("crs", "EPSG:3857")
        target_crs = CRS.from_user_input(crs_proj)
        transformer = Transformer.from_crs("EPSG:4326", target_crs, always_xy=True)

        orig_x, orig_y = transformer.transform(orig_latlon[1], orig_latlon[0])
        dest_x, dest_y = transformer.transform(dest_latlon[1], dest_latlon[0])

        orig_node = ox.distance.nearest_nodes(G_proj, orig_x, orig_y)
        dest_node = ox.distance.nearest_nodes(G_proj, dest_x, dest_y)

        # --- ルート計算 ---
        st.info("ルートを計算しています...")

        weight = "length"
        route = nx.shortest_path(G_proj, orig_node, dest_node, weight=weight)

        # --- ルートのbbox（±300mの余白つき） ---
        xs = []
        ys = []
        for node in route:
            xs.append(G_proj.nodes[node]["x"])
            ys.append(G_proj.nodes[node]["y"])

        minx, maxx = min(xs), max(xs)
        miny, maxy = min(ys), max(ys)

        # 300m のバッファ
        buffer = 300
        minx -= buffer
        maxx += buffer
        miny -= buffer
        maxy += buffer

        # 緯度経度に戻す
        inv = Transformer.from_crs(G_proj.graph["crs"], "EPSG:4326", always_xy=True)
        west, south = inv.transform(minx, miny)
        east, north = inv.transform(maxx, maxy)

        bbox = (south, west, north, east)

        # --- 街灯とコンビニをルート周辺だけ取得 ---
        try:
            street_lamps = load_street_lamps_bbox(bbox)
        except Exception as e:
            st.warning(f"街灯取得失敗: {e}")
            street_lamps = []

        try:
            convenience_stores = load_convenience_stores_bbox(bbox)
        except Exception as e:
            st.warning(f"コンビニ取得失敗: {e}")
            convenience_stores = []

        try:
            kobans = load_koban_bbox(bbox)
        except Exception as e:
            st.warning(f"交番取得失敗: {e}")
            kobans = []



        # --- 安全コスト計算 ---
        from scipy.spatial import cKDTree
        import numpy as np

        crime_points_proj = []
        for lat, lon in crime_locations:
            crime_points_proj.append(transformer.transform(lon, lat))

        lamp_points = []
        store_points = []
        koban_points = []

        for lat, lon, _ in street_lamps:
            lamp_points.append(transformer.transform(lon, lat))

        for lat, lon, _ in convenience_stores:
            store_points.append(transformer.transform(lon, lat))

        for lat, lon, _ in kobans:
            koban_points.append(transformer.transform(lon, lat))

        crime_tree = cKDTree(crime_points_proj) if crime_points_proj else None
        lamp_tree  = cKDTree(lamp_points)  if lamp_points else None
        store_tree = cKDTree(store_points) if store_points else None
        koban_tree = cKDTree(koban_points) if koban_points else None


        for u, v, data in G_proj.edges(data=True):
            mid_x = (G_proj.nodes[u]['x'] + G_proj.nodes[v]['x']) / 2
            mid_y = (G_proj.nodes[u]['y'] + G_proj.nodes[v]['y']) / 2

            crime_penalty = 0
            if crime_tree:
                dist, _ = crime_tree.query([mid_x, mid_y])
                crime_penalty = max(0, 200 - dist) * 5

            lamp_bonus = 0
            if lamp_tree:
                d, _ = lamp_tree.query([mid_x, mid_y])
                lamp_bonus = max(0, 80 - d) * 1.5

            store_bonus = 0
            if store_tree:
                d, _ = store_tree.query([mid_x, mid_y])
                store_bonus = max(0, 150 - d) * 4

            koban_bonus = 0
            if koban_tree:
                d, _ = koban_tree.query([mid_x, mid_y])
                koban_bonus = max(0, 300 - d) * 8

            poi_bonus = lamp_bonus + store_bonus + koban_bonus


            base = data.get("length", 1)
            data["safety_cost"] = max(1, base + crime_penalty - poi_bonus)

        # ← ループの外で1回だけ実行
        route = nx.shortest_path(G_proj, orig_node, dest_node, weight="safety_cost")
        route_color = "red"

        # --- ルートの安全スコアを計算 ---
        total_length = 0
        total_safety_cost = 0

        for u, v in zip(route[:-1], route[1:]):
            if G_proj.is_multigraph():
                edge_data = G_proj.get_edge_data(u, v)[0]
            else:
                edge_data = G_proj.edges[u, v]

            length = edge_data.get("length", 0)
            safety = edge_data.get("safety_cost", length)

            total_length += length
            total_safety_cost += safety

        # 危険度（小さいほど安全）
        if total_length > 0:
            danger_score = total_safety_cost / total_length
        else:
            danger_score = float("inf")



        # --- 地図描画 ---
        st.info("地図描画中...")
        route_latlon = [(G.nodes[n]["y"], G.nodes[n]["x"]) for n in route]

        m = folium.Map(location=orig_latlon, zoom_start=zoom)

        if crime_locations:
            HeatMap(crime_locations, radius=15, blur=10).add_to(m)

        folium.PolyLine(route_latlon, color=route_color, weight=5, opacity=0.85).add_to(m)
        folium.Marker(location=orig_latlon, popup="出発地", icon=folium.Icon(color="green")).add_to(m)
        folium.Marker(location=dest_latlon, popup="目的地", icon=folium.Icon(color="red")).add_to(m)

        st.success("ルート検索完了")
        st.metric("🛡 このルートの危険度", f"{danger_score:.2f}")
        st.caption("※ 数値が小さいほど安全（街灯・コンビニ・交番が多く、犯罪が少ない）")



        # --- 街灯をマップへ描画（クラスタリング） ---
        if street_lamps:
            try:
                cluster = MarkerCluster(name="street_lamps")
                for lat, lon, info in street_lamps:
                    popup_text = ""
                    if info:
                        popup_text = ", ".join([f"{k}: {v}" for k, v in info.items()])
                    # Use small circle marker inside cluster for performance + visibility
                    marker = folium.CircleMarker(
                        location=[lat, lon],
                        radius=2,
                        color="yellow",
                        fill=True,
                        fill_opacity=0.9,
                        popup=popup_text or "街灯"
                    )
                    cluster.add_child(marker)
                m.add_child(cluster)
            except Exception:
                # フォールバック: 個別に描画（重い場合あり）
                for lat, lon, info in street_lamps:
                    try:
                        folium.CircleMarker(
                            location=[lat, lon],
                            radius=2,
                            color="yellow",
                            fill=True,
                            fill_opacity=0.9,
                            popup=", ".join([f"{k}: {v}" for k, v in info.items()]) if info else "街灯"
                        ).add_to(m)
                    except Exception:
                        continue

        if convenience_stores:
            store_cluster = MarkerCluster(name="convenience_stores")

            for lat, lon, tags in convenience_stores:
                name = tags.get("name", "コンビニ")
                brand = tags.get("brand", "")
                popup = f"{name} {brand}".strip()

                folium.Marker(
                    location=[lat, lon],
                    popup=popup,
                    icon=folium.Icon(
                        color="blue",
                        icon="shopping-cart",
                        prefix="fa"
                    )
                ).add_to(store_cluster)

            m.add_child(store_cluster)

            if kobans:
                koban_cluster = MarkerCluster(name="kobans")
            for lat, lon, tags in kobans:
                name = tags.get("name", "交番")
                folium.Marker(
                    location=[lat, lon],
                    popup=name,
                    icon=folium.Icon(color="darkblue", icon="shield", prefix="fa")
                ).add_to(koban_cluster)
            m.add_child(koban_cluster)


        folium.LayerControl(collapsed=False).add_to(m)

        folium_static(m, width=1000, height=700)

    except Exception:
        st.error("エラーが発生しました")

        st.text(traceback.format_exc())
