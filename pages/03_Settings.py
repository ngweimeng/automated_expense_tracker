import os
import json
import pandas as pd
import re
import streamlit as st
from pathlib import Path

from gmail_api import init_gmail_service, get_email_message_details, search_emails
from utils import init_categories, load_from_db, save_to_db, categorize_transactions, save_categories
from monopoly_parse import parse_pdf

from dateutil import parser as date_parser
from zoneinfo import ZoneInfo
from email.utils import parsedate_to_datetime


st.set_page_config(page_title="Settings", page_icon="⚙️")

# ────────────────────────────────────────────────────────────────────────────────
# Setup OAuth files from Streamlit Secrets

# 1) Write client_secret.json
client_secret = st.secrets["gmail"]["client_secret"]
creds_path = Path("/tmp/client_secret.json")
creds_path.write_text(client_secret)

# 2) Ensure token files directory exists, then write token
token_dir  = Path("/tmp") / "token files"
token_dir.mkdir(parents=True, exist_ok=True)
token_file = token_dir / "token_gmail_v1.json"
token_file.write_text(st.secrets["gmail"]["token"])
# ────────────────────────────────────────────────────────────────────────────────

st.title("💰 WeiMeng's Budget Tracker")
st.markdown(
    """
## *Settings*
    """)

init_categories()

# ────────────────────────────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("📤 Upload & Manage Raw Transactions")

pw = st.text_input("Enter password to upload PDF", type="password")
if pw == "weimeng":
    f = st.file_uploader("Upload your credit card statement (PDF only)", type=["pdf"])
    if f:
        os.makedirs("temp_statements", exist_ok=True)
        path = os.path.join("temp_statements", f.name)
        with open(path, "wb") as out:
            out.write(f.read())
        src = f.name
        existing = load_from_db()["Source"].unique().tolist()
        if src in existing:
            st.warning(f"Already uploaded '{src}'.")
        else:
            parsed = parse_pdf(path)
            if parsed.empty:
                st.error("No transactions found.")
            else:
                added = save_to_db(parsed, src)
                st.success(f"{added} new transactions added.")
else:
    if pw:
        st.error("❌ Incorrect password.")

df = load_from_db()
df = categorize_transactions(df)
if "Date" in df:
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

with st.expander("Uploaded Files History"):
    for i, s in enumerate(df["Source"].dropna().unique(), 1):
        st.write(f"{i}) {s}")

if not df.empty:
    st.markdown("---")
    st.subheader("🗂️ Categorize/View Raw Transactions Data")
    edited = st.data_editor(
        df[["Date", "Description", "Amount", "Currency", "Category", "Source"]],
        column_config={
            "Category": st.column_config.SelectboxColumn(
                options=list(st.session_state.categories.keys())
            )
        },
        hide_index=True,
        use_container_width=True
    )
    if st.button("Apply Changes"):
        for idx, row in edited.iterrows():
            old, new = df.at[idx, "Category"], row["Category"]
            desc = row["Description"]
            if new != old and desc not in st.session_state.categories.get(new, []):
                st.session_state.categories.setdefault(new, []).append(desc)
        save_categories()
        st.experimental_rerun()
else:
    st.info("No transactions available to edit.")

# View categories.json
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
    st.error("categories.json not found. No categories to display.")

# ────────────────────────────────────────────────────────────────────────────────
# Fetch Wise & Instarem Transactions
st.markdown("---")
st.subheader("📨 Fetch Wise & Instarem Transactions")

if st.button("Fetch Transactions"):
    service = init_gmail_service(str(creds_path))

    # Wise
    wise_rows = []
    wise_q = 'from:noreply@wise.com subject:"spent at"'
    for msg in search_emails(service, wise_q, max_results=5):
        d = get_email_message_details(service, msg["id"])

        # 1) Parse & convert header date to SGT
        dt_utc = parsedate_to_datetime(d["date"])
        dt_sgt = dt_utc.astimezone(ZoneInfo("Asia/Singapore"))
        formatted = dt_sgt.strftime("%Y-%m-%d %H:%M:%S %Z")

        # 2) Extract amount, currency & merchant from subject
        #    e.g. "8.50 EUR spent at Ready"
        m = re.match(r"([\d.,]+)\s+([A-Z]{3}) spent at (.+)", d["subject"] or "")
        if m:
            amount   = m.group(1)
            currency = m.group(2)
            merchant = m.group(3).rstrip(".")
        else:
            amount = currency = merchant = "N/A"

        wise_rows.append({
            "Date":        formatted,
            "Description": merchant,
            "Amount":      amount,
            "Currency":    currency,
        })

    st.markdown("**Wise Transactions**")
    st.table(wise_rows)

    # Instarem 
    inst_rows = []
    inst_q = 'from:donotreply@instarem.com subject:"Transaction successful"'
    for msg in search_emails(service, inst_q, max_results=6):
        d = get_email_message_details(service, msg["id"])
        b = d["body"]

        # Extract raw date string
        dt_match = re.search(r'Date,?\s*time\s*([^\n]+)', b, re.IGNORECASE)
        raw_dt   = dt_match.group(1).strip() if dt_match else d["date"]

        # Clean ordinal suffix and parse
        clean_dt = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', raw_dt)
        try:
            parsed_dt = date_parser.parse(clean_dt)
        except ValueError:
            parsed_dt = parsedate_to_datetime(d["date"])

        # Make timezone-aware SGT and format
        if not parsed_dt.tzinfo:
            parsed_dt = parsed_dt.replace(tzinfo=ZoneInfo("Asia/Singapore"))
        dt_sgt    = parsed_dt.astimezone(ZoneInfo("Asia/Singapore"))
        formatted = dt_sgt.strftime("%Y-%m-%d %H:%M:%S %Z")

        # Merchant → Description
        me = re.search(r'Merchant\s*([^\n]+)', b)
        description = me.group(1).strip() if me else "N/A"

        # Amount paid → split into amount & currency
        pa = re.search(r'Amount paid\s*([\d.,]+\s+[A-Z]{3})', b)
        paid = pa.group(1).strip() if pa else ""
        if paid and " " in paid:
            amount, currency = paid.rsplit(" ", 1)
        else:
            amount, currency = "N/A", "N/A"

        inst_rows.append({
            "Date":        formatted,
            "Description": description,
            "Amount":      amount,
            "Currency":    currency,
        })

    st.markdown("**Instarem Transactions**")
    st.table(inst_rows)