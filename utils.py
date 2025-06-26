import os, json, pandas as pd
import streamlit as st
from supabase import Client, create_client
from monopoly_parse import parse_pdf

CATEGORY_FILE = "categories.json"

@st.cache_resource(show_spinner=False)
def get_supabase() -> Client:
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

def load_from_db() -> pd.DataFrame:
    sb = get_supabase()
    resp = (
        sb.table("transactions")
          .select("Date, Description, Amount, Currency, Source")
          .order("Date", desc=True)
          .execute()
    )
    data = resp.data or []
    cols = ["Date", "Description", "Amount", "Currency", "Source"]
    if not data:
        return pd.DataFrame(columns=cols)
    # Build DataFrame
    df = pd.DataFrame(data)
    for c in cols:
        if c not in df.columns:
            df[c] = pd.NA
    return df[cols]

def save_to_db(df: pd.DataFrame, source_name: str) -> int:
    sb = get_supabase()
    resp = (
        sb.table("transactions")
          .select("Date,Description,Amount,Currency,Source")
          .execute()
    )
    existing = resp.data or []
    existing_set = {
        (
            r["Date"],
            r["Description"],
            float(r["Amount"]),
            r["Currency"],
            r["Source"],
        )
        for r in existing
    }
    to_insert = []
    for _, row in df.iterrows():
        key = (
            row["Date"],
            row["Description"],
            float(row["Amount"]),
            row["Currency"],
            source_name,
        )
        if key not in existing_set:
            to_insert.append({
                "Date":        row["Date"],
                "Description": row["Description"],
                "Amount":      row["Amount"],
                "Currency":    row["Currency"],
                "Source":      source_name,
            })
    if not to_insert:
        return 0

    sb.table("transactions").insert(to_insert).execute()
    return len(to_insert)

def init_categories():
    with open(CATEGORY_FILE, "r") as f:
        st.session_state.categories = json.load(f)

def save_categories():
    with open(CATEGORY_FILE, "w") as f:
        json.dump(st.session_state.categories, f)

def categorize_transactions(df: pd.DataFrame) -> pd.DataFrame:
    df["Category"] = "Uncategorized"
    for cat, keywords in st.session_state.categories.items():
        if cat == "Uncategorized" or not keywords:
            continue
        lowered = [kw.lower().strip() for kw in keywords]
        mask = df["Description"].str.lower().str.strip().isin(lowered)
        df.loc[mask, "Category"] = cat
    return df
