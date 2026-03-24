import os
from datetime import datetime
import pandas as pd
import streamlit as st
import yaml

st.set_page_config(page_title="Oasis Portal", layout="wide")

REQUESTS_FILE = "data/requests.csv"
ORDERS_FILE = "data/orders.csv"
AUTH_YAML = "auth.yaml"


def ensure_data_files():
    os.makedirs("data", exist_ok=True)

    if not os.path.exists(REQUESTS_FILE):
        pd.DataFrame(columns=[
            "id", "article", "quantity", "week", "year",
            "note", "status", "created_at"
        ]).to_csv(REQUESTS_FILE, index=False)

    if not os.path.exists(ORDERS_FILE):
        pd.DataFrame(columns=[
            "id", "request_id", "article", "quantity", "week",
            "year", "status", "created_at"
        ]).to_csv(ORDERS_FILE, index=False)


def load_csv(path):
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def save_csv(path, df):
    df.to_csv(path, index=False)


def next_id(df):
    if df.empty or "id" not in df.columns:
        return 1
    try:
        return int(pd.to_numeric(df["id"], errors="coerce").fillna(0).max()) + 1
    except Exception:
        return 1


def load_auth():
    if not os.path.exists(AUTH_YAML):
        st.error("auth.yaml niet gevonden.")
        st.stop()

    try:
        with open(AUTH_YAML, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        st.error(f"Kon auth.yaml niet lezen: {e}")
        st.stop()


def login_panel():
    cfg = load_auth()
    users = cfg.get("credentials", {}).get("usernames", {})

    st.session_state.setdefault("auth_user", None)

    if st.session_state["auth_user"]:
        return st.session_state["auth_user"]

    st.title("Oasis Portal")
    st.subheader("🔐 Inloggen")

    username = st.text_input("Gebruikersnaam")
    password = st.text_input("Wachtwoord", type="password")

    if st.button("Inloggen", type="primary"):
        rec = users.get(username)

        if rec and str(password) == str(rec.get("password_plain", "")):
            st.session_state["auth_user"] = {
                "username": username,
                "name": rec.get("name", username),
                "email": rec.get("email", "")
            }
            st.success(f"Ingelogd als {st.session_state['auth_user']['name']}")
            st.rerun()
        else:
            st.error("Ongeldige gebruikersnaam of wachtwoord")

    st.stop()


ensure_data_files()

user = login_panel()

requests_df = load_csv(REQUESTS_FILE)
orders_df = load_csv(ORDERS_FILE)

st.sidebar.success(f"👤 Ingelogd als {user['name']}")

if st.sidebar.button("Uitloggen"):
    st.session_state["auth_user"] = None
    st.rerun()

st.title("Oasis Portal")

tab1, tab2 = st.tabs(["Requests", "Orders"])

with tab1:
    st.subheader("New Request")

    with st.form("new_request", clear_on_submit=True):
        article = st.text_input("Article")
        quantity = st.number_input("Quantity", min_value=1, value=1)
        week = st.number_input("Week", min_value=1, max_value=53, value=1)
        year = st.number_input("Year", min_value=2025, max_value=2100, value=datetime.now().year)
        note = st.text_input("Note")

        submit = st.form_submit_button("Add Request")

    if submit:
        if not article.strip():
            st.error("Article is verplicht.")
        else:
            new_row = {
                "id": next_id(requests_df),
                "article": article.strip(),
                "quantity": int(quantity),
                "week": int(week),
                "year": int(year),
                "note": note.strip(),
                "status": "New",
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }

            requests_df = pd.concat([requests_df, pd.DataFrame([new_row])], ignore_index=True)
            save_csv(REQUESTS_FILE, requests_df)
            st.success("Request toegevoegd.")
            st.rerun()

    st.markdown("---")
    st.subheader("Request List")

    if requests_df.empty:
        st.info("Nog geen requests.")
    else:
        for _, row in requests_df.iterrows():
            st.write(
                f"**{row['article']}** | Qty: {row['quantity']} | Week: {row['week']} | Status: {row['status']}"
            )

            if str(row["status"]) != "Converted":
                with st.form(f"convert_{row['id']}"):
                    new_article = st.text_input("Article", value=str(row["article"]), key=f"a{row['id']}")
                    new_qty = st.number_input("Qty", min_value=1, value=int(row["quantity"]), key=f"q{row['id']}")
                    new_week = st.number_input("Week", min_value=1, max_value=53, value=int(row["week"]), key=f"w{row['id']}")

                    convert = st.form_submit_button("Create Order")

                    if convert:
                        new_order = {
                            "id": next_id(orders_df),
                            "request_id": row["id"],
                            "article": new_article.strip(),
                            "quantity": int(new_qty),
                            "week": int(new_week),
                            "year": row["year"],
                            "status": "Open",
                            "created_at": datetime.now().isoformat(timespec="seconds"),
                        }

                        orders_df = pd.concat([orders_df, pd.DataFrame([new_order])], ignore_index=True)
                        requests_df.loc[requests_df["id"] == row["id"], "status"] = "Converted"

                        save_csv(REQUESTS_FILE, requests_df)
                        save_csv(ORDERS_FILE, orders_df)

                        st.success("Order aangemaakt.")
                        st.rerun()

with tab2:
    st.subheader("Orders")

    if orders_df.empty:
        st.info("Nog geen orders.")
    else:
        st.dataframe(orders_df, use_container_width=True)
