import os
from datetime import datetime
import pandas as pd
import streamlit as st
import yaml

st.set_page_config(page_title="Oasis Portal", layout="wide")

REQUESTS_FILE = "data/requests.csv"
ORDERS_FILE = "data/orders.csv"
AUTH_YAML = "auth.yaml"


# ---------------- DATA ----------------
def ensure_data_files():
    os.makedirs("data", exist_ok=True)

    if not os.path.exists(REQUESTS_FILE):
        pd.DataFrame(columns=[
            "id", "article", "quantity", "week", "year",
            "note", "status", "created_at"
        ]).to_csv(REQUESTS_FILE, index=False)

    if not os.path.exists(ORDERS_FILE):
        pd.DataFrame(columns=[
            "id", "request_id", "article", "supplier", "quantity", "week",
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


def ensure_orders_columns(df):
    df = df.copy()
    required_cols = [
        "id", "request_id", "article", "supplier", "quantity",
        "week", "year", "status", "created_at"
    ]
    for col in required_cols:
        if col not in df.columns:
            df[col] = ""
    return df[required_cols]


# ---------------- AUTH ----------------
def load_auth():
    if not os.path.exists(AUTH_YAML):
        st.error("auth.yaml not found.")
        st.stop()

    with open(AUTH_YAML, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def login():
    cfg = load_auth()
    users = cfg.get("credentials", {}).get("usernames", {})

    st.session_state.setdefault("user", None)

    if st.session_state["user"]:
        return st.session_state["user"]

    st.title("Oasis Portal")
    st.subheader("🔐 Login")

    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Login"):
        user = users.get(username)

        if user and password == user.get("password_plain", ""):
            st.session_state["user"] = {
                "username": username,
                "name": user.get("name", username)
            }
            st.success(f"Logged in as {user.get('name', username)}")
            st.rerun()
        else:
            st.error("Invalid username or password")

    st.stop()


# ---------------- INIT ----------------
ensure_data_files()
user = login()

requests_df = load_csv(REQUESTS_FILE)
orders_df = ensure_orders_columns(load_csv(ORDERS_FILE))

st.sidebar.success(f"👤 Logged in as {user['name']}")

if st.sidebar.button("Logout"):
    st.session_state["user"] = None
    st.rerun()

st.title("Oasis Portal")

tab1, tab2 = st.tabs(["Requests", "Orders"])


# ---------------- REQUESTS ----------------
with tab1:
    st.subheader("New Request")

    with st.form("new_request", clear_on_submit=True):
        article = st.text_input("Article")
        quantity = st.number_input("Quantity", min_value=1, value=1)
        week = st.number_input("Week", min_value=1, max_value=53, value=1)
        year = st.number_input("Year", value=datetime.now().year)
        note = st.text_input("Note")

        submit = st.form_submit_button("Add Request")

    if submit:
        if not article.strip():
            st.error("Article is required.")
        else:
            new_row = {
                "id": next_id(requests_df),
                "article": article.strip(),
                "quantity": int(quantity),
                "week": int(week),
                "year": int(year),
                "note": note.strip(),
                "status": "New",
                "created_at": datetime.now().isoformat(timespec="seconds")
            }

            requests_df = pd.concat([requests_df, pd.DataFrame([new_row])], ignore_index=True)
            save_csv(REQUESTS_FILE, requests_df)

            st.success("Request added.")
            st.rerun()

    st.markdown("---")
    st.subheader("Request List")

    if requests_df.empty:
        st.info("No requests yet.")
    else:
        for _, row in requests_df.iterrows():
            st.write(
                f"**{row['article']}** | Qty: {row['quantity']} | Week: {row['week']} | Status: {row['status']}"
            )

            if str(row["status"]) != "Converted":
                if st.button("Create Order", key=f"btn_{row['id']}"):
                    st.session_state["selected_request"] = row.to_dict()

    if "selected_request" in st.session_state:
        r = st.session_state["selected_request"]

        st.markdown("### Create Order")

        with st.form("order_form"):
            new_article = st.text_input("Article", value=str(r["article"]))
            new_supplier = st.text_input("Supplier", value="")
            new_qty = st.number_input("Quantity", min_value=1, value=int(r["quantity"]))
            new_week = st.number_input("Week", min_value=1, max_value=53, value=int(r["week"]))

            confirm = st.form_submit_button("Confirm Order")

            if confirm:
                new_order = {
                    "id": next_id(orders_df),
                    "request_id": r["id"],
                    "article": new_article.strip(),
                    "supplier": new_supplier.strip(),
                    "quantity": int(new_qty),
                    "week": int(new_week),
                    "year": int(r["year"]),
                    "status": "Open",
                    "created_at": datetime.now().isoformat(timespec="seconds")
                }

                orders_df = pd.concat([orders_df, pd.DataFrame([new_order])], ignore_index=True)
                orders_df = ensure_orders_columns(orders_df)

                requests_df.loc[requests_df["id"] == r["id"], "status"] = "Converted"

                save_csv(REQUESTS_FILE, requests_df)
                save_csv(ORDERS_FILE, orders_df)

                del st.session_state["selected_request"]

                st.success("Order created.")
                st.rerun()


# ---------------- ORDERS ----------------
with tab2:
    st.subheader("Orders")

    if orders_df.empty:
        st.info("No orders yet.")
    else:
        orders_view = orders_df[[
            "id", "request_id", "article", "supplier",
            "quantity", "week", "year", "status", "created_at"
        ]].copy()

        orders_view = orders_view.rename(columns={
            "id": "Order ID",
            "request_id": "Request ID",
            "article": "Article",
            "supplier": "Supplier",
            "quantity": "Quantity",
            "week": "Week",
            "year": "Year",
            "status": "Status",
            "created_at": "Created At"
        })

        st.dataframe(orders_view, use_container_width=True, hide_index=True)
