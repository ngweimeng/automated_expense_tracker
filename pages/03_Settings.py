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
        
        # 1) Parse the header date string into a datetime
        dt_utc = parsedate_to_datetime(d["date"])  # yields an aware datetime in UTC
        
        # 2) Convert to Singapore Time (or your desired zone)
        dt_sgt = dt_utc.astimezone(ZoneInfo("Asia/Singapore"))
        
        # 3) Format consistently
        formatted_date = dt_sgt.strftime("%Y-%m-%d %H:%M:%S %Z")
        
        # 4) Extract amount & merchant as before
        m     = re.match(r"([\d.,]+\s+[A-Z]{3}) spent at (.+)", d["subject"] or "")
        amt   = m.group(1) if m else "N/A"
        merch = m.group(2).rstrip(".") if m else "N/A"

        wise_rows.append({
            "Date":     formatted_date,
            "Amount":   amt,
            "Merchant": merch
        })

    st.markdown("**Wise Transactions**")
    st.table(wise_rows)

    # Instarem
    inst_rows = []
    inst_q = 'from:donotreply@instarem.com subject:"Transaction successful"'
    for msg in search_emails(service, inst_q, max_results=6):
        d = get_email_message_details(service, msg["id"])
        b = d["body"]

        # extract the raw date string
        dt_match = re.search(r'Date,?\s*time\s*([^\n]+)', b, re.IGNORECASE)
        raw_dt   = dt_match.group(1).strip() if dt_match else d["date"]

        # 1) remove ordinal suffix on the day (e.g. '24th' → '24')
        raw_dt = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', raw_dt)

        # 2) parse into a datetime
        try:
            parsed_dt = date_parser.parse(raw_dt)
        except ValueError:
            # fallback to header date parse
            from email.utils import parsedate_to_datetime
            parsed_dt = parsedate_to_datetime(d["date"])

        # 3) format consistently
        formatted_dt = parsed_dt.strftime('%Y-%m-%d %H:%M:%S %Z')

        # extract amounts & merchant
        ta = re.search(r'Transaction amount\s*([\d.,]+\s+[A-Z]{3})', b)
        pa = re.search(r'Amount paid\s*([\d.,]+\s+[A-Z]{3})',       b)
        me = re.search(r'Merchant\s*([^\n]+)',                     b)

        inst_rows.append({
            "Date":              formatted_dt,
            "Transaction amt":   ta.group(1).strip() if ta else "N/A",
            "Amount paid":       pa.group(1).strip() if pa else "N/A",
            "Merchant":          me.group(1).strip() if me else "N/A"
        })

    st.markdown("**Instarem Transactions**")
    st.table(inst_rows)