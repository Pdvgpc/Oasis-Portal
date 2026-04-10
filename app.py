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
LIST_PATH = f"{DATA_DIR}/request_list.csv"


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


def normalize_list(df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "id",
        "article",
        "quantity",
        "week",
        "year",
        "note",
        "supplier",
        "status",
        "created_at",
    ]
    df = ensure_columns(df if df is not None else pd.DataFrame(), cols)

    for c in ["id", "quantity", "week", "year"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    for c in ["article", "note", "supplier", "status", "created_at"]:
        df[c] = df[c].astype("string")

    return df


def next_id(df: pd.DataFrame) -> int:
    if df.empty or "id" not in df.columns:
        return 1
    try:
        return int(pd.to_numeric(df["id"], errors="coerce").fillna(0).max()) + 1
    except Exception:
        return 1


def excel_bytes(df: pd.DataFrame) -> BytesIO:
    buf = BytesIO()

    export_df = df.copy().rename(columns={
        "id": "ID",
        "article": "Article",
        "quantity": "Quantity",
        "week": "Week",
        "year": "Year",
        "note": "Note",
        "supplier": "Supplier",
        "status": "Status",
        "created_at": "Created At",
    })

    export_df = export_df[
        ["ID", "Article", "Quantity", "Week", "Year", "Note", "Supplier", "Status", "Created At"]
    ]

    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        export_df.to_excel(writer, index=False, sheet_name="Requests")

        ws = writer.sheets["Requests"]
        for column_cells in ws.columns:
            max_length = 0
            col_letter = column_cells[0].column_letter
            for cell in column_cells:
                value = "" if cell.value is None else str(cell.value)
                max_length = max(max_length, len(value))
            ws.column_dimensions[col_letter].width = min(max_length + 2, 35)

    buf.seek(0)
    return buf


# ============================================================
# Init
# ============================================================
user = login()

if "main_list_df" not in st.session_state:
    st.session_state["main_list_df"] = normalize_list(gh_get_csv(LIST_PATH))

main_df = st.session_state["main_list_df"]


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

st.subheader("New Request")

with st.form("new_request_form", clear_on_submit=True):
    article = st.text_input("Article")
    quantity = st.number_input("Quantity", min_value=1, max_value=999999, value=1, step=1)
    week = st.number_input("Week", min_value=1, max_value=53, value=1, step=1)
    year = st.number_input("Year", min_value=2025, max_value=2100, value=datetime.now().year, step=1)
    note = st.text_input("Note")

    add_request = st.form_submit_button("Add Request", use_container_width=True)

if add_request:
    if not str(article).strip():
        st.error("Article is required.")
    else:
        new_row = pd.DataFrame([{
            "id": next_id(main_df),
            "article": str(article).strip(),
            "quantity": int(quantity),
            "week": int(week),
            "year": int(year),
            "note": str(note).strip(),
            "supplier": "",
            "status": "New",
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }])

        updated_df = pd.concat([main_df, new_row], ignore_index=True)
        updated_df = normalize_list(updated_df)

        if gh_put_csv(LIST_PATH, updated_df, "update request list"):
            st.session_state["main_list_df"] = updated_df
            st.success("Request added.")
            st.rerun()
        else:
            st.error("Request could not be saved to GitHub.")

st.markdown("---")
st.subheader("Request List")

if main_df.empty:
    st.info("No requests yet.")
else:
    work_df = normalize_list(main_df.copy())
    work_df.insert(0, "select", False)

    display_df = work_df.rename(columns={
        "select": "Select",
        "id": "ID",
        "article": "Article",
        "quantity": "Quantity",
        "week": "Week",
        "year": "Year",
        "note": "Note",
        "supplier": "Supplier",
        "status": "Status",
        "created_at": "Created At",
    })

    display_df = display_df[
        ["Select", "ID", "Article", "Quantity", "Week", "Year", "Note", "Supplier", "Status", "Created At"]
    ]

    edited_df = st.data_editor(
        display_df,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        column_config={
            "Select": st.column_config.CheckboxColumn(required=False),
            "ID": st.column_config.NumberColumn(disabled=True),
            "Article": st.column_config.TextColumn(),
            "Quantity": st.column_config.NumberColumn(min_value=1, step=1),
            "Week": st.column_config.NumberColumn(min_value=1, max_value=53, step=1),
            "Year": st.column_config.NumberColumn(min_value=2025, max_value=2100, step=1),
            "Note": st.column_config.TextColumn(),
            "Supplier": st.column_config.TextColumn(),
            "Status": st.column_config.SelectboxColumn(
                options=["New", "Seen", "Ordered", "Rejected"]
            ),
            "Created At": st.column_config.TextColumn(disabled=True),
        },
        key="main_editor",
    )

    c1, c2, c3 = st.columns(3)

    with c1:
        if st.button("Save Changes", use_container_width=True):
            to_save = edited_df.drop(columns=["Select"]).rename(columns={
                "ID": "id",
                "Article": "article",
                "Quantity": "quantity",
                "Week": "week",
                "Year": "year",
                "Note": "note",
                "Supplier": "supplier",
                "Status": "status",
                "Created At": "created_at",
            })

            to_save = normalize_list(to_save)

            if gh_put_csv(LIST_PATH, to_save, "update request list"):
                st.session_state["main_list_df"] = to_save
                st.success("Changes saved.")
                st.rerun()
            else:
                st.error("Changes could not be saved.")

    with c2:
        selected_ids = edited_df.loc[edited_df["Select"] == True, "ID"].tolist()

        if st.button("Delete Selected", use_container_width=True):
            if not selected_ids:
                st.warning("Select at least one row.")
            else:
                updated_df = main_df.loc[
                    ~pd.to_numeric(main_df["id"], errors="coerce").isin(selected_ids)
                ].copy()
                updated_df = normalize_list(updated_df)

                if gh_put_csv(LIST_PATH, updated_df, "delete selected rows"):
                    st.session_state["main_list_df"] = updated_df
                    st.success("Selected rows deleted.")
                    st.rerun()
                else:
                    st.error("Selected rows could not be deleted.")

    with c3:
        selected_ids = edited_df.loc[edited_df["Select"] == True, "ID"].tolist()

        if selected_ids:
            export_df = main_df.loc[
                pd.to_numeric(main_df["id"], errors="coerce").isin(selected_ids)
            ].copy()
        else:
            export_df = main_df.copy()

        st.download_button(
            "Export to Excel",
            data=excel_bytes(normalize_list(export_df)).getvalue(),
            file_name=f"oasis_requests_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
