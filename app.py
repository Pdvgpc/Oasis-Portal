import base64
import json
from datetime import datetime
from io import BytesIO, StringIO
from typing import Optional

import pandas as pd
import requests
import streamlit as st
import yaml

# ============================================================
# Page config
# ============================================================
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


def rejected_orders_path() -> str:
    repo_dir = SEC.get("DATA_DIR", "data")
    return f"{repo_dir}/rejected_orders.csv"


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

    if st.button("Login", type="primary", use_container_width=True):
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
    cols = ["id", "article", "quantity", "week", "year", "note", "created_at"]
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


def normalize_rejected_orders(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["id", "request_id", "article", "quantity", "week", "year", "note", "rejected_at"]
    if df is None:
        df = pd.DataFrame(columns=cols)
    df = ensure_columns(df, cols)

    for col in ["id", "request_id", "quantity", "week", "year"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def load_requests() -> pd.DataFrame:
    df = gh_get_csv(requests_path())
    if df is None:
        df = pd.DataFrame(columns=["id", "article", "quantity", "week", "year", "note", "created_at"])
    return normalize_requests(df)


def load_orders() -> pd.DataFrame:
    df = gh_get_csv(orders_path())
    if df is None:
        df = pd.DataFrame(columns=["id", "request_id", "article", "supplier", "quantity", "week", "year", "status", "created_at"])
    return normalize_orders(df)


def load_rejected_orders() -> pd.DataFrame:
    df = gh_get_csv(rejected_orders_path())
    if df is None:
        df = pd.DataFrame(columns=["id", "request_id", "article", "quantity", "week", "year", "note", "rejected_at"])
    return normalize_rejected_orders(df)


def save_requests(df: pd.DataFrame) -> bool:
    return gh_put_csv(requests_path(), normalize_requests(df), "update requests.csv")


def save_orders(df: pd.DataFrame) -> bool:
    return gh_put_csv(orders_path(), normalize_orders(df), "update orders.csv")


def save_rejected_orders(df: pd.DataFrame) -> bool:
    return gh_put_csv(rejected_orders_path(), normalize_rejected_orders(df), "update rejected_orders.csv")


def next_id(df: pd.DataFrame) -> int:
    if df.empty or "id" not in df.columns:
        return 1
    try:
        return int(pd.to_numeric(df["id"], errors="coerce").fillna(0).max()) + 1
    except Exception:
        return 1


def orders_excel_bytes(df: pd.DataFrame) -> BytesIO:
    output = BytesIO()
    export_df = df.copy()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        export_df.to_excel(writer, index=False, sheet_name="Orders")
        ws = writer.sheets["Orders"]

        for column_cells in ws.columns:
            max_length = 0
            col_letter = column_cells[0].column_letter
            for cell in column_cells:
                cell_value = "" if cell.value is None else str(cell.value)
                max_length = max(max_length, len(cell_value))
            ws.column_dimensions[col_letter].width = min(max_length + 2, 30)

    output.seek(0)
    return output


# ============================================================
# Mobile mode
# ============================================================
st.session_state.setdefault("mobile_mode", False)

top_left, top_right = st.columns([5, 1])
with top_right:
    mobile_mode = st.checkbox("📱 Mobile", value=st.session_state["mobile_mode"])
    st.session_state["mobile_mode"] = mobile_mode

if st.session_state["mobile_mode"]:
    st.markdown(
        """
        <style>
        .block-container {
            max-width: 700px;
            padding-top: 1.2rem;
            padding-left: 1rem;
            padding-right: 1rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ============================================================
# Init
# ============================================================
user = login_panel()

if "requests_df" not in st.session_state:
    st.session_state["requests_df"] = load_requests()

if "orders_df" not in st.session_state:
    st.session_state["orders_df"] = load_orders()

if "rejected_orders_df" not in st.session_state:
    st.session_state["rejected_orders_df"] = load_rejected_orders()

requests_df = st.session_state["requests_df"]
orders_df = st.session_state["orders_df"]
rejected_orders_df = st.session_state["rejected_orders_df"]

st.sidebar.success(f"Logged in as {user['name']}")

if st.sidebar.button("Logout"):
    st.session_state["user"] = None
    st.session_state.pop("requests_df", None)
    st.session_state.pop("orders_df", None)
    st.session_state.pop("rejected_orders_df", None)
    st.rerun()

st.title("Oasis Portal")

tab_requests, tab_orders, tab_rejected = st.tabs(["Requests", "Orders", "Rejected Orders"])


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

        submit_request = st.form_submit_button("Add Request", use_container_width=True)

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
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }

            new_requests_df = pd.concat([requests_df, pd.DataFrame([new_row])], ignore_index=True)

            if save_requests(new_requests_df):
                st.session_state["requests_df"] = new_requests_df
                st.success("Request added.")
                st.rerun()
            else:
                st.error("Request could not be saved to GitHub.")

    st.markdown("---")
    st.subheader("Create or Reject Request")

    if requests_df.empty:
        st.info("No open requests available.")
    else:
        requests_select_df = requests_df.copy()
        requests_select_df["label"] = requests_select_df.apply(
            lambda r: f"#{int(r['id'])} | {str(r['article'])} | Qty {int(r['quantity']) if pd.notna(r['quantity']) else 0} | Week {int(r['week']) if pd.notna(r['week']) else 0}",
            axis=1,
        )

        labels = requests_select_df["label"].tolist()
        id_by_label = dict(zip(requests_select_df["label"], requests_select_df["id"]))

        selected_label = st.selectbox("Select request", options=labels)
        selected_id = int(id_by_label[selected_label])
        selected_row = requests_select_df.loc[
            pd.to_numeric(requests_select_df["id"], errors="coerce") == selected_id
        ].iloc[0]

        with st.form("create_or_reject_form"):
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

            c1, c2 = st.columns(2)
            with c1:
                create_order = st.form_submit_button("Create Order", use_container_width=True)
            with c2:
                reject_request = st.form_submit_button("Reject Request", use_container_width=True)

        if create_order:
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
                new_requests_df = requests_df.loc[
                    pd.to_numeric(requests_df["id"], errors="coerce") != int(selected_row["id"])
                ].copy()

                ok_orders = save_orders(new_orders_df)
                ok_requests = save_requests(new_requests_df)

                if ok_orders and ok_requests:
                    st.session_state["orders_df"] = new_orders_df
                    st.session_state["requests_df"] = new_requests_df
                    st.success("Order created. Request removed from open requests.")
                    st.rerun()
                else:
                    st.error("Order could not be saved to GitHub.")

        if reject_request:
            new_rejected_row = {
                "id": next_id(rejected_orders_df),
                "request_id": int(selected_row["id"]),
                "article": str(selected_row["article"]),
                "quantity": int(selected_row["quantity"]) if pd.notna(selected_row["quantity"]) else 0,
                "week": int(selected_row["week"]) if pd.notna(selected_row["week"]) else 0,
                "year": int(selected_row["year"]) if pd.notna(selected_row["year"]) else datetime.now().year,
                "note": str(selected_row["note"]) if pd.notna(selected_row["note"]) else "",
                "rejected_at": datetime.now().isoformat(timespec="seconds"),
            }

            new_rejected_df = pd.concat([rejected_orders_df, pd.DataFrame([new_rejected_row])], ignore_index=True)
            new_requests_df = requests_df.loc[
                pd.to_numeric(requests_df["id"], errors="coerce") != int(selected_row["id"])
            ].copy()

            ok_rejected = save_rejected_orders(new_rejected_df)
            ok_requests = save_requests(new_requests_df)

            if ok_rejected and ok_requests:
                st.session_state["rejected_orders_df"] = new_rejected_df
                st.session_state["requests_df"] = new_requests_df
                st.success("Request rejected and moved to Rejected Orders.")
                st.rerun()
            else:
                st.error("Request could not be rejected.")


# ============================================================
# Orders tab
# ============================================================
with tab_orders:
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

        orders_view = orders_view[
            ["Order ID", "Request ID", "Article", "Supplier", "Quantity", "Week", "Year", "Status", "Created At"]
        ]

        excel_file = orders_excel_bytes(orders_view)

        if st.session_state["mobile_mode"]:
            st.download_button(
                label="Export Orders to Excel",
                data=excel_file.getvalue(),
                file_name=f"oasis_orders_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        else:
            c1, c2 = st.columns([1, 3])
            with c1:
                st.download_button(
                    label="Export Orders to Excel",
                    data=excel_file.getvalue(),
                    file_name=f"oasis_orders_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )

        st.markdown("---")

        delete_df = orders_view.copy()
        delete_df.insert(0, "Select", False)

        edited_orders = st.data_editor(
            delete_df,
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            column_config={
                "Select": st.column_config.CheckboxColumn(required=False),
            },
            key="orders_delete_editor",
        )

        selected_order_ids = edited_orders.loc[edited_orders["Select"] == True, "Order ID"].tolist()

        if st.button("Delete Selected Orders", type="primary", use_container_width=st.session_state["mobile_mode"]):
            if not selected_order_ids:
                st.warning("Select at least one order.")
            else:
                new_orders_df = orders_df.loc[
                    ~pd.to_numeric(orders_df["id"], errors="coerce").isin(selected_order_ids)
                ].copy()

                if save_orders(new_orders_df):
                    st.session_state["orders_df"] = new_orders_df
                    st.success(f"Deleted orders: {', '.join(map(str, selected_order_ids))}")
                    st.rerun()
                else:
                    st.error("Orders could not be deleted.")


# ============================================================
# Rejected Orders tab
# ============================================================
with tab_rejected:
    st.subheader("Rejected Orders")

    if rejected_orders_df.empty:
        st.info("No rejected orders yet.")
    else:
        rejected_view = rejected_orders_df.copy()
        rejected_view = rejected_view.rename(columns={
            "id": "Rejected ID",
            "request_id": "Request ID",
            "article": "Article",
            "quantity": "Quantity",
            "week": "Week",
            "year": "Year",
            "note": "Note",
            "rejected_at": "Rejected At",
        })

        rejected_view = rejected_view[
            ["Rejected ID", "Request ID", "Article", "Quantity", "Week", "Year", "Note", "Rejected At"]
        ]

        delete_rejected_df = rejected_view.copy()
        delete_rejected_df.insert(0, "Select", False)

        edited_rejected = st.data_editor(
            delete_rejected_df,
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            column_config={
                "Select": st.column_config.CheckboxColumn(required=False),
            },
            key="rejected_delete_editor",
        )

        selected_rejected_ids = edited_rejected.loc[edited_rejected["Select"] == True, "Rejected ID"].tolist()

        if st.button("Delete Selected Rejected Orders", type="primary", use_container_width=st.session_state["mobile_mode"]):
            if not selected_rejected_ids:
                st.warning("Select at least one rejected order.")
            else:
                new_rejected_df = rejected_orders_df.loc[
                    ~pd.to_numeric(rejected_orders_df["id"], errors="coerce").isin(selected_rejected_ids)
                ].copy()

                if save_rejected_orders(new_rejected_df):
                    st.session_state["rejected_orders_df"] = new_rejected_df
                    st.success(f"Deleted rejected orders: {', '.join(map(str, selected_rejected_ids))}")
                    st.rerun()
                else:
                    st.error("Rejected orders could not be deleted.")
