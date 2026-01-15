import streamlit as st
from pathlib import Path
import uuid
import streamlit.components.v1 as components
import folium

from sidebar import render_sidebar
from auth_db import load_reports, save_report, UPLOAD_DIR
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


render_sidebar()
st.title("📝 夜道掲示板 - 投稿と確認")

# ユーザー認証
allow_post = st.session_state.get("user") is not None
if not allow_post:
    st.info("掲示板に投稿するにはログインしてください（サイドバーからログイン）")

# --- 場所の入力セクション（フォーム外で実装） ---
st.write("### 場所の入力")
st.info("💡 下から、地図上でピンを刺すか、手動で住所を入力してください。")

input_method = st.radio("入力方法を選択", ("地図上でピン刺し", "手動入力"), horizontal=True, key="input_method")

report_address = None
manual_lat = None
manual_lon = None

if input_method == "地図上でピン刺し":
    st.write("#### 地図上で投稿位置をクリック:")
    st.caption("地図をクリックすれば座標が自動で反映されます")
    
    # デフォルト位置（さいたま市）
    default_lat, default_lon = 35.8617, 139.6455
    
    # 初期化
    if "map_selected_lat" not in st.session_state:
        st.session_state["map_selected_lat"] = None
    if "map_selected_lon" not in st.session_state:
        st.session_state["map_selected_lon"] = None
    if "map_selected_address" not in st.session_state:
        st.session_state["map_selected_address"] = ""
    
    # Folium地図を作成
    m = folium.Map(
        location=[default_lat, default_lon],
        zoom_start=15,
        tiles="OpenStreetMap"
    )
    
    # クリック位置にマーカーを追加（既に選択されている場合）
    if st.session_state["map_selected_lat"] is not None and st.session_state["map_selected_lon"] is not None:
        folium.Marker(
            location=[st.session_state["map_selected_lat"], st.session_state["map_selected_lon"]],
            popup=f"緯度: {st.session_state['map_selected_lat']}<br>経度: {st.session_state['map_selected_lon']}",
            color="red"
        ).add_to(m)
    
    # クリック時にポップアップ表示用のLatLngPopupを追加
    m.add_child(folium.LatLngPopup())
    
    # 地図を表示（st_foliumで返り値としてクリック情報を取得）
    try:
        from streamlit_folium import st_folium
        map_data = st_folium(m, width=700, height=400)
        
        # クリック情報を処理
        if map_data and map_data.get("last_clicked"):
            click_info = map_data["last_clicked"]
            lat = click_info["lat"]
            lon = click_info["lng"]
            
            # 座標を保存
            st.session_state["map_selected_lat"] = round(lat, 6)
            st.session_state["map_selected_lon"] = round(lon, 6)
            
            # 住所を自動取得
            try:
                import requests
                response = requests.get(
                    f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=18",
                    timeout=5
                )
                if response.status_code == 200:
                    data = response.json()
                    address = data.get("display_name", "住所不明")
                    st.session_state["map_selected_address"] = address
            except:
                st.session_state["map_selected_address"] = f"(座標: {lat:.6f}, {lon:.6f})"
            
            st.rerun()
    except ImportError:
        # st_foliumが無い場合はfolium_staticを使用
        from streamlit_folium import folium_static
        map_data = folium_static(m, width=700, height=400)
    
    st.write("---")
    st.write("#### 選択済みの位置:")
    
    # 選択状態を表示
    if st.session_state["map_selected_lat"] is not None:
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("緯度", f"{st.session_state['map_selected_lat']:.6f}")
        
        with col2:
            st.metric("経度", f"{st.session_state['map_selected_lon']:.6f}")
        
        with col3:
            if st.session_state["map_selected_address"]:
                st.info(f"📍 {st.session_state['map_selected_address']}")
        
        report_address = st.session_state["map_selected_address"]
        manual_lat = st.session_state["map_selected_lat"]
        manual_lon = st.session_state["map_selected_lon"]
    else:
        st.info("💡 地図をクリックして位置を選択してください")
    
