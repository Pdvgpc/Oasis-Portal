import base64
import json
from datetime import datetime
from io import StringIO
from typing import Optional

import pandas as pd
import requests
import streamlit as st
import yaml

st.set_page_config(page_title="Oasis Portal", layout="wide")

SEC = dict(st.secrets)
AUTH_YAML = "auth.yaml"


# ============================================================
# GitHub storage helpers
# ============================================================
def gh_headers():
    return {
        "Authorization": f"Bearer {SEC['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github+json",
    }


def gh_api(path: str) -> str:
    owner = SEC["GITHUB_OWNER"]
    repo = SEC["GITHUB_REPO"]
    return f"https://api.github.com/repos/{owner}/{repo}{path}"


def gh_get_text(path_in_repo: str) -> Optional[str]:
    url = gh_api(f"/contents/{path_in_repo}")

    try:
        r = requests.get(url, headers=gh_headers(), timeout=15)
    except Exception as e:
        st.error(f"GitHub connection failed: {e}")
        return ""

    if r.status_code == 200:
        data = r.json()
        return base64.b64decode(data["content"]).decode("utf-8", errors="ignore")

    if r.status_code == 404:
        return None

    st.error(f"GitHub read error {r.status_code}: {r.text[:300]}")
    return ""


def gh_put_text(path_in_repo: str, content_text: str, msg: str) -> bool:
    url = gh_api(f"/contents/{path_in_repo}")

    try:
        r = requests.get(url, headers=gh_headers(), timeout=15)
    except Exception as e:
        st.error(f"GitHub pre-write read failed: {e}")
        return False

    sha = r.json().get("sha") if r.status_code == 200 else None

    payload = {
        "message": msg,
        "content": base64.b64encode(content_text.encode("utf-8")).decode("ascii"),
        "branch": "main",
    }
    if sha:
        payload["sha"] = sha

    try:
        r2 = requests.put(url, headers=gh_headers(), data=json.dumps(payload), timeout=15)
    except Exception as e:
        st.error(f"GitHub write failed: {e}")
        return False

    if r2.status_code not in (200, 201):
        st.error(f"GitHub write error {r2.status_code}: {r2.text[:300]}")
        return False

    return True


def gh_get_csv(path_in_repo: str) -> Optional[pd.DataFrame]:
    txt = gh_get_text(path_in_repo)
    if txt is None:
        return None
    if not txt.strip():
        return pd.DataFrame()
    try:
        return pd.read_csv(StringIO(txt))
    except Exception:
        return pd.DataFrame()


def gh_put_csv(path_in_repo: str, df: pd.DataFrame, msg: str) -> bool:
    csv_txt = df.to_csv(index=False)
    return gh_put_text(path_in_repo, csv_txt, msg)


# ============================================================
# Repo paths
# ============================================================
def requests_path() -> str:
    repo_dir = SEC.get("DATA_DIR", "data")
    return f"{repo_dir}/requests.csv"


def orders_path() -> str:
    repo_dir = SEC.get("DATA_DIR", "data")
    return f"{repo_dir}/orders.csv"


def layout_path() -> str:
    repo_dir = SEC.get("DATA_DIR", "data")
    return f"{repo_dir}/layout_settings.json"


