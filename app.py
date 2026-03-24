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


# ------------------------------------------------------------
# GitHub storage helpers
# ------------------------------------------------------------
def _gh_headers():
    return {
        "Authorization": f"Bearer {SEC['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github+json",
    }


def _gh_api(path: str) -> str:
    owner = SEC["GITHUB_OWNER"]
    repo = SEC["GITHUB_REPO"]
    return f"https://api.github.com/repos/{owner}/{repo}{path}"


def _gh_get_text(path_in_repo: str) -> Optional[str]:
    url = _gh_api(f"/contents/{path_in_repo}")
    try:
        r = requests.get(url, headers=_gh_headers(), timeout=15)
    except Exception as e:
        st.error(f"GitHub connection failed: {e}")
        return ""

    if r.status_code == 200:
        data = r.json()
        return base64.b64decode(data["content"]).decode("utf-8", errors="ignore")
    if r.status_code == 404:
        return None

    st.error(f"GitHub read error {r.status_code}: {r.text[:200]}")
    return ""


def _gh_put_text(path_in_repo: str, content_text: str, msg: str):
    url = _gh_api(f"/contents/{path_in_repo}")

    try:
        r = requests.get(url, headers=_gh_headers(), timeout=15)
    except Exception as e:
        st.error(f"GitHub pre-write read failed: {e}")
        return

    sha = r.json().get("sha") if r.status_code == 200 else None

    payload = {
        "message": msg,
        "content": base64.b64encode(content_text.encode("utf-8")).decode("ascii"),
        "branch": "main",
    }
    if sha:
        payload["sha"] = sha

    try:
        r2 = requests.put(url, headers=_gh_headers(), data=json.dumps(payload), timeout=15)
    except Exception as e:
        st.error(f"GitHub write failed: {e}")
        return

    if r2.status_code not in (200, 201):
        st.error(f"GitHub write error {r2.status_code}: {r2.text[:200]}")


def _gh_get_csv(path_in_repo: str) -> Optional[pd.DataFrame]:
    txt = _gh_get_text(path_in_repo)
    if txt is None:
        return None
    if not txt.strip():
        return pd.DataFrame()
    try:
        return pd.read_csv(StringIO(txt))
    except Exception:
        return pd.DataFrame()


def _gh_put_csv(path_in_repo: str, df: pd.DataFrame, msg: str):
    csv_txt = df.to_csv(index=False)
    _gh_put_text(path_in_repo, csv_txt, msg)


# ------------------------------------------------------------
# Paths
# ------------------------------------------------------------
def requests_path() -> str:
    repo_dir = SEC.get("DATA_DIR", "data")
    return f"{repo_dir}/requests.csv"


def orders_path() -> str:
    repo_dir = SEC.get("DATA_DIR", "data")
    return f"{repo_dir}/orders.csv"


def layout_path() -> str:
    repo_dir = SEC.get("DATA_DIR", "data")
    return f"{repo_dir}/layout_settings.json"


