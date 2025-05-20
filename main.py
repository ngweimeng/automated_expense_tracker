import streamlit as st
import pandas as pd
import plotly.express as px
import json
import os
import sqlite3
from datetime import datetime

# Constants
DB_FILE = "transactions.db"
CATEGORY_FILE = "categories.json"

st.set_page_config(page_title="Simple Finance App", page_icon="💰", layout="wide")


# --- Database Helpers ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            Date TEXT,
            Description TEXT,
            Amount REAL
        )
        """
    )
    c.execute("PRAGMA table_info(transactions)")
    cols = [row[1] for row in c.fetchall()]
    if "Source" not in cols:
        c.execute("ALTER TABLE transactions ADD COLUMN Source TEXT")
    conn.commit()
    conn.close()


def save_to_db(df, source_name):
    conn = sqlite3.connect(DB_FILE)
    existing = pd.read_sql_query(
        "SELECT Date, Description, Amount, Source FROM transactions", conn
    )
    existing_set = set(
        existing.apply(
            lambda r: (r["Date"], r["Description"], r["Amount"], r["Source"]), axis=1
        )
    )
    to_append = []
    for _, row in df.iterrows():
        key = (row["Date"], row["Description"], row["Amount"], source_name)
        if key not in existing_set:
            to_append.append(
                {
                    "Date": row["Date"],
                    "Description": row["Description"],
                    "Amount": row["Amount"],
                    "Source": source_name,
                }
            )
    if not to_append:
        conn.close()
        return 0
    pd.DataFrame(to_append).to_sql(
        "transactions", conn, if_exists="append", index=False
    )
    conn.close()
    return len(to_append)


def load_from_db():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query(
        "SELECT Date, Description, Amount, Source FROM transactions ORDER BY Date", conn
    )
    conn.close()
    return df


# --- Category Helpers ---
def init_categories():
    if "categories" not in st.session_state:
        st.session_state.categories = {"Uncategorized": []}
    if os.path.exists(CATEGORY_FILE):
        with open(CATEGORY_FILE, "r") as f:
            st.session_state.categories = json.load(f)


def save_categories():
    with open(CATEGORY_FILE, "w") as f:
        json.dump(st.session_state.categories, f)


# --- Categorization Logic ---
def categorize_transactions(df):
    df["Category"] = "Uncategorized"
    for cat, keys in st.session_state.categories.items():
        if cat == "Uncategorized" or not keys:
            continue
        lowered = [k.lower().strip() for k in keys]
        mask = df["Description"].str.lower().str.strip().isin(lowered)
        df.loc[mask, "Category"] = cat
    return df


# --- CSV Parsing ---
def parse_date(val):
    s = str(val).strip()
    parts = s.split()
    if len(parts) == 2:
        yr = datetime.now().year
        today = datetime.now()
        try:
            dt = datetime.strptime(f"{s} {yr}", "%d %b %Y")
            if dt > today:
                dt = dt.replace(year=yr - 1)
            return dt.strftime("%Y-%m-%d")
        except:
            return None
    try:
        return pd.to_datetime(s, errors="coerce").strftime("%Y-%m-%d")
    except:
        return None


# --- Main Application ---
def main():
    init_db()
    init_categories()

    st.title("Simple Finance Dashboard")
    tab_dashboard, tab_raw = st.tabs(["Dashboard", "Raw Data"])

    # Raw Data Tab: uploader, dedupe, category management, and editing
    with tab_raw:
        st.subheader("Upload & Manage Raw Transactions")
        uploaded = st.file_uploader(
            "Upload your transaction CSV file", type=["csv"], key="raw_uploader"
        )
        if uploaded:
            df = pd.read_csv(uploaded)
            df.columns = [c.strip() for c in df.columns]
            if not set(["Amount", "Description"]).issubset(df.columns):
                st.error("CSV must include 'Amount' and 'Description'.")
            else:
                df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce")
                if "Date" in df.columns:
                    df["Date"] = df["Date"].apply(parse_date)
                else:
                    df["Date"] = None
                source_name = os.path.basename(uploaded.name)
                added = save_to_db(df[["Date", "Description", "Amount"]], source_name)
                if added > 0:
                    st.success(f"{added} new transactions added from {source_name}.")
                else:
                    st.info("No new transactions—duplicates skipped.")

        raw_df = load_from_db()
        raw_df = categorize_transactions(raw_df)
        if "Date" in raw_df.columns:
            raw_df["Date"] = pd.to_datetime(raw_df["Date"], errors="coerce")

        # Uploaded Files History
        raw_sources = raw_df["Source"].dropna().unique().tolist()
        with st.expander("Uploaded Files History"):
            if raw_sources:
                for idx, src in enumerate(raw_sources, start=1):
                    st.write(f"{idx}) {src}")
            else:
                st.write("No files uploaded yet.")

        # Manage Categories and Edit Table
        st.subheader("Manage Categories & Edit Raw Transactions")
        new_cat = st.text_input("New Category Name", key="raw_new_cat")
        if st.button("Add Category", key="raw_add_cat") and new_cat:
            st.session_state.categories.setdefault(new_cat, [])
            save_categories()

        if not raw_df.empty:
            # Re-apply categorization so new keywords affect all matching rows
            raw_df = categorize_transactions(raw_df)

            cols = [
                c
                for c in ["Date", "Description", "Amount", "Category", "Source"]
                if c in raw_df.columns
            ]
            edited = st.data_editor(
                raw_df[cols],
                column_config={
                    "Date": st.column_config.DateColumn(format="YYYY-MM-DD"),
                    "Amount": st.column_config.NumberColumn(format="%.2f SGD"),
                    "Category": st.column_config.SelectboxColumn(
                        options=list(st.session_state.categories.keys())
                    ),
                    "Source": st.column_config.TextColumn(),
                },
                hide_index=True,
                use_container_width=True,
                key="raw_editor",
            )
            if st.button("Apply Changes to Raw", key="raw_apply_changes"):
                for i, row in edited.iterrows():
                    cat = row["Category"]
                    desc = row["Description"]
                    if cat != raw_df.at[i, "Category"]:
                        # Add keyword to category for future auto-labeling
                        st.session_state.categories[cat].append(desc)
                save_categories()
                # After saving, re-apply categorization to update all matches
                raw_df = categorize_transactions(raw_df)
                # Write back to session state so editor reflects updates
                st.session_state.expenses_df = raw_df.copy()

        else:
            st.info("No transactions available to edit.")
            st.info("No transactions available to edit.")

    # Dashboard Tab: filtering, summary only
    with tab_dashboard:
        all_df = load_from_db()
        if "Date" in all_df.columns:
            all_df["Date"] = pd.to_datetime(all_df["Date"], errors="coerce")
            all_df["Month"] = all_df["Date"].dt.strftime("%Y-%m")
            months = ["All"] + sorted(
                all_df["Month"].dropna().unique().tolist(), reverse=True
            )
            sel = st.selectbox("Filter by month", months, key="dash_month")
            if sel != "All":
                all_df = all_df[all_df["Month"] == sel]
        all_df = categorize_transactions(all_df)

        # Display non-editable transactions table
        st.subheader("Transactions")
        cols = [
            c
            for c in ["Date", "Description", "Amount", "Category", "Source"]
            if c in all_df.columns
        ]
        if not all_df.empty:
            st.dataframe(
                all_df[cols].sort_values("Date"),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Amount": st.column_config.NumberColumn(format="%.2f SGD")
                },
            )
        else:
            st.info("No transactions to display.")

        st.subheader("Expense Summary")
        tot = all_df.groupby("Category")["Amount"].sum().reset_index()
        tot = tot.sort_values("Amount", ascending=False)

        st.subheader("Expense Summary")
        tot = all_df.groupby("Category")["Amount"].sum().reset_index()
        tot = tot.sort_values("Amount", ascending=False)
        st.dataframe(
            tot,
            use_container_width=True,
            hide_index=True,
            column_config={"Amount": st.column_config.NumberColumn(format="%.2f SGD")},
        )
        fig = px.pie(
            tot, values="Amount", names="Category", title="Expenses by Category"
        )
        st.plotly_chart(fig, use_container_width=True)


if __name__ == "__main__":
    main()