# ============================================================
# Auth
# ============================================================
def load_auth() -> dict:
    try:
        with open(AUTH_YAML, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        st.error("auth.yaml not found or invalid.")
        st.stop()


def login_panel():
    cfg = load_auth()
    users = cfg.get("credentials", {}).get("usernames", {})

    st.session_state.setdefault("user", None)

    if st.session_state["user"]:
        return st.session_state["user"]

    st.title("Oasis Portal")
    st.subheader("Login")

    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Login", type="primary"):
        rec = users.get(username)
        if rec and str(password) == str(rec.get("password_plain", "")):
            st.session_state["user"] = {
                "username": username,
                "name": rec.get("name", username),
            }
            st.success(f"Logged in as {st.session_state['user']['name']}")
            st.rerun()
        else:
            st.error("Invalid username or password")

    st.stop()


# ============================================================
# Data helpers
# ============================================================
def ensure_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    df = df.copy()
    for col in columns:
        if col not in df.columns:
            df[col] = ""
    return df[columns]


def normalize_requests(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["id", "article", "quantity", "week", "year", "note", "status", "created_at"]
    if df is None:
        df = pd.DataFrame(columns=cols)
    df = ensure_columns(df, cols)

    for col in ["id", "quantity", "week", "year"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def normalize_orders(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["id", "request_id", "article", "supplier", "quantity", "week", "year", "status", "created_at"]
    if df is None:
        df = pd.DataFrame(columns=cols)
    df = ensure_columns(df, cols)

    for col in ["id", "request_id", "quantity", "week", "year"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def load_requests() -> pd.DataFrame:
    df = gh_get_csv(requests_path())
    if df is None:
        df = pd.DataFrame(columns=["id", "article", "quantity", "week", "year", "note", "status", "created_at"])
    return normalize_requests(df)


def load_orders() -> pd.DataFrame:
    df = gh_get_csv(orders_path())
    if df is None:
        df = pd.DataFrame(columns=["id", "request_id", "article", "supplier", "quantity", "week", "year", "status", "created_at"])
    return normalize_orders(df)


def save_requests(df: pd.DataFrame) -> bool:
    return gh_put_csv(requests_path(), normalize_requests(df), "update requests.csv")


def save_orders(df: pd.DataFrame) -> bool:
    return gh_put_csv(orders_path(), normalize_orders(df), "update orders.csv")


def next_id(df: pd.DataFrame) -> int:
    if df.empty or "id" not in df.columns:
        return 1
    try:
        return int(pd.to_numeric(df["id"], errors="coerce").fillna(0).max()) + 1
    except Exception:
        return 1


# ============================================================
# Layout settings
# ============================================================
def load_layout_settings() -> dict:
    txt = gh_get_text(layout_path())
    if not txt:
        return {}
    try:
        data = json.loads(txt)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_layout_settings(data: dict) -> bool:
    content = json.dumps(data, indent=2, sort_keys=True)
    return gh_put_text(layout_path(), content, "update layout_settings.json")


def get_user_layout(username: str, section: str, default_columns: list[str]) -> dict:
    data = load_layout_settings()
    section_data = data.get(username, {}).get(section, {})

    visible_columns = section_data.get("visible_columns", default_columns)
    visible_columns = [c for c in visible_columns if c in default_columns]

    if not visible_columns:
        visible_columns = default_columns

    return {
        "visible_columns": visible_columns
    }


def save_user_layout(username: str, section: str, visible_columns: list[str], default_columns: list[str]) -> bool:
    visible_columns = [c for c in visible_columns if c in default_columns]
    if not visible_columns:
        visible_columns = default_columns

    data = load_layout_settings()
    data.setdefault(username, {})
    data[username][section] = {
        "visible_columns": visible_columns
    }
    return save_layout_settings(data)


def apply_layout(df: pd.DataFrame, username: str, section: str, default_columns: list[str]) -> pd.DataFrame:
    layout = get_user_layout(username, section, default_columns)
    visible_cols = [c for c in default_columns if c in layout["visible_columns"] and c in df.columns]

    if not visible_cols:
        visible_cols = [c for c in default_columns if c in df.columns]

    return df[visible_cols].copy()


# ============================================================
# Init
# ============================================================
user = login_panel()
requests_df = load_requests()
orders_df = load_orders()

st.sidebar.success(f"Logged in as {user['name']}")

if st.sidebar.button("Logout"):
    st.session_state["user"] = None
    st.rerun()

st.title("Oasis Portal")

tab_requests, tab_orders = st.tabs(["Requests", "Orders"])


# ============================================================
# Requests tab
# ============================================================
with tab_requests:
    st.subheader("New Request")

    with st.form("new_request_form", clear_on_submit=True):
        article = st.text_input("Article")
        quantity = st.number_input("Quantity", min_value=1, step=1, value=1)
        week = st.number_input("Week", min_value=1, max_value=53, step=1, value=1)
        year = st.number_input("Year", min_value=2025, max_value=2100, step=1, value=datetime.now().year)
        note = st.text_input("Note")

        submit_request = st.form_submit_button("Add Request")

    if submit_request:
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
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }

            new_requests_df = pd.concat([requests_df, pd.DataFrame([new_row])], ignore_index=True)

            if save_requests(new_requests_df):
                st.success("Request added.")
                st.rerun()
            else:
                st.error("Request could not be saved to GitHub.")

    st.markdown("---")

    request_display_cols = ["Request ID", "Article", "Quantity", "Week", "Year", "Note", "Status", "Created At"]
    current_req_layout = get_user_layout(user["username"], "requests", request_display_cols)

    st.subheader("Columns")
    req_visible_cols = st.multiselect(
        "Select visible columns",
        options=request_display_cols,
        default=current_req_layout["visible_columns"],
        key="req_visible_cols",
    )

    if st.button("Save Columns", key="save_request_columns"):
        ok = save_user_layout(
            user["username"],
            "requests",
            req_visible_cols,
            request_display_cols
        )
        if ok:
            st.success("Request columns saved.")
            st.rerun()
        else:
            st.error("Failed to save request columns.")

    st.markdown("---")
    st.subheader("Request List")

    if requests_df.empty:
        st.info("No requests yet.")
    else:
        requests_view = requests_df.copy()
        requests_view = requests_view.rename(columns={
            "id": "Request ID",
            "article": "Article",
            "quantity": "Quantity",
            "week": "Week",
            "year": "Year",
            "note": "Note",
            "status": "Status",
            "created_at": "Created At",
        })

        requests_view = apply_layout(requests_view, user["username"], "requests", request_display_cols)
        st.dataframe(requests_view, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("Create Order from Request")

    open_requests = requests_df[requests_df["status"].astype(str) != "Converted"].copy()

    if open_requests.empty:
        st.info("No open requests available.")
    else:
        open_requests["label"] = open_requests.apply(
            lambda r: f"#{int(r['id'])} | {str(r['article'])} | Qty {int(r['quantity']) if pd.notna(r['quantity']) else 0} | Week {int(r['week']) if pd.notna(r['week']) else 0}",
            axis=1,
        )

        labels = open_requests["label"].tolist()
        id_by_label = dict(zip(open_requests["label"], open_requests["id"]))

        selected_label = st.selectbox("Select request", options=labels)
        selected_id = int(id_by_label[selected_label])
        selected_row = open_requests.loc[pd.to_numeric(open_requests["id"], errors="coerce") == selected_id].iloc[0]

        with st.form("create_order_form"):
            new_article = st.text_input("Article", value=str(selected_row["article"]))
            new_supplier = st.text_input("Supplier", value="")
            new_qty = st.number_input(
                "Quantity",
                min_value=1,
                step=1,
                value=int(selected_row["quantity"]) if pd.notna(selected_row["quantity"]) else 1,
            )
            new_week = st.number_input(
                "Week",
                min_value=1,
                max_value=53,
                step=1,
                value=int(selected_row["week"]) if pd.notna(selected_row["week"]) else 1,
            )

            confirm_order = st.form_submit_button("Create Order")

        if confirm_order:
            if not new_article.strip():
                st.error("Article is required.")
            else:
                new_order = {
                    "id": next_id(orders_df),
                    "request_id": int(selected_row["id"]),
                    "article": new_article.strip(),
                    "supplier": new_supplier.strip(),
                    "quantity": int(new_qty),
                    "week": int(new_week),
                    "year": int(selected_row["year"]) if pd.notna(selected_row["year"]) else datetime.now().year,
                    "status": "Open",
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                }

                new_orders_df = pd.concat([orders_df, pd.DataFrame([new_order])], ignore_index=True)
                new_requests_df = requests_df.copy()
                new_requests_df.loc[
                    pd.to_numeric(new_requests_df["id"], errors="coerce") == int(selected_row["id"]),
                    "status"
                ] = "Converted"

                ok_orders = save_orders(new_orders_df)
                ok_requests = save_requests(new_requests_df)

                if ok_orders and ok_requests:
                    st.success("Order created.")
                    st.rerun()
                else:
                    st.error("Order could not be saved to GitHub.")


# ============================================================
# Orders tab
# ============================================================
with tab_orders:
    order_display_cols = ["Order ID", "Request ID", "Article", "Supplier", "Quantity", "Week", "Year", "Status", "Created At"]
    current_ord_layout = get_user_layout(user["username"], "orders", order_display_cols)

    st.subheader("Columns")
    ord_visible_cols = st.multiselect(
        "Select visible columns",
        options=order_display_cols,
        default=current_ord_layout["visible_columns"],
        key="ord_visible_cols",
    )

    if st.button("Save Columns", key="save_order_columns"):
        ok = save_user_layout(
            user["username"],
            "orders",
            ord_visible_cols,
            order_display_cols
        )
        if ok:
            st.success("Order columns saved.")
            st.rerun()
        else:
            st.error("Failed to save order columns.")

    st.markdown("---")
    st.subheader("Orders")

    if orders_df.empty:
        st.info("No orders yet.")
    else:
        orders_view = orders_df.copy()
        orders_view = orders_view.rename(columns={
            "id": "Order ID",
            "request_id": "Request ID",
            "article": "Article",
            "supplier": "Supplier",
            "quantity": "Quantity",
            "week": "Week",
            "year": "Year",
            "status": "Status",
            "created_at": "Created At",
        })

        orders_view = apply_layout(orders_view, user["username"], "orders", order_display_cols)
        st.dataframe(orders_view, use_container_width=True, hide_index=True)