else:  # 手動入力
    st.write("#### 手動で住所を入力:")
    
    # 現在位置を取得するボタン
    components.html("""
    <button id="getLocationBtn" style="padding: 10px; background-color: #4CAF50; color: white; border: none; border-radius: 4px; cursor: pointer;">現在の位置を取得</button>
    <script>
    document.getElementById('getLocationBtn').addEventListener('click', function() {
        if (navigator.geolocation) {
            navigator.geolocation.getCurrentPosition(function(position) {
                const lat = position.coords.latitude;
                const lon = position.coords.longitude;
                // 逆ジオコーディング
                fetch(`https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lon}`)
                .then(response => response.json())
                .then(data => {
                    const address = data.display_name;
                    // テキストフィールドにセット
                    const input = document.querySelector('input[aria-label="場所（住所・建物名など）"]');
                    if (input) {
                        input.value = address;
                        // Streamlitのイベントをトリガーして更新
                        input.dispatchEvent(new Event('input', { bubbles: true }));
                    }
                })
                .catch(error => {
                    alert('住所の取得に失敗しました: ' + error.message);
                });
            }, function(error) {
                alert('位置情報の取得に失敗しました: ' + error.message);
            });
        } else {
            alert('Geolocation is not supported by this browser.');
        }
    });
    </script>
    """, height=50)
    
    report_address = st.text_input("場所（住所・建物名など）", key="report_address")
    
    # 緯度経度を手動入力するためのフィールド
    use_manual_coords = st.checkbox("緯度・経度を手動で指定する（直接座標入力したい場合）", key="use_manual_coords")
    if use_manual_coords:
        col1, col2 = st.columns(2)
        with col1:
            manual_lat = st.text_input("緯度 (lat)", key="manual_lat")
        with col2:
            manual_lon = st.text_input("経度 (lon)", key="manual_lon")

# --- 投稿フォーム（場所選択の後）---
with st.form("report_form"):
    post_type = st.radio("投稿タイプ", ("コメントのみ", "タグのみ", "コメントとタグ"), index=0)
    # コメント欄（コメントのみ or 両方 の場合は本文入力欄を目立たせるが、いずれのケースでも入力欄は表示する）
    report_text = st.text_input("内容（例：この道が暗くて怖かったなど）", key="report_text")

    # タグ入力: カテゴリごとにタブで選択できるUI
    st.markdown("タグを選択（複数選択可）")
    tab1, tab2, tab3 = st.tabs(["環境", "人通り/時間帯", "その他"])
    selected_tags = []
    with tab1:
        lighting = st.multiselect(
            "照明状況",
            ["暗い", "薄暗い", "明るい", "街灯あり", "街灯なし", "ちらほら"],
            key="tag_lighting",
        )
        road = st.multiselect(
            "道の状態",
            ["狭い", "広い", "段差あり", "歩道なし", "歩道あり", "舗装不良", "水たまりあり"],
            key="tag_road",
        )
        selected_tags.extend(lighting)
        selected_tags.extend(road)
    with tab2:
        crowd = st.multiselect(
            "人通り",
            ["人通り少ない", "人通り多い", "昼は多い", "夜は少ない", "夜間人気がない"],
            key="tag_crowd",
        )
        time = st.multiselect(
            "時間帯の特徴",
            ["深夜に危険", "深夜帯に危険", "夕方に危険", "明け方に危険", "帰宅時間に混雑", "朝は静か"],
            key="tag_time",
        )
        selected_tags.extend(crowd)
        selected_tags.extend(time)
    with tab3:
        crime = st.multiselect(
            "その他の問題",
            [
                "危険人物目撃",
                "路上泥酔者",
                "不審物",
                "暴力目撃",
                "ひったくり注意",
                "視界が悪い",
                "角が多い",
                "建物で見通し悪い",
                "駐輪場あり",
                "駐輪場暗い",
                "駐車場あり",
                "過去に警察出動あり",
            ],
            key="tag_other",
        )
        selected_tags.extend(crime)

    # カスタムタグ入力も可能
    custom_tags = st.text_input("カスタムタグ（任意・カンマ区切り）", key="report_custom_tags")
    if custom_tags:
        selected_tags.extend([t.strip() for t in custom_tags.split(",") if t.strip()])
    tags_input = ",".join(selected_tags) if selected_tags else ""
    
    uploaded_file = st.file_uploader("画像（任意）", type=["png", "jpg", "jpeg"], key="report_image")
    report_submit = st.form_submit_button("投稿")

