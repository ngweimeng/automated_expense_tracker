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

st.set_page_config(page_title="Settings", page_icon="⚙️")
st.title("💰 WeiMeng's Budget Tracker")
st.markdown("## *Settings*")

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


# ──────────────── Fetch New Transactions ─────────────────────────────────────
st.markdown("---")
st.subheader("📨 Fetch Wise & Instarem Transactions")

if st.button("Fetch Transactions"):
    service = init_gmail_service(str(creds_path))

    fetched = []
    # Wise
    wise_q = 'from:noreply@wise.com subject:"spent at"'
    for msg in search_emails(service, wise_q, max_results=5):
        d      = get_email_message_details(service, msg["id"])
        dt_utc = parsedate_to_datetime(d["date"])
        dt_sgt = dt_utc.astimezone(ZoneInfo("Asia/Singapore"))
        date_s = dt_sgt.strftime("%Y-%m-%d %H:%M:%S %Z")

        m = re.match(r"([\d.,]+)\s+([A-Z]{3}) spent at (.+)", d["subject"] or "")
        if m:
            amount, currency, merchant = m.group(1), m.group(2), m.group(3).rstrip(".")
        else:
            amount = currency = merchant = "N/A"

        fetched.append({
            "Date":        date_s,
            "Description": merchant,
            "Amount":      amount,
            "Currency":    currency,
            "Source":      "Wise",
            "Add?":        False
        })

    # Instarem
    inst_q = 'from:donotreply@instarem.com subject:"Transaction successful"'
    for msg in search_emails(service, inst_q, max_results=6):
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
        dt_sgt  = parsed.astimezone(ZoneInfo("Asia/Singapore"))
        date_s  = dt_sgt.strftime("%Y-%m-%d %H:%M:%S %Z")

        me = re.search(r'Merchant\s*([^\n]+)', b)
        desc = me.group(1).strip() if me else "N/A"

        pa = re.search(r'Amount paid\s*([\d.,]+\s+[A-Z]{3})', b)
        paid = pa.group(1).strip() if pa else ""
        if paid and " " in paid:
            amount, currency = paid.rsplit(" ", 1)
        else:
            amount = currency = "N/A"

        fetched.append({
            "Date":        date_s,
            "Description": desc,
            "Amount":      amount,
            "Currency":    currency,
            "Source":      "Instarem",
            "Add?":        False
        })

    # Show fetched table with checkbox
    fetched_df = pd.DataFrame(fetched)
    st.markdown("**Fetched Transactions**")
    edited = st.data_editor(
        fetched_df,
        column_config={
            "Add?": st.column_config.CheckboxColumn("Add to Raw")
        },
        hide_index=True,
        use_container_width=True
    )

    # ── Add Selected to Raw Transactions (with dedupe) ────────────────────────
    if st.button("Add Selected to Raw Transactions"):
        to_add = edited.loc[edited["Add?"]].drop(columns=["Add?"])
        if to_add.empty:
            st.info("No transactions selected for adding.")
        else:
            raw = load_from_db()[["Date", "Description", "Amount", "Currency", "Source"]]
            merged = to_add.merge(
                raw,
                on=["Date", "Description", "Amount", "Currency", "Source"],
                how="left",
                indicator=True
            )
            new_rows = merged[merged["_merge"] == "left_only"].drop(columns=["_merge"])
            dup_count = len(to_add) - len(new_rows)

            if not new_rows.empty:
                save_to_db(new_rows, src="fetched")
                st.success(f"Added {len(new_rows)} new transactions.")
            if dup_count:
                st.warning(f"Skipped {dup_count} duplicate{'s' if dup_count>1 else ''}.")
    # ────────────────────────────────────────────────────────────────────────


# ─────────────── Categorize/View Raw Transactions ────────────────────────────
st.markdown("---")
df = load_from_db()
df = categorize_transactions(df)
if "Date" in df:
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

if not df.empty:
    st.subheader("🗂️ Categorize/View Raw Transactions Data")
    edited2 = st.data_editor(
        df[["Date", "Description", "Amount", "Currency", "Category", "Source"]],
        column_config={
            "Category": st.column_config.SelectboxColumn(
                options=list(st.session_state.categories.keys())
            )
        },
        hide_index=True,
        use_container_width=True
    )
    if st.button("Apply Changes to Categories"):
        for idx, row in edited2.iterrows():
            old, new = df.at[idx, "Category"], row["Category"]
            desc = row["Description"]
            if new != old and desc not in st.session_state.categories.get(new, []):
                st.session_state.categories.setdefault(new, []).append(desc)
        save_categories()
        st.experimental_rerun()
else:
    st.info("No transactions available.")

# ─────────────── Current Categories File ─────────────────────────────────────
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
