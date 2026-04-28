import streamlit as st
import pandas as pd
import yaml
from datetime import datetime
from io import BytesIO
from pathlib import Path

# =====================================================
# OASIS PORTAL - SIMPLE REQUEST / SHIPMENT LIST
# =====================================================
# Doel:
# - Klanten kunnen requests toevoegen
# - Admin kan regels bewerken
# - Export naar Excel zonder interne kolommen
# - Tray Size toegevoegd
# - Klantcodes vanaf kolom G in export
# =====================================================

st.set_page_config(
    page_title="Oasis Portal",
    page_icon="🌿",
    layout="wide",
)

# =====================================================
# CONFIG
# =====================================================

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

REQUESTS_FILE = DATA_DIR / "request_list.csv"

CUSTOMER_CODES = [
    "ELF", "ABD", "SAL", "NAM", "BOAZ", "BALA", "ATUN", "VIK",
    "PEL", "YOG", "BERG", "KDU", "RAFI", "BENE", "ETZ", "KOB",
    "OREN", "GRAN", "FAR",
]

INTERNAL_COLUMNS = [
    "ID",
    "Article",
    "Tray Size",
    "Quantity",
    "Week",
    "Year",
    "Note",
    "Supplier",
    "Status",
    "Created At",
] + CUSTOMER_CODES

EXPORT_COLUMNS = [
    "Article",
    "Tray Size",
    "Quantity",
    "Week",
    "Note",
    "Supplier",
] + CUSTOMER_CODES

STATUS_OPTIONS = ["New", "In Request", "Ordered", "Denied"]

# =====================================================
# LOGIN VIA auth.yaml
# Verwachte structuur:
# credentials:
#   usernames:
#     pieter:
#       name: Pieter
#       role: admin
#       password_plain: jouw_wachtwoord
#     ilan:
#       name: Ilan
#       role: customer
#       password_plain: klant_wachtwoord

AUTH_FILE = Path("auth.yaml")


