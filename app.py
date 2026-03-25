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


def gh_get_text(path: str) -> Optional[str]:
    try:
        r = requests.get(gh_api(f"/contents/{path}"), headers=gh_headers(), timeout=15)
    except Exception as e:
        st.error(f"GitHub connection failed: {e}")
        return ""

    if r.status_code == 200:
        return base64.b64decode(r.json()["content"]).decode("utf-8", errors="ignore")
    if r.status_code == 404:
        return None

    st.error(f"GitHub read error {r.status_code}: {r.text[:300]}")
    return ""


def gh_put_csv(path: str, df: pd.DataFrame, msg: str) -> bool:
    url = gh_api(f"/contents/{path}")

    try:
        r = requests.get(url, headers=gh_headers(), timeout=15)
    except Exception as e:
        st.error(f"GitHub pre-write read failed: {e}")
        return False

    sha = r.json().get("sha") if r.status_code == 200 else None

    payload = {
        "message": msg,
        "content": base64.b64encode(df.to_csv(index=False).encode("utf-8")).decode("ascii"),
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


def gh_get_csv(path: str) -> pd.DataFrame:
    txt = gh_get_text(path)
    if txt is None or not txt.strip():
        return pd.DataFrame()
    try:
        return pd.read_csv(StringIO(txt))
    except Exception:
        return pd.DataFrame()


# ============================================================
# Paths
# ============================================================
DATA_DIR = SEC.get("DATA_DIR", "data")

REQ_PATH = f"{DATA_DIR}/requests.csv"
ORD_PATH = f"{DATA_DIR}/orders.csv"
REJ_PATH = f"{DATA_DIR}/rejected_orders.csv"


# ============================================================
# Auth
# ============================================================
def load_auth():
    try:
        with open(AUTH_YAML, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        st.error("auth.yaml not found or invalid.")
        st.stop()


def login():
    users = load_auth().get("credentials", {}).get("usernames", {})

    if "user" in st.session_state:
        return st.session_state["user"]

    st.title("Oasis Portal")
    st.subheader("Login")

    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Login", use_container_width=True):
        rec = users.get(username)
        if rec and str(rec.get("password_plain", "")) == str(password):
            st.session_state["user"] = username
            st.rerun()
        else:
            st.error("Wrong login")

    st.stop()


# ============================================================
# Helpers
# ============================================================
def ensure_columns(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    df = df.copy()
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    return df[cols]


def normalize_requests(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["id", "article", "quantity", "week", "year", "note", "created_at"]
    df = ensure_columns(df if df is not None else pd.DataFrame(), cols)
    for c in ["id", "quantity", "week", "year"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def normalize_orders(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["id", "request_id", "article", "supplier", "quantity", "week", "year", "status", "created_at"]
    df = ensure_columns(df if df is not None else pd.DataFrame(), cols)
    for c in ["id", "request_id", "quantity", "week", "year"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def normalize_rejected(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["id", "request_id", "article", "quantity", "week", "year", "note", "rejected_at"]
    df = ensure_columns(df if df is not None else pd.DataFrame(), cols)
    for c in ["id", "request_id", "quantity", "week", "year"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def next_id(df: pd.DataFrame) -> int:
    if df.empty or "id" not in df.columns:
        return 1
    try:
        return int(pd.to_numeric(df["id"], errors="coerce").fillna(0).max()) + 1
    except Exception:
        return 1


def auto_width_worksheet(ws, max_width: int = 35):
    for column_cells in ws.columns:
        max_length = 0
        col_letter = column_cells[0].column_letter
        for cell in column_cells:
            value = "" if cell.value is None else str(cell.value)
            max_length = max(max_length, len(value))
        ws.column_dimensions[col_letter].width = min(max_length + 2, max_width)


def orders_excel_bytes(df: pd.DataFrame) -> BytesIO:
    buf = BytesIO()
    export_df = df.copy()

    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        export_df.to_excel(writer, index=False, sheet_name="Orders")
        ws = writer.sheets["Orders"]
        auto_width_worksheet(ws)

    buf.seek(0)
    return buf


def build_requests_pivot_export_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["Article", "Note"])

    work = df.copy()
    work["article"] = work["article"].astype(str).fillna("")
    work["note"] = work["note"].astype(str).fillna("")
    work["quantity"] = pd.to_numeric(work["quantity"], errors="coerce").fillna(0).astype(int)
    work["week"] = pd.to_numeric(work["week"], errors="coerce").astype("Int64")
    work["year"] = pd.to_numeric(work["year"], errors="coerce").astype("Int64")

    def make_yearweek(row):
        if pd.isna(row["year"]) or pd.isna(row["week"]):
            return None
        return f"{int(row['year'])}{int(row['week']):02d}"

    work["YearWeek"] = work.apply(make_yearweek, axis=1)
    work = work[work["YearWeek"].notna()].copy()

    if work.empty:
        return pd.DataFrame(columns=["Article", "Note"])

    pivot = work.pivot_table(
        index=["article", "note"],
        columns="YearWeek",
        values="quantity",
        aggfunc="sum",
        fill_value=0,
    )

    if isinstance(pivot.columns, pd.MultiIndex):
        pivot.columns = [c[-1] for c in pivot.columns]

    cols_sorted = sorted([c for c in pivot.columns if c is not None], key=lambda x: int(x))
    pivot = pivot.reindex(columns=cols_sorted)

    pivot = pivot.reset_index()
    pivot = pivot.rename(columns={
        "article": "Article",
        "note": "Note",
    })

    return pivot


def requests_excel_bytes(df: pd.DataFrame) -> BytesIO:
    buf = BytesIO()
    export_df = build_requests_pivot_export_df(df)

    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        export_df.to_excel(writer, index=False, sheet_name="Requests")
        ws = writer.sheets["Requests"]
        auto_width_worksheet(ws)

    buf.seek(0)
    return buf


# ============================================================
# Init
# ============================================================
user = login()

if "requests_df" not in st.session_state:
    st.session_state["requests_df"] = normalize_requests(gh_get_csv(REQ_PATH))

if "orders_df" not in st.session_state:
    st.session_state["orders_df"] = normalize_orders(gh_get_csv(ORD_PATH))

if "rejected_df" not in st.session_state:
    st.session_state["rejected_df"] = normalize_rejected(gh_get_csv(REJ_PATH))

requests_df = st.session_state["requests_df"]
orders_df = st.session_state["orders_df"]
rejected_df = st.session_state["rejected_df"]


# ============================================================
# Sidebar
# ============================================================
st.sidebar.success(f"Logged in as {user}")

if st.sidebar.button("Logout"):
    st.session_state.clear()
    st.rerun()

st.sidebar.markdown("---")

st.session_state.setdefault("mobile_mode", False)
st.session_state["mobile_mode"] = st.sidebar.checkbox(
    "📱 Mobile mode",
    value=st.session_state["mobile_mode"]
)

if st.session_state["mobile_mode"]:
    st.markdown(
        """
        <style>
        .block-container {
            max-width: 700px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ============================================================
# UI
# ============================================================
st.title("Oasis Portal")

tab_requests, tab_orders, tab_rejected = st.tabs(["Requests", "Orders", "Rejected"])


# ============================================================
# REQUESTS
# ============================================================
with tab_requests:
    st.subheader("New Request")

    with st.form("new_request_form"):
        article = st.text_input("Article")
        quantity = st.number_input("Quantity", min_value=1, max_value=999999, value=1, step=1)
        week = st.number_input("Week", min_value=1, max_value=53, value=1, step=1)
        year = st.number_input("Year", min_value=2025, max_value=2100, value=datetime.now().year, step=1)
        note = st.text_input("Note")

        add_request = st.form_submit_button("Add", use_container_width=True)

    if add_request:
        if not str(article).strip():
            st.error("Article needed")
        else:
            new_row = pd.DataFrame([{
                "id": next_id(requests_df),
                "article": str(article).strip(),
                "quantity": int(quantity),
                "week": int(week),
                "year": int(year),
                "note": str(note).strip(),
                "created_at": datetime.now().isoformat(timespec="seconds")
            }])

            new_requests_df = pd.concat([requests_df, new_row], ignore_index=True)

            if gh_put_csv(REQ_PATH, normalize_requests(new_requests_df), "update requests"):
                st.session_state["requests_df"] = normalize_requests(new_requests_df)
                st.success("Request added")
                st.rerun()
            else:
                st.error("Request could not be saved to GitHub.")

    st.markdown("---")
    st.subheader("Export Requests to Excel")

    if requests_df.empty:
        st.info("No requests available for export.")
    else:
        export_requests_df = requests_df.copy()
        export_requests_df.insert(0, "Select", False)

        export_requests_df = export_requests_df.rename(columns={
            "id": "Request ID",
            "article": "Article",
            "quantity": "Quantity",
            "week": "Week",
            "year": "Year",
            "note": "Note",
            "created_at": "Created At",
        })

        export_requests_df = export_requests_df[
            ["Select", "Request ID", "Article", "Quantity", "Week", "Year", "Note", "Created At"]
        ]

        edited_requests_export = st.data_editor(
            export_requests_df,
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            column_config={
                "Select": st.column_config.CheckboxColumn(required=False),
            },
            key="requests_export_editor",
        )

        selected_request_ids = edited_requests_export.loc[
            edited_requests_export["Select"] == True, "Request ID"
        ].tolist()

        if selected_request_ids:
            selected_requests_df = requests_df.loc[
                pd.to_numeric(requests_df["id"], errors="coerce").isin(selected_request_ids)
            ].copy()

            req_excel = requests_excel_bytes(selected_requests_df)

            st.download_button(
                "Export Selected Requests to Excel",
                data=req_excel.getvalue(),
                file_name=f"requests_export_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        else:
            st.caption("Select one or more requests to enable export.")

    st.markdown("---")
    st.subheader("Create or Reject Request")

    if requests_df.empty:
        st.info("No open requests available.")
    else:
        select_df = requests_df.copy()
        select_df["label"] = select_df.apply(
            lambda r: f"#{int(r['id'])} | {str(r['article'])} | Qty {int(r['quantity']) if pd.notna(r['quantity']) else 0} | Week {int(r['week']) if pd.notna(r['week']) else 0}",
            axis=1,
        )

        selected_label = st.selectbox("Select request", select_df["label"].tolist(), key="request_selectbox")
        selected_id = int(selected_label.split("|")[0].replace("#", "").strip())
        row = select_df.loc[pd.to_numeric(select_df["id"], errors="coerce") == selected_id].iloc[0]

        with st.form("create_or_reject_request_form"):
            art = st.text_input("Article", value=str(row["article"]))
            sup = st.text_input("Supplier")
            qty = st.number_input("Quantity", min_value=1, max_value=999999, value=int(row["quantity"]), step=1)
            wk = st.number_input("Week", min_value=1, max_value=53, value=int(row["week"]), step=1)

            c1, c2 = st.columns(2)
            with c1:
                create = st.form_submit_button("Create Order", use_container_width=True)
            with c2:
                reject = st.form_submit_button("Reject", use_container_width=True)

        if create:
            if not str(art).strip():
                st.error("Article needed")
            else:
                new_order = pd.DataFrame([{
                    "id": next_id(orders_df),
                    "request_id": int(row["id"]),
                    "article": str(art).strip(),
                    "supplier": str(sup).strip(),
                    "quantity": int(qty),
                    "week": int(wk),
                    "year": int(row["year"]),
                    "status": "Open",
                    "created_at": datetime.now().isoformat(timespec="seconds")
                }])

                updated_orders = pd.concat([orders_df, new_order], ignore_index=True)
                updated_requests = requests_df.loc[
                    pd.to_numeric(requests_df["id"], errors="coerce") != int(row["id"])
                ].copy()

                ok1 = gh_put_csv(ORD_PATH, normalize_orders(updated_orders), "update orders")
                ok2 = gh_put_csv(REQ_PATH, normalize_requests(updated_requests), "update requests")

                if ok1 and ok2:
                    st.session_state["orders_df"] = normalize_orders(updated_orders)
                    st.session_state["requests_df"] = normalize_requests(updated_requests)
                    st.success("Order created")
                    st.rerun()
                else:
                    st.error("Order could not be saved to GitHub.")

        if reject:
            new_rejected = pd.DataFrame([{
                "id": next_id(rejected_df),
                "request_id": int(row["id"]),
                "article": str(row["article"]),
                "quantity": int(row["quantity"]),
                "week": int(row["week"]),
                "year": int(row["year"]),
                "note": str(row["note"]) if pd.notna(row["note"]) else "",
                "rejected_at": datetime.now().isoformat(timespec="seconds")
            }])

            updated_rejected = pd.concat([rejected_df, new_rejected], ignore_index=True)
            updated_requests = requests_df.loc[
                pd.to_numeric(requests_df["id"], errors="coerce") != int(row["id"])
            ].copy()

            ok1 = gh_put_csv(REJ_PATH, normalize_rejected(updated_rejected), "update rejected")
            ok2 = gh_put_csv(REQ_PATH, normalize_requests(updated_requests), "update requests")

            if ok1 and ok2:
                st.session_state["rejected_df"] = normalize_rejected(updated_rejected)
                st.session_state["requests_df"] = normalize_requests(updated_requests)
                st.success("Request rejected")
                st.rerun()
            else:
                st.error("Rejected request could not be saved to GitHub.")


# ============================================================
# ORDERS
# ============================================================
with tab_orders:
    st.subheader("Orders")

    if orders_df.empty:
        st.info("No orders yet.")
    else:
        display_orders = orders_df.copy()
        display_orders.insert(0, "Select", False)

        edited_orders = st.data_editor(
            display_orders,
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            column_config={
                "Select": st.column_config.CheckboxColumn(required=False),
            },
            key="orders_editor",
        )

        selected_ids = edited_orders.loc[edited_orders["Select"] == True, "id"].tolist()

        if st.button("Delete selected", use_container_width=True):
            if not selected_ids:
                st.warning("Select at least one order.")
            else:
                updated_orders = orders_df.loc[
                    ~pd.to_numeric(orders_df["id"], errors="coerce").isin(selected_ids)
                ].copy()

                if gh_put_csv(ORD_PATH, normalize_orders(updated_orders), "update orders"):
                    st.session_state["orders_df"] = normalize_orders(updated_orders)
                    st.success("Selected orders deleted")
                    st.rerun()
                else:
                    st.error("Orders could not be deleted.")

        st.download_button(
            "Export Excel",
            data=orders_excel_bytes(normalize_orders(orders_df)),
            file_name="orders.xlsx",
            use_container_width=True,
        )


# ============================================================
# REJECTED
# ============================================================
with tab_rejected:
    st.subheader("Rejected")

    if rejected_df.empty:
        st.info("No rejected orders yet.")
    else:
        display_rejected = rejected_df.copy()
        display_rejected.insert(0, "Select", False)

        edited_rejected = st.data_editor(
            display_rejected,
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            column_config={
                "Select": st.column_config.CheckboxColumn(required=False),
            },
            key="rejected_editor",
        )

        selected_rejected_ids = edited_rejected.loc[edited_rejected["Select"] == True, "id"].tolist()

        if st.button("Delete rejected", use_container_width=True):
            if not selected_rejected_ids:
                st.warning("Select at least one rejected item.")
            else:
                updated_rejected = rejected_df.loc[
                    ~pd.to_numeric(rejected_df["id"], errors="coerce").isin(selected_rejected_ids)
                ].copy()

                if gh_put_csv(REJ_PATH, normalize_rejected(updated_rejected), "update rejected"):
                    st.session_state["rejected_df"] = normalize_rejected(updated_rejected)
                    st.success("Selected rejected items deleted")
                    st.rerun()
                else:
                    st.error("Rejected items could not be deleted.")