# ------------------------------------------------------------
# Auth
# ------------------------------------------------------------
def load_auth():
    try:
        with open(AUTH_YAML, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        st.error("auth.yaml not found or invalid.")
        st.stop()


def login():
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


# ------------------------------------------------------------
# Data helpers
# ------------------------------------------------------------
def ensure_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    df = df.copy()
    for col in columns:
        if col not in df.columns:
            df[col] = ""
    return df[columns]


def load_requests() -> pd.DataFrame:
    df = _gh_get_csv(requests_path())
    if df is None:
        df = pd.DataFrame(columns=[
            "id", "article", "quantity", "week", "year",
            "note", "status", "created_at"
        ])
    df = ensure_columns(df, [
        "id", "article", "quantity", "week", "year",
        "note", "status", "created_at"
    ])
    return df


def load_orders() -> pd.DataFrame:
    df = _gh_get_csv(orders_path())
    if df is None:
        df = pd.DataFrame(columns=[
            "id", "request_id", "article", "supplier", "quantity",
            "week", "year", "status", "created_at"
        ])
    df = ensure_columns(df, [
        "id", "request_id", "article", "supplier", "quantity",
        "week", "year", "status", "created_at"
    ])
    return df


def save_requests(df: pd.DataFrame):
    _gh_put_csv(requests_path(), df, "update requests.csv")


def save_orders(df: pd.DataFrame):
    _gh_put_csv(orders_path(), df, "update orders.csv")


def next_id(df: pd.DataFrame) -> int:
    if df.empty or "id" not in df.columns:
        return 1
    try:
        return int(pd.to_numeric(df["id"], errors="coerce").fillna(0).max()) + 1
    except Exception:
        return 1


# ------------------------------------------------------------
# Layout settings (saved per user in GitHub)
# ------------------------------------------------------------
def load_layout_settings() -> dict:
    txt = _gh_get_text(layout_path())
    if not txt:
        return {}
    try:
        data = json.loads(txt)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_layout_settings(data: dict):
    content = json.dumps(data, indent=2, sort_keys=True)
    _gh_put_text(layout_path(), content, "update layout_settings.json")


def get_user_layout(username: str, section: str, default_columns: list[str]) -> dict:
    data = load_layout_settings()
    user_data = data.get(username, {})
    section_data = user_data.get(section, {})

    visible = section_data.get("visible_columns", default_columns)
    order = section_data.get("column_order", default_columns)

    visible = [c for c in visible if c in default_columns]
    order = [c for c in order if c in default_columns]

    for col in default_columns:
        if col not in order:
            order.append(col)
        if col not in visible:
            pass

    return {
        "visible_columns": visible if visible else default_columns,
        "column_order": order,
    }


def save_user_layout(username: str, section: str, visible_columns: list[str], column_order: list[str]):
    data = load_layout_settings()
    data.setdefault(username, {})
    data[username][section] = {
        "visible_columns": visible_columns,
        "column_order": column_order,
    }
    save_layout_settings(data)


def apply_layout(df: pd.DataFrame, username: str, section: str, default_columns: list[str]) -> pd.DataFrame:
    layout = get_user_layout(username, section, default_columns)
    ordered = [c for c in layout["column_order"] if c in df.columns]
    visible = [c for c in ordered if c in layout["visible_columns"]]
    if not visible:
        visible = [c for c in default_columns if c in df.columns]
    return df[visible].copy()


# ------------------------------------------------------------
# Init
# ------------------------------------------------------------
user = login()
requests_df = load_requests()
orders_df = load_orders()

st.sidebar.success(f"Logged in as {user['name']}")

if st.sidebar.button("Logout"):
    st.session_state["user"] = None
    st.rerun()

st.title("Oasis Portal")

tab_requests, tab_orders = st.tabs(["Requests", "Orders"])


# ------------------------------------------------------------
# Requests tab
# ------------------------------------------------------------
with tab_requests:
    st.subheader("New Request")

    with st.form("new_request_form", clear_on_submit=True):
        article = st.text_input("Article")
        quantity = st.number_input("Quantity", min_value=1, step=1, value=1)
        week = st.number_input("Week", min_value=1, max_value=53, step=1, value=1)
        year = st.number_input("Year", min_value=2025, max_value=2100, value=datetime.now().year)
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
            requests_df = pd.concat([requests_df, pd.DataFrame([new_row])], ignore_index=True)
            save_requests(requests_df)
            st.success("Request added.")
            st.rerun()

    st.markdown("---")
    st.subheader("Request List")

    request_default_cols = ["id", "article", "quantity", "week", "year", "note", "status", "created_at"]

    with st.expander("Request Layout Settings"):
        current_layout = get_user_layout(user["username"], "requests", request_default_cols)

        visible_cols = st.multiselect(
            "Visible columns",
            options=request_default_cols,
            default=current_layout["visible_columns"],
            key="req_visible_cols",
        )

        layout_editor_df = pd.DataFrame({
            "Column": request_default_cols,
            "Position": [current_layout["column_order"].index(c) + 1 for c in request_default_cols],
        })

        edited_layout = st.data_editor(
            layout_editor_df,
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            column_config={
                "Column": st.column_config.TextColumn(disabled=True),
                "Position": st.column_config.NumberColumn(min_value=1, max_value=len(request_default_cols), step=1),
            },
            key="req_layout_editor",
        )

        if st.button("Save Request Layout"):
            ordered_cols = edited_layout.sort_values("Position")["Column"].tolist()
            save_user_layout(user["username"], "requests", visible_cols, ordered_cols)
            st.success("Request layout saved.")
            st.rerun()

    requests_view = requests_df.copy()
    if not requests_view.empty:
        requests_view["id"] = pd.to_numeric(requests_view["id"], errors="coerce").astype("Int64")
        requests_view["quantity"] = pd.to_numeric(requests_view["quantity"], errors="coerce").astype("Int64")
        requests_view["week"] = pd.to_numeric(requests_view["week"], errors="coerce").astype("Int64")
        requests_view["year"] = pd.to_numeric(requests_view["year"], errors="coerce").astype("Int64")

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

        request_display_cols = ["Request ID", "Article", "Quantity", "Week", "Year", "Note", "Status", "Created At"]
        requests_view = apply_layout(requests_view, user["username"], "requests", request_display_cols)

        st.dataframe(requests_view, use_container_width=True, hide_index=True)
    else:
        st.info("No requests yet.")

    st.markdown("---")
    st.subheader("Create Order from Request")

    if requests_df.empty:
        st.info("No requests available.")
    else:
        open_requests = requests_df[requests_df["status"].astype(str) != "Converted"].copy()

        if open_requests.empty:
            st.info("All requests are already converted.")
        else:
            open_requests["label"] = open_requests.apply(
                lambda r: f"#{r['id']} | {r['article']} | Qty {r['quantity']} | Week {r['week']}",
                axis=1,
            )
            labels = open_requests["label"].tolist()
            id_by_label = dict(zip(open_requests["label"], open_requests["id"]))

            selected_label = st.selectbox("Select request", options=labels)
            selected_id = id_by_label[selected_label]
            selected_row = open_requests.loc[open_requests["id"] == selected_id].iloc[0]

            with st.form("create_order_form"):
                new_article = st.text_input("Article", value=str(selected_row["article"]))
                new_supplier = st.text_input("Supplier", value="")
                new_qty = st.number_input("Quantity", min_value=1, step=1, value=int(selected_row["quantity"]))
                new_week = st.number_input("Week", min_value=1, max_value=53, step=1, value=int(selected_row["week"]))
                confirm_order = st.form_submit_button("Create Order")

            if confirm_order:
                new_order = {
                    "id": next_id(orders_df),
                    "request_id": int(selected_row["id"]),
                    "article": new_article.strip(),
                    "supplier": new_supplier.strip(),
                    "quantity": int(new_qty),
                    "week": int(new_week),
                    "year": int(selected_row["year"]),
                    "status": "Open",
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                }

                orders_df = pd.concat([orders_df, pd.DataFrame([new_order])], ignore_index=True)
                requests_df.loc[requests_df["id"] == selected_row["id"], "status"] = "Converted"

                save_orders(orders_df)
                save_requests(requests_df)

                st.success("Order created.")
                st.rerun()


# ------------------------------------------------------------
# Orders tab
# ------------------------------------------------------------
with tab_orders:
    st.subheader("Orders")

    order_default_cols = [
        "Order ID", "Request ID", "Article", "Supplier",
        "Quantity", "Week", "Year", "Status", "Created At"
    ]

    with st.expander("Order Layout Settings"):
        current_layout = get_user_layout(user["username"], "orders", order_default_cols)

        visible_cols = st.multiselect(
            "Visible columns",
            options=order_default_cols,
            default=current_layout["visible_columns"],
            key="ord_visible_cols",
        )

        layout_editor_df = pd.DataFrame({
            "Column": order_default_cols,
            "Position": [current_layout["column_order"].index(c) + 1 for c in order_default_cols],
        })

        edited_layout = st.data_editor(
            layout_editor_df,
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            column_config={
                "Column": st.column_config.TextColumn(disabled=True),
                "Position": st.column_config.NumberColumn(min_value=1, max_value=len(order_default_cols), step=1),
            },
            key="ord_layout_editor",
        )

        if st.button("Save Order Layout"):
            ordered_cols = edited_layout.sort_values("Position")["Column"].tolist()
            save_user_layout(user["username"], "orders", visible_cols, ordered_cols)
            st.success("Order layout saved.")
            st.rerun()

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

        orders_view = apply_layout(orders_view, user["username"], "orders", order_default_cols)
        st.dataframe(orders_view, use_container_width=True, hide_index=True)
