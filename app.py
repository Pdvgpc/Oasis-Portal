import base64
import json
from datetime import datetime
from io import BytesIO, StringIO
from typing import Optional

import pandas as pd
import requests
import streamlit as st
import yaml

st.set_page_config(page_title="Oasis Portal", layout="wide")

SEC = dict(st.secrets)
AUTH_YAML = "auth.yaml"


# ============================================================
# GitHub helpers
# ============================================================
def gh_headers():
    return {
        "Authorization": f"Bearer {SEC['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github+json",
    }


def gh_api(path: str) -> str:
    return f"https://api.github.com/repos/{SEC['GITHUB_OWNER']}/{SEC['GITHUB_REPO']}{path}"


def gh_get_text(path):
    r = requests.get(gh_api(f"/contents/{path}"), headers=gh_headers())
    if r.status_code == 200:
        return base64.b64decode(r.json()["content"]).decode()
    if r.status_code == 404:
        return None
    return ""


def gh_put_csv(path, df, msg):
    url = gh_api(f"/contents/{path}")
    r = requests.get(url, headers=gh_headers())
    sha = r.json().get("sha") if r.status_code == 200 else None

    payload = {
        "message": msg,
        "content": base64.b64encode(df.to_csv(index=False).encode()).decode(),
        "branch": "main",
    }
    if sha:
        payload["sha"] = sha

    requests.put(url, headers=gh_headers(), data=json.dumps(payload))


def gh_get_csv(path):
    txt = gh_get_text(path)
    if txt is None or not txt.strip():
        return pd.DataFrame()
    return pd.read_csv(StringIO(txt))


# ============================================================
# Paths
# ============================================================
DATA_DIR = SEC.get("DATA_DIR", "data")

REQ = f"{DATA_DIR}/requests.csv"
ORD = f"{DATA_DIR}/orders.csv"
REJ = f"{DATA_DIR}/rejected_orders.csv"


# ============================================================
# Auth
# ============================================================
def load_auth():
    with open(AUTH_YAML) as f:
        return yaml.safe_load(f)


def login():
    users = load_auth()["credentials"]["usernames"]

    if "user" in st.session_state:
        return st.session_state["user"]

    st.title("Oasis Portal")

    u = st.text_input("Username")
    p = st.text_input("Password", type="password")

    if st.button("Login"):
        if u in users and users[u]["password_plain"] == p:
            st.session_state["user"] = u
            st.rerun()
        else:
            st.error("Wrong login")

    st.stop()


# ============================================================
# Helpers
# ============================================================
def next_id(df):
    return int(df["id"].max()) + 1 if not df.empty else 1


def excel_bytes(df):
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False)
    buf.seek(0)
    return buf


# ============================================================
# Init
# ============================================================
user = login()

if "req" not in st.session_state:
    st.session_state.req = gh_get_csv(REQ)
if "ord" not in st.session_state:
    st.session_state.ord = gh_get_csv(ORD)
if "rej" not in st.session_state:
    st.session_state.rej = gh_get_csv(REJ)

req = st.session_state.req
ord = st.session_state.ord
rej = st.session_state.rej


# ============================================================
# Sidebar
# ============================================================
st.sidebar.success(f"Logged in as {user}")

if st.sidebar.button("Logout"):
    st.session_state.clear()
    st.rerun()

st.sidebar.markdown("---")

st.session_state.setdefault("mobile", False)
st.session_state.mobile = st.sidebar.checkbox("📱 Mobile mode", value=st.session_state.mobile)

if st.session_state.mobile:
    st.markdown(
        """<style>
        .block-container {max-width:700px;}
        </style>""",
        unsafe_allow_html=True,
    )


# ============================================================
# UI
# ============================================================
st.title("Oasis Portal")

t1, t2, t3 = st.tabs(["Requests", "Orders", "Rejected"])


# ============================================================
# REQUESTS
# ============================================================
with t1:
    st.subheader("New Request")

    with st.form("req"):
        a = st.text_input("Article")
        q = st.number_input("Quantity", 1, 999, 1)
        w = st.number_input("Week", 1, 53, 1)
        y = st.number_input("Year", 2025, 2100, datetime.now().year)
        n = st.text_input("Note")

        if st.form_submit_button("Add", use_container_width=True):
            if not a:
                st.error("Article needed")
            else:
                new = pd.DataFrame([{
                    "id": next_id(req),
                    "article": a,
                    "quantity": q,
                    "week": w,
                    "year": y,
                    "note": n,
                    "created_at": datetime.now()
                }])
                req = pd.concat([req, new])
                gh_put_csv(REQ, req, "update")
                st.session_state.req = req
                st.rerun()

    st.markdown("---")

    if not req.empty:
        sel = st.selectbox(
            "Select request",
            req["id"].astype(str) + " | " + req["article"]
        )

        row = req[req["id"] == int(sel.split("|")[0])].iloc[0]

        with st.form("convert"):
            art = st.text_input("Article", row["article"])
            sup = st.text_input("Supplier")
            qty = st.number_input("Quantity", 1, 999, int(row["quantity"]))
            wk = st.number_input("Week", 1, 53, int(row["week"]))

            c1, c2 = st.columns(2)

            with c1:
                create = st.form_submit_button("Create Order", use_container_width=True)
            with c2:
                reject = st.form_submit_button("Reject", use_container_width=True)

        if create:
            new_order = pd.DataFrame([{
                "id": next_id(ord),
                "request_id": row["id"],
                "article": art,
                "supplier": sup,
                "quantity": qty,
                "week": wk,
                "year": row["year"],
                "created_at": datetime.now()
            }])

            ord = pd.concat([ord, new_order])
            req = req[req["id"] != row["id"]]

            gh_put_csv(ORD, ord, "update")
            gh_put_csv(REQ, req, "update")

            st.session_state.ord = ord
            st.session_state.req = req
            st.rerun()

        if reject:
            new_rej = pd.DataFrame([{
                "id": next_id(rej),
                "request_id": row["id"],
                "article": row["article"],
                "quantity": row["quantity"],
                "week": row["week"],
                "year": row["year"],
                "note": row["note"],
                "rejected_at": datetime.now()
            }])

            rej = pd.concat([rej, new_rej])
            req = req[req["id"] != row["id"]]

            gh_put_csv(REJ, rej, "update")
            gh_put_csv(REQ, req, "update")

            st.session_state.rej = rej
            st.session_state.req = req
            st.rerun()


# ============================================================
# ORDERS
# ============================================================
with t2:
    st.subheader("Orders")

    if not ord.empty:
        df = ord.copy()
        df.insert(0, "Select", False)

        edited = st.data_editor(df, use_container_width=True)

        ids = edited.loc[edited["Select"], "id"].tolist()

        if st.button("Delete selected", use_container_width=True):
            ord = ord[~ord["id"].isin(ids)]
            gh_put_csv(ORD, ord, "update")
            st.session_state.ord = ord
            st.rerun()

        st.download_button(
            "Export Excel",
            data=excel_bytes(ord),
            file_name="orders.xlsx",
            use_container_width=True
        )


# ============================================================
# REJECTED
# ============================================================
with t3:
    st.subheader("Rejected")

    if not rej.empty:
        df = rej.copy()
        df.insert(0, "Select", False)

        edited = st.data_editor(df, use_container_width=True)

        ids = edited.loc[edited["Select"], "id"].tolist()

        if st.button("Delete rejected", use_container_width=True):
            rej = rej[~rej["id"].isin(ids)]
            gh_put_csv(REJ, rej, "update")
            st.session_state.rej = rej
            st.rerun()