def load_users_from_yaml():
    if not AUTH_FILE.exists():
        st.error("auth.yaml niet gevonden in de hoofdmap van je repo.")
        st.stop()

    with open(AUTH_FILE, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    try:
        return config["credentials"]["usernames"]
    except Exception:
        st.error("auth.yaml heeft niet de juiste structuur.")
        st.stop()


def login():
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
        st.session_state.username = None
        st.session_state.role = None

    if st.session_state.logged_in:
        return True

    users = load_users_from_yaml()

    st.title("🌿 Oasis Portal")
    st.subheader("Login")

    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")

    if submitted:
        user = users.get(username)

        if user and str(user.get("password_plain", "")) == password:
            st.session_state.logged_in = True
            st.session_state.username = username
            st.session_state.role = user.get("role", "customer")
            st.rerun()
        else:
            st.error("Incorrect username or password")

    return False


# =====================================================
# DATA FUNCTIONS
# =====================================================


def ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    # --- AUTO CONVERT OLD CSV STRUCTURE ---
    COLUMN_RENAME_MAP = {
        "id": "ID",
        "article": "Article",
        "quantity": "Quantity",
        "week": "Week",
        "year": "Year",
        "note": "Note",
        "supplier": "Supplier",
        "status": "Status",
        "created_at": "Created At",
    }

    df = df.rename(columns=COLUMN_RENAME_MAP)

    # Tray Size bestond nog niet → standaard 0
    if "Tray Size" not in df.columns:
        df["Tray Size"] = 0

    # --- ENSURE ALL REQUIRED COLUMNS ---
    for col in INTERNAL_COLUMNS:
        if col not in df.columns:
            if col in CUSTOMER_CODES:
                df[col] = 0
            elif col == "Status":
                df[col] = "New"
            else:
                df[col] = ""

    df = df[INTERNAL_COLUMNS]

    numeric_cols = ["ID", "Quantity", "Tray Size", "Week", "Year"] + CUSTOMER_CODES
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    df["Article"] = df["Article"].astype(str)
    df["Note"] = df["Note"].astype(str)
    df["Supplier"] = df["Supplier"].astype(str)
    df["Status"] = df["Status"].astype(str)
    df["Created At"] = df["Created At"].astype(str)

    return df


def load_requests() -> pd.DataFrame:
    if not REQUESTS_FILE.exists():
        df = pd.DataFrame(columns=INTERNAL_COLUMNS)
        df.to_csv(REQUESTS_FILE, index=False)
        return df

    df = pd.read_csv(REQUESTS_FILE)
    return ensure_columns(df)


def save_requests(df: pd.DataFrame):
    df = ensure_columns(df)
    df.to_csv(REQUESTS_FILE, index=False)


def next_id(df: pd.DataFrame) -> int:
    if df.empty:
        return 1
    return int(df["ID"].max()) + 1


def make_excel_file(df: pd.DataFrame) -> BytesIO:
    export_df = df.copy()

    for col in EXPORT_COLUMNS:
        if col not in export_df.columns:
            export_df[col] = 0 if col in CUSTOMER_CODES else ""

    export_df = export_df[EXPORT_COLUMNS]

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        export_df.to_excel(writer, index=False, sheet_name="Requests")

        ws = writer.book["Requests"]

        for column_cells in ws.columns:
            max_length = 0
            column_letter = column_cells[0].column_letter
            for cell in column_cells:
                value = "" if cell.value is None else str(cell.value)
                max_length = max(max_length, len(value))
            ws.column_dimensions[column_letter].width = max_length + 2

    output.seek(0)
    return output


# =====================================================
# APP
# =====================================================

if not login():
    st.stop()

role = st.session_state.role
username = st.session_state.username

st.title("🌿 Oasis Portal")
st.caption(f"Logged in as: {username} | Role: {role}")

top_col1, top_col2, top_col3 = st.columns([2, 2, 1])

with top_col1:
    mobile_mode = st.toggle("Mobile mode", value=False)

with top_col3:
    if st.button("Logout"):
        st.session_state.logged_in = False
        st.session_state.username = None
        st.session_state.role = None
        st.rerun()

# Load data
requests_df = load_requests()

# =====================================================
# ADD NEW REQUEST
# =====================================================

st.header("Add New Request")

with st.form("new_request_form", clear_on_submit=True):
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        article = st.text_input("Article")

    with col2:
        tray_size = st.number_input("Tray Size", min_value=0, step=1)

    with col3:
        quantity = st.number_input("Quantity", min_value=0, step=1)

    with col4:
        week = st.number_input("Week", min_value=1, max_value=53, step=1)

    col5, col6, col7 = st.columns(3)

    with col5:
        year = st.number_input("Year", min_value=2024, max_value=2100, value=datetime.now().year, step=1)

    with col6:
        supplier = st.text_input("Supplier") if role == "admin" else st.text_input("Supplier", disabled=True)

    with col7:
        note = st.text_input("Note")

    submitted = st.form_submit_button("Add request")

if submitted:
    if not article.strip():
        st.error("Article is required")
    elif quantity <= 0:
        st.error("Quantity must be higher than 0")
    else:
        new_row = {col: 0 if col in CUSTOMER_CODES else "" for col in INTERNAL_COLUMNS}
        new_row.update({
            "ID": next_id(requests_df),
            "Article": article.strip(),
            "Tray Size": int(tray_size),
            "Quantity": int(quantity),
            "Week": int(week),
            "Year": int(year),
            "Note": note.strip(),
            "Supplier": supplier.strip() if role == "admin" else "",
            "Status": "New",
            "Created At": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        })

        requests_df = pd.concat([requests_df, pd.DataFrame([new_row])], ignore_index=True)
        save_requests(requests_df)
        st.success("Request added")
        st.rerun()

st.divider()

# =====================================================
# FILTERS
# =====================================================

st.header("Request List")

filter_col1, filter_col2, filter_col3 = st.columns(3)

with filter_col1:
    status_filter = st.selectbox("Status filter", ["All"] + STATUS_OPTIONS, index=0)

with filter_col2:
    article_search = st.text_input("Search article")

with filter_col3:
    supplier_search = st.text_input("Search supplier") if role == "admin" else ""

view_df = requests_df.copy()

if status_filter != "All":
    view_df = view_df[view_df["Status"] == status_filter]

if article_search:
    view_df = view_df[view_df["Article"].str.contains(article_search, case=False, na=False)]

if role == "admin" and supplier_search:
    view_df = view_df[view_df["Supplier"].str.contains(supplier_search, case=False, na=False)]

# =====================================================
# TABLE EDITING
# =====================================================

if role == "admin":
    st.caption("Admin view: select rows, edit supplier, status, customer-code quantities, and other fields.")

    editor_df = view_df.copy()
    editor_df.insert(0, "Select", False)

    if mobile_mode:
        visible_columns = ["Select", "ID", "Article", "Tray Size", "Quantity", "Week", "Supplier", "Status"]
    else:
        visible_columns = ["Select"] + INTERNAL_COLUMNS

    edited_df = st.data_editor(
        editor_df[visible_columns],
        use_container_width=True,
        num_rows="fixed",
        hide_index=True,
        column_config={
            "Status": st.column_config.SelectboxColumn(
                "Status",
                options=STATUS_OPTIONS,
                required=True,
            ),
            "Select": st.column_config.CheckboxColumn(
                "Select",
                default=False,
            ),
            "Quantity": st.column_config.NumberColumn("Quantity", min_value=0, step=1),
            "Tray Size": st.column_config.NumberColumn("Tray Size", min_value=0, step=1),
            "Week": st.column_config.NumberColumn("Week", min_value=1, max_value=53, step=1),
            "Year": st.column_config.NumberColumn("Year", min_value=2024, max_value=2100, step=1),
            **{
                code: st.column_config.NumberColumn(code, min_value=0, step=1)
                for code in CUSTOMER_CODES
            },
        },
        key="admin_editor",
    )

    col_save, col_delete, col_export = st.columns(3)

    with col_save:
        if st.button("Save changes", type="primary"):
            updated_df = requests_df.copy()

            for _, row in edited_df.iterrows():
                row_id = int(row["ID"])
                idx = updated_df.index[updated_df["ID"] == row_id]
                if len(idx) == 1:
                    for col in edited_df.columns:
                        if col != "Select":
                            updated_df.loc[idx[0], col] = row[col]

            save_requests(updated_df)
            st.success("Changes saved")
            st.rerun()

    with col_delete:
        selected_ids = edited_df.loc[edited_df["Select"] == True, "ID"].astype(int).tolist()

        if st.button("Delete selected"):
            if selected_ids:
                requests_df = requests_df[~requests_df["ID"].isin(selected_ids)]
                save_requests(requests_df)
                st.success("Selected rows deleted")
                st.rerun()
            else:
                st.warning("No rows selected")

    with col_export:
        excel_file = make_excel_file(view_df)
        st.download_button(
            label="Export Excel",
            data=excel_file,
            file_name="oasis_requests_export.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

else:
    st.caption("Customer view: you can add requests. Editing is disabled.")

    customer_view_columns = [
        "Article",
        "Tray Size",
        "Quantity",
        "Week",
        "Note",
        "Status",
    ]

    st.dataframe(
        view_df[customer_view_columns],
        use_container_width=True,
        hide_index=True,
    )

# =====================================================
# EXPORT PREVIEW
# =====================================================

if role == "admin":
    with st.expander("Excel export preview"):
        export_preview = view_df.copy()
        for col in EXPORT_COLUMNS:
            if col not in export_preview.columns:
                export_preview[col] = 0 if col in CUSTOMER_CODES else ""
        st.dataframe(export_preview[EXPORT_COLUMNS], use_container_width=True, hide_index=True)
