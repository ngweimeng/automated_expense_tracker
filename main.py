# main.py

import os
import json
import sqlite3
from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

from pdf_parser import parse_pdf  # your PDF‐parsing module

# ─── Constants ──────────────────────────────────────────────────────────────

DB_FILE = "transactions.db"
CATEGORY_FILE = "categories.json"

st.set_page_config(page_title="Simple Finance App", page_icon="💰", layout="wide")


# ─── Database Helpers ────────────────────────────────────────────────────────


def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Create the base table if it doesn’t exist (Date, Description, Amount only)
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
    # Check which columns currently exist
    c.execute("PRAGMA table_info(transactions)")
    cols = [row[1] for row in c.fetchall()]

    # If "Source" is missing, add it
    if "Source" not in cols:
        c.execute("ALTER TABLE transactions ADD COLUMN Source TEXT")
    # If "Currency" is missing, add it
    if "Currency" not in cols:
        c.execute("ALTER TABLE transactions ADD COLUMN Currency TEXT")

    conn.commit()
    conn.close()


def save_to_db(df: pd.DataFrame, source_name: str) -> int:
    """
    Expects `df` to have columns ["Date","Description","Amount","Currency"].
    Deduplicates based on (Date,Description,Amount,Currency,Source).
    Returns the number of newly inserted rows.
    """
    conn = sqlite3.connect(DB_FILE)
    existing = pd.read_sql_query(
        "SELECT Date, Description, Amount, Currency, Source FROM transactions", conn
    )
    existing_set = set(
        existing.apply(
            lambda r: (
                r["Date"],
                r["Description"],
                r["Amount"],
                r["Currency"],
                r["Source"],
            ),
            axis=1,
        )
    )

    to_append = []
    for _, row in df.iterrows():
        currency = row.get("Currency", None)
        key = (row["Date"], row["Description"], row["Amount"], currency, source_name)
        if key not in existing_set:
            to_append.append(
                {
                    "Date": row["Date"],
                    "Description": row["Description"],
                    "Amount": row["Amount"],
                    "Currency": currency,
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


def load_from_db() -> pd.DataFrame:
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query(
        "SELECT Date, Description, Amount, Currency, Source FROM transactions ORDER BY Date",
        conn,
    )
    conn.close()
    return df


# ─── Category Helpers ────────────────────────────────────────────────────────


def init_categories():
    if "categories" not in st.session_state:
        st.session_state.categories = {"Uncategorized": []}
    if os.path.exists(CATEGORY_FILE):
        with open(CATEGORY_FILE, "r") as f:
            st.session_state.categories = json.load(f)


def save_categories():
    with open(CATEGORY_FILE, "w") as f:
        json.dump(st.session_state.categories, f)


# ─── Categorization Logic ───────────────────────────────────────────────────


def categorize_transactions(df: pd.DataFrame) -> pd.DataFrame:
    df["Category"] = "Uncategorized"
    for cat, keywords in st.session_state.categories.items():
        if cat == "Uncategorized" or not keywords:
            continue
        lowered = [kw.lower().strip() for kw in keywords]
        mask = df["Description"].str.lower().str.strip().isin(lowered)
        df.loc[mask, "Category"] = cat
    return df


# ─── Date Parsing Helper ────────────────────────────────────────────────────


def parse_date(val) -> str | None:
    """
    Normalize a date string like "19 APR" into "YYYY-MM-DD". If that fails,
    fall back to pandas.to_datetime. Return None if parsing cannot succeed.
    """
    s = str(val).strip()
    parts = s.split()
    if len(parts) == 2:
        yr = datetime.now().year
        today = datetime.now()
        try:
            dt = datetime.strptime(f"{s} {yr}", "%d %b %Y")
            if dt > today:
                # If “19 APR 2025” is in the future, assume it was last year
                dt = dt.replace(year=yr - 1)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return None
    try:
        dt = pd.to_datetime(s, errors="coerce")
        if pd.isna(dt):
            return None
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return None


# ─── Main Application ───────────────────────────────────────────────────────


def main():
    init_db()
    init_categories()

    st.title("Simple Finance Dashboard")
    tab_dashboard, tab_raw = st.tabs(["Dashboard", "Raw Data"])

    # ── Raw Data Tab ──────────────────────────────────────────────────────────
    with tab_raw:
        st.subheader("Upload & Manage Raw Transactions")

        # Only accept PDF now
        uploaded_file = st.file_uploader(
            "Upload your credit card statement (PDF only)",
            type=["pdf"],
            key="pdf_uploader",
        )

        if uploaded_file:
            # 1) Save uploaded PDF to a temp folder
            os.makedirs("temp_statements", exist_ok=True)
            temp_path = os.path.join("temp_statements", uploaded_file.name)
            with open(temp_path, "wb") as f:
                f.write(uploaded_file.read())

            source_name = os.path.basename(uploaded_file.name)

            # ── NEW: Skip parsing if this PDF was already processed ───────────────
            existing_sources = load_from_db()["Source"].dropna().unique().tolist()
            if source_name in existing_sources:
                st.warning(
                    f"You’ve already uploaded “{source_name}” before—skipping parse."
                )
            else:
                # 2) Parse the PDF via parse_pdf()
                parsed_df = parse_pdf(temp_path)

                # 3) If parsing produced no rows, show an error
                if parsed_df.empty:
                    st.error("Unable to extract any transactions from that PDF.")
                else:
                    # 4) Normalize date strings into YYYY-MM-DD
                    if "Date" in parsed_df.columns:
                        parsed_df["Date"] = parsed_df["Date"].apply(parse_date)

                    # 5) Save new rows into the database
                    added = save_to_db(parsed_df, source_name)
                    if added > 0:
                        st.success(
                            f"{added} new transactions added from {source_name}."
                        )
                    else:
                        st.info("No new transactions—duplicates were skipped.")

        # ── Show Uploaded Files History ────────────────────────────────────────
        raw_df = load_from_db()
        raw_df = categorize_transactions(raw_df)
        if "Date" in raw_df.columns:
            raw_df["Date"] = pd.to_datetime(raw_df["Date"], errors="coerce")

        raw_sources = raw_df["Source"].dropna().unique().tolist()
        with st.expander("Uploaded Files History"):
            if raw_sources:
                for idx, src in enumerate(raw_sources, start=1):
                    st.write(f"{idx}) {src}")
            else:
                st.write("No files uploaded yet.")

        # ── Manage Categories & Edit Transactions ───────────────────────────────
        st.subheader("Manage Categories & Edit Raw Transactions")
        new_cat = st.text_input("New Category Name", key="raw_new_cat")
        if st.button("Add Category", key="raw_add_cat") and new_cat:
            st.session_state.categories.setdefault(new_cat, [])
            save_categories()

        if not raw_df.empty:
            # Convert Date column for display
            if "Date" in raw_df.columns:
                raw_df["Date"] = pd.to_datetime(
                    raw_df["Date"], format="%Y-%m-%d", errors="coerce"
                )

            # Re-apply categorization to reflect any new keywords
            raw_df = categorize_transactions(raw_df)

            # Columns to show in the editor
            cols = [
                c
                for c in [
                    "Date",
                    "Description",
                    "Amount",
                    "Currency",
                    "Category",
                    "Source",
                ]
                if c in raw_df.columns
            ]

            edited = st.data_editor(
                raw_df[cols],
                column_config={
                    "Date": st.column_config.DateColumn(format="YYYY-MM-DD"),
                    "Description": st.column_config.TextColumn(),
                    "Amount": st.column_config.NumberColumn(format="%.2f"),
                    "Currency": st.column_config.TextColumn(),
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
                    old_cat = raw_df.at[i, "Category"]
                    new_cat_sel = row["Category"]
                    desc = row["Description"]
                    if new_cat_sel != old_cat:
                        st.session_state.categories[new_cat_sel].append(desc)
                save_categories()
                raw_df = categorize_transactions(raw_df)
                st.session_state.expenses_df = raw_df.copy()
        else:
            st.info("No transactions available to edit.")

    # ── Dashboard Tab ────────────────────────────────────────────────────────
    with tab_dashboard:
        all_df = load_from_db()

        if "Date" in all_df.columns:
            all_df["Date"] = pd.to_datetime(all_df["Date"], errors="coerce")

        all_df = categorize_transactions(all_df)

        # If no valid dates, show placeholder and stop
        valid_dates = all_df["Date"].dropna()
        if valid_dates.empty:
            st.info("No transactions to display.")
            st.stop()

        st.subheader("📊 Dashboard Filters")
        min_date = valid_dates.min()
        max_date = valid_dates.max()
        date_range = st.date_input(
            "Select time period",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
        )

        if isinstance(date_range, tuple) and len(date_range) == 2:
            start_date, end_date = date_range
        else:
            st.warning("Please select both a start and end date.")
            st.stop()

        filtered_df = all_df[
            (all_df["Date"] >= pd.to_datetime(start_date))
            & (all_df["Date"] <= pd.to_datetime(end_date))
        ].copy()

        # ── Transactions Table ────────────────────────────────────────────────
        st.markdown("---")
        st.subheader("🧾 Transactions")
        cols = [
            c
            for c in ["Date", "Description", "Amount", "Category", "Source"]
            if c in filtered_df.columns
        ]
        if not filtered_df.empty:
            st.dataframe(
                filtered_df[cols].sort_values("Date"),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Amount": st.column_config.NumberColumn(format="%.2f SGD")
                },
            )
        else:
            st.info("No transactions to display.")

        # ── Expense Summary + Pie Chart ────────────────────────────────────────
        st.markdown("---")
        st.subheader("📂 Expense Summary")
        tot = filtered_df.groupby("Category")["Amount"].sum().reset_index()
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

        # ── Spending Over Time ─────────────────────────────────────────────────
        st.markdown("---")
        st.subheader("📈 Spending Over Time")

        agg_level = st.selectbox(
            "Aggregate by", ["Daily", "Weekly", "Monthly"], index=0
        )

        if agg_level == "Daily":
            agg_df = filtered_df.groupby("Date")["Amount"].sum().reset_index()
            agg_df["Label"] = agg_df["Date"].dt.strftime("%Y-%m-%d")

        elif agg_level == "Weekly":
            filtered_df["ISOYear"] = filtered_df["Date"].dt.isocalendar().year
            filtered_df["WeekNum"] = filtered_df["Date"].dt.isocalendar().week

            def get_week_range_label(year, week):
                start_date = pd.to_datetime(f"{year}-W{week}-1", format="%G-W%V-%u")
                end_date = start_date + pd.Timedelta(days=6)
                return f"{year}-W{str(week).zfill(2)} ({start_date.strftime('%b %d')} – {end_date.strftime('%b %d')})"

            week_info = (
                filtered_df[["ISOYear", "WeekNum"]]
                .drop_duplicates()
                .sort_values(["ISOYear", "WeekNum"])
                .reset_index(drop=True)
            )
            week_info["Label"] = week_info.apply(
                lambda row: get_week_range_label(row["ISOYear"], row["WeekNum"]), axis=1
            )

            weekly_totals = (
                filtered_df.groupby(["ISOYear", "WeekNum"])["Amount"]
                .sum()
                .reset_index()
            )
            agg_df = weekly_totals.merge(
                week_info, on=["ISOYear", "WeekNum"], how="left"
            )
            agg_df = agg_df[["Label", "Amount"]]

        else:  # Monthly
            filtered_df["MonthLabel"] = filtered_df["Date"].dt.strftime("%B %Y")
            agg_df = filtered_df.groupby("MonthLabel")["Amount"].sum().reset_index()
            agg_df.rename(columns={"MonthLabel": "Label"}, inplace=True)

        fig_time = px.line(
            agg_df,
            x="Label",
            y="Amount",
            title=f"{agg_level} Spending Trend",
            labels={"Label": agg_level, "Amount": "Amount (SGD)"},
            markers=True,
        )
        st.plotly_chart(fig_time, use_container_width=True)

        # ── High Expense Alerts ────────────────────────────────────────────────
        st.markdown("---")
        st.subheader("🚨 High Expense Alerts")
        threshold = st.slider(
            "Highlight transactions above this amount (SGD)",
            min_value=10.0,
            max_value=1000.0,
            value=200.0,
            step=10.0,
        )

        high_spend_df = filtered_df[filtered_df["Amount"] > threshold]
        count = len(high_spend_df)

        if count > 0:
            st.warning(f"Found {count} transactions above ${threshold:.2f}")
            st.dataframe(
                high_spend_df[cols],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Amount": st.column_config.NumberColumn(format="%.2f SGD")
                },
            )
        else:
            st.success(f"No transactions exceed ${threshold:.2f}")


if __name__ == "__main__":
    main()
