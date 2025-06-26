import os
import json
import pandas as pd
import re
import streamlit as st
from pathlib import Path

from gmail_api import init_gmail_service, get_email_message_details, search_emails
from utils import load_from_db, save_to_db, categorize_transactions, init_categories, save_categories
from dateutil import parser as date_parser
from zoneinfo import ZoneInfo
from email.utils import parsedate_to_datetime

# Page config
st.set_page_config(page_title="Settings", page_icon="⚙️")
st.title("💰 WeiMeng's Budget Tracker")
st.markdown("## *Settings*")

# Initialize categories
init_categories()

# ──────────────── OAuth Setup ────────────────────────────────────────────────
client_secret = st.secrets["gmail"]["client_secret"]
creds_path     = Path("/tmp/client_secret.json")
creds_path.write_text(client_secret)

token_dir  = Path("/tmp") / "token files"
token_dir.mkdir(parents=True, exist_ok=True)
token_file = token_dir / "token_gmail_v1.json"
token_file.write_text(st.secrets["gmail"]["token"])
# ─────────────────────────────────────────────────────────────────────────────

# ───────── Fetch & Add Transactions ───────────────────────────────────────────
st.markdown("---")
st.subheader("📨 Fetch Wise & Instarem Transactions")

# Session storage key for fetched transactions
tf_key = "fetched_df"
if tf_key not in st.session_state:
    st.session_state[tf_key] = pd.DataFrame()

# Fetch new transactions
if st.button("Fetch Transactions", key="fetch"):
    service = init_gmail_service(str(creds_path))
    rows = []
    # Wise
    wise_q = 'from:noreply@wise.com subject:"spent at"'
    for msg in search_emails(service, wise_q, max_results=10):
        d      = get_email_message_details(service, msg["id"])
        dt_utc = parsedate_to_datetime(d["date"])
        dt_sgt = dt_utc.astimezone(ZoneInfo("Europe/Luxembourg"))
        date_s = dt_sgt.strftime("%Y-%m-%d %H:%M:%S %Z")
        m = re.match(r"([\d.,]+)\s+([A-Z]{3}) spent at (.+)", d["subject"] or "")
        if m:
            amount, currency, merchant = m.group(1), m.group(2), m.group(3).rstrip('.')
        else:
            amount = currency = merchant = "N/A"
        rows.append({
            "Date":        date_s,
            "Description": merchant,
            "Amount":      amount,
            "Currency":    currency,
            "Source":      "Wise",
            "Add?":        False
        })
    # Instarem
    inst_q = 'from:donotreply@instarem.com subject:"Transaction successful"'
    for msg in search_emails(service, inst_q, max_results=10):
        d = get_email_message_details(service, msg["id"])
        b = d["body"]
        dtm     = re.search(r'Date,?\s*time\s*([^\n]+)', b, re.IGNORECASE)
        raw_dt  = dtm.group(1).strip() if dtm else d["date"]
        clean   = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', raw_dt)
        try:
            parsed = date_parser.parse(clean)
        except ValueError:
            parsed = parsedate_to_datetime(d["date"])
        if not parsed.tzinfo:
            parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Singapore"))
        dt_sgt  = parsed.astimezone(ZoneInfo("Europe/Luxembourg"))
        date_s  = dt_sgt.strftime("%Y-%m-%d %H:%M:%S %Z")
        me      = re.search(r'Merchant\s*([^\n]+)', b)
        desc    = me.group(1).strip() if me else "N/A"
        pa      = re.search(r'Amount paid\s*([\d.,]+\s+[A-Z]{3})', b)
        paid    = pa.group(1).strip() if pa else ""
        if paid and " " in paid:
            amount, currency = paid.rsplit(" ", 1)
        else:
            amount = currency = "N/A"
        rows.append({
            "Date":        date_s,
            "Description": desc,
            "Amount":      amount,
            "Currency":    currency,
            "Source":      "Instarem",
            "Add?":        False
        })
    st.session_state[tf_key] = pd.DataFrame(rows)

