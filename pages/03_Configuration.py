import os
import json
import pandas as pd
import re
import streamlit as st
from pathlib import Path
from datetime import timedelta
import datetime


from gmail_api import init_gmail_service, get_email_message_details, search_emails
from utils import load_from_db, save_to_db, categorize_transactions, init_categories, save_categories
from dateutil import parser as date_parser
from zoneinfo import ZoneInfo
from email.utils import parsedate_to_datetime

# Page config
st.set_page_config(page_title="Configuration", page_icon="⚙️")
st.title("💰 WeiMeng's Budget Tracker")
st.markdown("## *Configuration*")

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
        dt_sgt = dt_utc.astimezone(ZoneInfo("UTC"))
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
        dt_sgt  = parsed.astimezone(ZoneInfo("UTC"))
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
    start_default = max(min_date, max_date - timedelta(days=7))

    col1, col2 = st.columns(2)
    with col1:
        date_range = st.date_input("Filter by date", [start_default, max_date], key="date_range")
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
            # 2) Load existing raw table & normalize
            raw = load_from_db()[["Date","Description","Amount","Currency","Source"]]
            raw["Date"] = pd.to_datetime(raw["Date"], utc=True).dt.strftime("%Y-%m-%d %H:%M:%S %Z")
            raw["Amount"] = raw["Amount"].astype(float)

            to_add["Date"]   = pd.to_datetime(to_add["Date"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S %Z")
            to_add["Amount"] = to_add["Amount"].astype(float)

            # 3) Anti-join to split new vs duplicates
            merged = to_add.merge(
                raw,
                on=["Date","Description","Amount","Currency","Source"],
                how="left",
                indicator=True
            )

            new_rows = merged[merged["_merge"] == "left_only"].drop(columns=["_merge"])
            dup_rows = merged[merged["_merge"] == "both"].drop(columns=["_merge"])

            # 4) Insert only the new ones
            total = 0
            if not new_rows.empty:
                for source, group in new_rows.groupby("Source"):
                    save_to_db(group.drop(columns=["Source"]), source)
                    total += len(group)

            # 5) Feedback & tables
            if not new_rows.empty:
                st.success(f"Added {total} new transaction{'s' if total>1 else ''}:")
                st.dataframe(new_rows, use_container_width=True)

            if not dup_rows.empty:
                st.warning(f"Skipped {len(dup_rows)} duplicate{'s' if len(dup_rows)>1 else ''}:")
                st.dataframe(dup_rows, use_container_width=True)

            # 6) Preserve checkbox state
            st.session_state[tf_key]["Add?"] = edited["Add?"]

# ───────── Manual Transactions ───────────────────────────────────────────────
st.markdown("---")
st.subheader("📝 Manual Transactions")

# initialize a buffer if not present
if "manual_df" not in st.session_state:
    st.session_state.manual_df = pd.DataFrame(
        columns=["Date","Description","Amount","Currency","Source","Add?","Remove?"]
    )

# 1) ENTRY FORM
with st.form("manual_entry", clear_on_submit=True):
    d = st.date_input("Date")
    t = st.time_input("Time")
    dt = datetime.datetime.combine(d, t)
    desc = st.text_input("Description")
    amt  = st.number_input("Amount", min_value=0.0, format="%.2f")
    curr = st.text_input("Currency", max_chars=3, value="EUR")
    src  = st.selectbox("Source", ["Manual","Manual (Recurring)"])
    submitted = st.form_submit_button("Add to Manual Buffer")
    if submitted:
        st.session_state.manual_df = pd.concat([
            st.session_state.manual_df,
            pd.DataFrame([{
                "Date":        dt,
                "Description": desc,
                "Amount":      amt,
                "Currency":    curr.upper(),
                "Source":      src,
                "Add?":        False,
                "Remove?":     False
            }])
        ], ignore_index=True)
        st.success("Added to manual buffer.")

# 2) SHOW MANUAL BUFFER WITH ADD/REMOVE
if not st.session_state.manual_df.empty:
    st.markdown("**Manual Entries**")
    # sort by date descending
    buf = st.session_state.manual_df.sort_values("Date", ascending=False)
    edited_buf = st.data_editor(
        buf,
        column_config={
          "Add?":    st.column_config.CheckboxColumn("To Add"),
          "Remove?": st.column_config.CheckboxColumn("To Remove")
        },
        hide_index=True,
        use_container_width=True
    )

    # 3) ADD SELECTED
    if st.button("Add Selected Manual → DB"):
        to_add = edited_buf.loc[edited_buf["Add?"]].drop(columns=["Add?","Remove?"])
        if not to_add.empty:
            # reuse your anti‐join + save_to_db logic
            raw = load_from_db()[["Date","Description","Amount","Currency","Source"]]
            raw["Date"]   = pd.to_datetime(raw["Date"], utc=True).dt.strftime("%Y-%m-%d %H:%M:%S %Z")
            raw["Amount"] = raw["Amount"].astype(float)

            to_add["Date"]   = pd.to_datetime(to_add["Date"], utc=True).dt.strftime("%Y-%m-%d %H:%M:%S %Z")
            to_add["Amount"] = to_add["Amount"].astype(float)

            merged = to_add.merge(raw, how="left",
                                  on=["Date","Description","Amount","Currency","Source"],
                                  indicator=True)
            new_rows = merged[merged["_merge"]=="left_only"].drop(columns=["_merge"])
            for source, grp in new_rows.groupby("Source"):
                save_to_db(grp.drop(columns=["Source"]), source)
            st.success(f"Added {len(new_rows)} manual transaction(s).")
        else:
            st.info("No manual rows selected to add.")

    # 4) REMOVE SELECTED
    if st.button("Remove Selected from Buffer"):
        to_remove = edited_buf.loc[edited_buf["Remove?"]].index
        if len(to_remove):
            st.session_state.manual_df = (
                st.session_state.manual_df
                  .drop(to_remove)
                  .reset_index(drop=True)
            )
            st.success(f"Removed {len(to_remove)} row(s) from buffer.")
        else:
            st.info("No rows selected to remove.")

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
        st.rerun()
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
