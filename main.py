import os
import json
import sqlite3

import pandas as pd
import plotly.express as px
import streamlit as st

from monopoly_parse import parse_pdf

# ─── Constants ──────────────────────────────────────────────────────────────

DB_FILE = "transactions.db"
CATEGORY_FILE = "categories.json"

st.set_page_config(page_title="WeiMeng's Finance App", page_icon="💰", layout="wide")


# ─── Database Helpers ────────────────────────────────────────────────────────


def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            Date TEXT,
            Description TEXT,
            Amount REAL,
            Source TEXT,
            Currency TEXT
        )
        """
    )
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
        key = (
            row["Date"],
            row["Description"],
            row["Amount"],
            row["Currency"],
            source_name,
        )
        if key not in existing_set:
            to_append.append(
                {
                    "Date": row["Date"],
                    "Description": row["Description"],
                    "Amount": row["Amount"],
                    "Currency": row["Currency"],
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


# ─── Main Application ───────────────────────────────────────────────────────


def main():
    init_db()
    init_categories()

    st.title("💰WeiMeng's Finance Dashboard")
    tab_dashboard, tab_raw = st.tabs(["Dashboard", "Raw Data"])

    with tab_raw:
        st.subheader("Upload & Manage Raw Transactions")

        uploaded_file = st.file_uploader(
            "Upload your credit card statement (PDF only)",
            type=["pdf"],
            key="pdf_uploader",
        )

        if uploaded_file:
            os.makedirs("temp_statements", exist_ok=True)
            temp_path = os.path.join("temp_statements", uploaded_file.name)
            with open(temp_path, "wb") as f:
                f.write(uploaded_file.read())

            source_name = uploaded_file.name
            existing_sources = load_from_db()["Source"].dropna().unique().tolist()
            if source_name in existing_sources:
                st.warning(f"You’ve already uploaded '{source_name}'—skipping parse.")
            else:
                parsed_df = parse_pdf(temp_path)
                if parsed_df.empty:
                    st.error("Unable to extract any transactions from that PDF.")
                else:
                    added = save_to_db(parsed_df, source_name)
                    if added > 0:
                        st.success(
                            f"{added} new transactions added from {source_name}."
                        )
                    else:
                        st.info("No new transactions—duplicates were skipped.")

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

        if not raw_df.empty:
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
                    "Date": st.column_config.DateColumn(
                        format="YYYY-MM-DD", disabled=True
                    ),
                    "Description": st.column_config.TextColumn(disabled=True),
                    "Amount": st.column_config.NumberColumn(
                        format="%.2f", disabled=True
                    ),
                    "Currency": st.column_config.TextColumn(disabled=True),
                    "Category": st.column_config.SelectboxColumn(
                        options=list(st.session_state.categories.keys())
                    ),
                    "Source": st.column_config.TextColumn(disabled=True),
                },
                hide_index=True,
                use_container_width=True,
                key="raw_editor",
            )
            if st.button("Apply Changes to Raw", key="raw_apply_changes"):
                for i, row in edited.iterrows():
                    old_cat = raw_df.at[i, "Category"]
                    new_cat = row["Category"]
                    desc = row["Description"]
                    if new_cat != old_cat:
                        if desc not in st.session_state.categories.get(new_cat, []):
                            st.session_state.categories.setdefault(new_cat, []).append(
                                desc
                            )
                save_categories()
                st.rerun()
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

        # ── Metrics ─────────────────────────────────
        st.markdown("---")
        st.subheader("🎯 Key Metrics")
        total_spend = filtered_df["Amount"].sum()
        # 2) compute number of days in the selected range
        #    (date_range is a tuple of two datetime.date objects)
        period_days = (end_date - start_date).days + 1
        avg_daily = total_spend / period_days if period_days > 0 else 0

        # 3) find top‐spending category
        cat_totals = filtered_df.groupby("Category")["Amount"].sum()
        if not cat_totals.empty:
            top_cat = cat_totals.idxmax()
            top_amt = cat_totals.max()
        else:
            top_cat, top_amt = "—", 0.0

        # 4) render three metrics side by side
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Spent", f"SGD {total_spend:,.2f}", border=True)
        m2.metric(
            "Avg. Daily Spend",
            f"SGD {avg_daily:,.2f}",
            help=f"over {period_days} days",
            border=True,
        )
        m3.metric("Top Category", top_cat, f"SGD {top_amt:,.2f}", border=True)

        # ── Transactions Table ────────────────────────────────────────────────
        st.markdown("---")
        st.subheader("🧾 Transactions")

        categories = ["All"] + sorted(
            filtered_df["Category"].dropna().unique().tolist()
        )
        selected_category = st.selectbox(
            "Filter by Category",
            categories,
            index=0,
            help="Show only transactions in this category",
        )

        if selected_category != "All":
            df_to_show = filtered_df[filtered_df["Category"] == selected_category]
        else:
            df_to_show = filtered_df

        cols = [
            c
            for c in ["Date", "Description", "Amount", "Category", "Source"]
            if c in df_to_show.columns
        ]
        if not df_to_show.empty:
            st.dataframe(
                df_to_show[cols].sort_values("Date"),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Date": st.column_config.DateColumn(format="YYYY-MM-DD"),
                    "Amount": st.column_config.NumberColumn(format="%.2f SGD"),
                },
            )
        else:
            st.info("No transactions to display.")

        # ── Expense Summary + Pie Chart ────────────────────────────────────────
        st.markdown("---")
        st.subheader("📂 Expense Summary")
        tot = filtered_df.groupby("Category")["Amount"].sum().reset_index()
        tot = tot.sort_values("Amount", ascending=False)
        display_df = tot.copy()
        display_df.loc[len(display_df)] = ["Total", display_df["Amount"].sum()]

        def highlight_total(row):
            if row.name == display_df.index[-1]:
                return ["background-color: #e0f7fa; font-weight: bold;" for _ in row]
            return ["" for _ in row]

        styled = display_df.style.apply(highlight_total, axis=1).format(
            {"Amount": "{:.2f} SGD"}
        )

        st.dataframe(
            styled,
            use_container_width=True,
            hide_index=True,
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