# Display fetched, apply filters, and handle adding
if not st.session_state[tf_key].empty:
    st.markdown("**Fetched Transactions**")
    df_fetched = st.session_state[tf_key].copy()
    # Convert Date column to datetime for filtering
    dates = pd.to_datetime(df_fetched["Date"], errors="coerce", utc=True)
    # Date range and Source filters side by side
    min_date = dates.min().date()
    max_date = dates.max().date()

    col1, col2 = st.columns(2)
    with col1:
        date_range = st.date_input("Filter by date", [min_date, max_date], key="date_range")
        # Ensure two dates are selected
        if not isinstance(date_range, (list, tuple)) or len(date_range) != 2:
            st.error("Please select both a start **and** end date for filtering.")
            # Stop further execution of this block
            st.stop()
    with col2:
        sources = ['All'] + sorted(df_fetched['Source'].unique().tolist())
        selected_source = st.selectbox("Filter by source", sources, key="source_filter")
    # Apply date filter
    mask_date = (dates.dt.date >= date_range[0]) & (dates.dt.date <= date_range[1])
    df_fetched = df_fetched.loc[mask_date]
    # Apply source filter
    if selected_source != 'All':
        df_fetched = df_fetched[df_fetched['Source'] == selected_source]

    # Show editable table
    df_fetched = df_fetched.sort_values("Date", ascending=False)
    edited = st.data_editor(
        df_fetched,
        column_config={"Add?": st.column_config.CheckboxColumn("Add to Raw")},
        hide_index=True,
        use_container_width=True
    )
    # Add selected transactions into db
    if st.button("Add Selected to Raw Transactions", key="add"):
        # 1) Grab only the user-checked rows
        to_add = edited.loc[edited["Add?"]].drop(columns=["Add?"])
        if to_add.empty:
            st.info("No transactions selected for adding.")
        else:
            # 2) Load your existing raw table
            raw = load_from_db()[["Date","Description","Amount","Currency","Source"]]
            raw["Date"] = (
                pd.to_datetime(raw["Date"], utc=True)     
                .dt.tz_convert("Europe/Luxembourg")     # convert to CET/CEST automatically
            )
            
            # 3) Normalize formats on both sides
            for df in (raw, to_add):
                df["Date"]   = pd.to_datetime(df["Date"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S")
                df["Amount"] = df["Amount"].astype(float)
            
            # 4) Do an anti-join: keep only rows not already in raw
            merged = to_add.merge(
                raw,
                on=["Date","Description","Amount","Currency","Source"],
                how="left",
                indicator=True
            )
            new_rows  = merged[merged["_merge"] == "left_only"].drop(columns=["_merge"])
            dup_count = len(to_add) - len(new_rows)

            # 5) Save only the new rows
            total = 0
            if not new_rows.empty:
                for source, group in new_rows.groupby("Source"):
                    save_to_db(group.drop(columns=["Source"]), source)
                    total += len(group)

            # 6) Feedback to user
            if total:
                st.success(f"Added {total} new transaction{'s' if total>1 else ''}.")
            if dup_count:
                st.warning(f"Skipped {dup_count} duplicate{'s' if dup_count>1 else ''}.")

            # 7) Keep the checkboxes as they were
            st.session_state[tf_key]["Add?"] = edited["Add?"]


# ───────── Categorize/View Raw Transactions ─────────────────────────────────
st.markdown("---")
raw_df = load_from_db()
raw_df["Date"] = (
    pd.to_datetime(raw_df["Date"], utc=True)     
      .dt.tz_convert("Europe/Luxembourg")     # convert to CET/CEST automatically
)
cat_df = categorize_transactions(raw_df)
if "Date" in cat_df: cat_df["Date"] = pd.to_datetime(cat_df["Date"], errors='coerce')
if not cat_df.empty:
    st.subheader("🗂️ Categorize/View Raw Transactions Data")
    edited2 = st.data_editor(
        cat_df[["Date","Description","Amount","Currency","Category","Source"]],
        column_config={"Category": st.column_config.SelectboxColumn(
            options=list(st.session_state.categories.keys())
        )},
        hide_index=True,
        use_container_width=True
    )
    if st.button("Apply Changes to Categories"):
        for idx, row in edited2.iterrows():
            old, new = cat_df.at[idx, "Category"], row["Category"]
            desc = row["Description"]
            if new != old and desc not in st.session_state.categories.get(new, []):
                st.session_state.categories.setdefault(new, []).append(desc)
        save_categories()
        st.experimental_rerun()
else:
    st.info("No transactions available.")

# ───────── Current Categories File ───────────────────────────────────────────
st.markdown("---")
st.subheader("📂 Current Categories File")
try:
    with open("categories.json", "r") as f:
        categories = json.load(f)
    st.json(categories)
    st.download_button(
        "Download categories.json",
        data=json.dumps(categories, indent=4),
        file_name="categories.json",
        mime="application/json"
    )
except FileNotFoundError:
    st.error("categories.json not found.")
