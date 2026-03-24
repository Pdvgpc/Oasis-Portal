import os
from datetime import datetime
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Oasis Portal", layout="wide")

REQUESTS_FILE = "data/requests.csv"
ORDERS_FILE = "data/orders.csv"


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
    return pd.read_csv(path)


def save_csv(path, df):
    df.to_csv(path, index=False)


def next_id(df):
    if df.empty:
        return 1
    return int(df["id"].max()) + 1


ensure_data_files()

requests_df = load_csv(REQUESTS_FILE)
orders_df = load_csv(ORDERS_FILE)

st.title("Oasis Portal")

tab1, tab2 = st.tabs(["Requests", "Orders"])


# ---------------- REQUESTS ----------------
with tab1:
    st.subheader("New Request")

    with st.form("new_request"):
        article = st.text_input("Article")
        quantity = st.number_input("Quantity", min_value=1, value=1)
        week = st.number_input("Week", min_value=1, max_value=53, value=1)
        year = st.number_input("Year", value=datetime.now().year)
        note = st.text_input("Note")

        submit = st.form_submit_button("Add Request")

    if submit:
        new_row = {
            "id": next_id(requests_df),
            "article": article,
            "quantity": quantity,
            "week": week,
            "year": year,
            "note": note,
            "status": "New",
            "created_at": datetime.now()
        }

        requests_df = pd.concat([requests_df, pd.DataFrame([new_row])], ignore_index=True)
        save_csv(REQUESTS_FILE, requests_df)
        st.rerun()

    st.markdown("---")
    st.subheader("Request List")

    for _, row in requests_df.iterrows():
        st.write(f"**{row['article']}** | Qty: {row['quantity']} | Week: {row['week']} | Status: {row['status']}")

        if row["status"] != "Converted":

            with st.form(f"convert_{row['id']}"):
                new_qty = st.number_input("Qty", value=int(row["quantity"]), key=f"q{row['id']}")
                new_week = st.number_input("Week", value=int(row["week"]), key=f"w{row['id']}")

                convert = st.form_submit_button("Create Order")

                if convert:
                    new_order = {
                        "id": next_id(orders_df),
                        "request_id": row["id"],
                        "article": row["article"],
                        "quantity": new_qty,
                        "week": new_week,
                        "year": row["year"],
                        "status": "Open",
                        "created_at": datetime.now()
                    }

                    orders_df = pd.concat([orders_df, pd.DataFrame([new_order])], ignore_index=True)

                    requests_df.loc[requests_df["id"] == row["id"], "status"] = "Converted"

                    save_csv(REQUESTS_FILE, requests_df)
                    save_csv(ORDERS_FILE, orders_df)

                    st.rerun()


# ---------------- ORDERS ----------------
with tab2:
    st.subheader("Orders")
    st.dataframe(orders_df)
