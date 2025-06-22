import os
import json
import pandas as pd
import streamlit as st
from utils import init_categories, load_from_db, save_to_db, categorize_transactions, save_categories
from monopoly_parse import parse_pdf


st.set_page_config(page_title="Settings", page_icon="⚙️")
st.title("💰 WeiMeng's Budget Tracker")
st.write("Manage your budget categories and upload raw transaction data here.")

init_categories()

st.markdown("---")
st.subheader("📤 Upload & Manage Raw Transactions")
pw = st.text_input("Enter password to upload PDF", type="password")
if pw=="weimeng":
    f = st.file_uploader("Upload your credit card statement (PDF only)", type=["pdf"])
    if f:
        os.makedirs("temp_statements", exist_ok=True)
        path = os.path.join("temp_statements", f.name)
        with open(path, "wb") as out: out.write(f.read())
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
    if pw: st.error("❌ Incorrect password.")

df = load_from_db()
df = categorize_transactions(df)
if "Date" in df: df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

with st.expander("Uploaded Files History"):
    for i, s in enumerate(df["Source"].dropna().unique(), 1):
        st.write(f"{i}) {s}")

if not df.empty:
    st.markdown("---")
    st.subheader("🗂️ Categorize/View Raw Transactions Data")
    edited = st.data_editor(
        df[["Date","Description","Amount","Currency","Category","Source"]],
        column_config={
            "Category": st.column_config.SelectboxColumn(options=list(st.session_state.categories.keys()))
        },
        hide_index=True, use_container_width=True
    )
    if st.button("Apply Changes"):
        for idx, row in edited.iterrows():
            old, new = df.at[idx, "Category"], row["Category"]
            desc = row["Description"]
            if new!=old and desc not in st.session_state.categories.get(new, []):
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
    # Optional: allow download
    st.download_button(
        "Download categories.json",
        data=json.dumps(categories, indent=4),
        file_name="categories.json",
        mime="application/json"
    )
except FileNotFoundError:
    st.error("categories.json not found. No categories to display.")
