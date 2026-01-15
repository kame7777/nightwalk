# sidebar.py
import streamlit as st
from auth_db import login, signup

def render_sidebar():
    st.sidebar.title("🌙 NightWalk")

    st.sidebar.page_link("app.py", label="🏠 ホーム(ルート検索)")
    st.sidebar.page_link("pages/bbs.py", label="📝 掲示板")

    st.sidebar.divider()
    st.sidebar.title("ユーザー")

    if "user" not in st.session_state:
        st.session_state["user"] = None

    if st.session_state["user"] is None:
        mode = st.sidebar.radio(
            "操作",
            ("ログイン", "新規登録", "ゲストで利用"),
            key="auth_mode"   # ← 念のため key も付与
        )

        if mode == "ログイン":
            with st.sidebar.form("login_form"):
                u = st.text_input("メール or ユーザー名")
                p = st.text_input("パスワード", type="password")
                ok = st.form_submit_button("ログイン")
            if ok:
                user = login(u, p)
                if user:
                    st.session_state["user"] = user
                    st.rerun()
                else:
                    st.error("ログイン失敗")

        elif mode == "新規登録":
            with st.sidebar.form("signup_form"):
                n = st.text_input("ユーザー名")
                e = st.text_input("メール")
                p1 = st.text_input("パスワード", type="password")
                p2 = st.text_input("確認", type="password")
                ok = st.form_submit_button("登録")
            if ok:
                if p1 != p2:
                    st.warning("パスワードが一致しません")
                else:
                    ok, err = signup(n, e, p1)
                    if ok:
                        st.success("登録完了")
                    else:
                        st.error(err)
        else:
            st.info("ゲスト利用（投稿不可）")
    else:
        st.sidebar.write(f"👤 {st.session_state['user']['username']}")
        if st.sidebar.button("ログアウト"):
            st.session_state["user"] = None
            st.rerun()