if report_submit:
    if not allow_post:
        st.warning("投稿にはログインが必要です。")
    else:
        # バリデーション: 投稿タイプに応じて必須項目をチェック
        missing = False
        if post_type == "コメントのみ":
            if not report_text or not report_address:
                missing = True
        elif post_type == "タグのみ":
            if (not tags_input) or (not report_address):
                missing = True
        elif post_type == "コメントとタグ":
            # 住所は必須。本文またはタグのいずれかは必須。
            if not report_address or (not report_text and not tags_input):
                missing = True

        if missing:
            st.warning("必要な入力を行ってください（場所は必須。コメントまたはタグを指定してください）。")
        else:
            lat = lon = None
            
            # 地図から選択された座標を優先
            if input_method == "地図上でピン刺し":
                map_lat = st.session_state.get("map_selected_lat")
                map_lon = st.session_state.get("map_selected_lon")
                
                if not map_lat or not map_lon:
                    st.error("❌ 地図上で位置をクリックしてから投稿してください。")
                    st.stop()
                
                try:
                    lat = float(map_lat)
                    lon = float(map_lon)
                except Exception:
                    st.error("❌ 地図から取得した座標が無効です。もう一度地図をクリックしてください。")
                    st.stop()
                    
                # 地図から取得した住所を使用
                if not report_address:
                    report_address = st.session_state.get("map_selected_address", "座標")
                    
            elif st.session_state.get("use_manual_coords"):
                # 手動緯度経度が入力されていればそれを優先
                manual_lat = st.session_state.get("manual_lat", "").strip()
                manual_lon = st.session_state.get("manual_lon", "").strip()
                
                if manual_lat and manual_lon:
                    try:
                        lat = float(manual_lat)
                        lon = float(manual_lon)
                    except Exception:
                        st.error("❌ 緯度/経度の形式が不正です。小数（例: 35.1234）で入力してください。")
                        st.stop()
                else:
                    st.error("❌ 緯度と経度を入力してください。")
                    st.stop()
            else:
                try:
                    lat, lon = geocode_cached(report_address)
                except Exception as e:
                    st.error("住所から位置情報を取得できませんでした。別の表現で試してください。")
                    st.error(str(e))
                    lat = lon = None

            if lat is None or lon is None:
                # geocode failed or missing coords
                st.stop()

            # 画像があれば保存
            image_path = None
            if uploaded_file is not None:
                try:
                    ext = Path(uploaded_file.name).suffix
                    fname = f"{uuid.uuid4().hex}{ext}"
                    out_path = UPLOAD_DIR / fname
                    with open(out_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    image_path = str(out_path)
                except Exception as e:
                    st.warning(f"画像の保存に失敗しました: {e}")

            # 自動判定
            polarity = detect_polarity(report_text, tags_input)

            # DB 保存
            try:
                rid = save_report(
                    st.session_state["user"],
                    report_text,
                    report_address,
                    lat,
                    lon,
                    post_type=post_type,
                    tags=tags_input,
                    image_path=image_path,
                    polarity=polarity,
                )
                if rid:
                    st.success("投稿を保存しました！")
                else:
                    st.error("投稿保存に失敗しました。")
            except Exception as e:
                st.error("投稿の保存中にエラーが発生しました。")
                st.error(str(e))

# --- 投稿一覧 ---
st.subheader("📍 投稿された怖い場所（掲示板）")
reports = load_reports()
if reports:
    for r in reports[:50]:  # 最新50件表示
        created = r["created_at"][:19] if r["created_at"] else ""
        user_label = r["username"] or "匿名"
        st.markdown(f"**{user_label}** - {created}")
        # 表示: 投稿タイプ / タグ / 判定
        meta = []
        if r.get("post_type"):
            meta.append(f"タイプ: {r.get('post_type')}")
        if r.get("tags"):
            meta.append(f"タグ: {r.get('tags')}")
        if r.get("polarity"):
            meta.append(f"判定: {r.get('polarity')}")
        if meta:
            st.caption(" | ".join(meta))
        if r.get("text"):
            st.write(r["text"])
        st.caption(r["address"])
        # 画像があれば表示
        if r.get("image_path"):
            try:
                st.image(r.get("image_path"), width=350)
            except Exception:
                pass
        st.markdown("---")
else:
    st.write("まだ投稿はありません。")
