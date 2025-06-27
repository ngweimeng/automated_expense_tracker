import os, json, pandas as pd
import streamlit as st
from supabase import Client, create_client
from monopoly_parse import parse_pdf
from typing import List, Dict

RECUR_FILE = "recurring.json"
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
    # grab your flat mapping: Description → Category
    mapping: pd.Series = st.session_state.category_map  
    # create a boolean mask of exact matches
    mask = df["Description"].isin(mapping.index)
    # map those descriptions to their category
    df.loc[mask, "Category"] = df.loc[mask, "Description"].map(mapping)
    return df

def load_recurring() -> pd.DataFrame:
    """Fetch all active recurring definitions from Supabase."""
    sb   = get_supabase()
    resp = (
        sb.table("recurring")
          .select('"id","Day","Description","Amount","Currency","Source"')
          .order("Day", desc=False)
          .execute()
    )
    data = resp.data or []
    df   = pd.DataFrame(data)
    # If empty, just return the empty DataFrame (with those columns auto-set)
    if df.empty:
        return df
    # Otherwise ensure column order
    return df[["id","Day","Description","Amount","Currency","Source"]]

def save_recurring_row(row: dict) -> int:
    """Insert a new recurring definition; returns the new row's Id."""
    sb = get_supabase()
    # Build your payload using the exact capitalized column names
    payload = {
        "Day":         int(row["day"]),
        "Description": row["description"],
        "Amount":      float(row["amount"]),
        "Currency":    row["currency"],
        "Source":      row.get("source", "Manual Recurring"),
    }
    resp = sb.table("recurring").insert(payload).execute()
    # Supabase returns the inserted row, now under "Id"
    return resp.data[0]["id"]

def delete_recurring(ids: List[int]) -> None:
    """Delete the recurring definitions with the given primary keys."""
    sb = get_supabase()
    for rid in ids:
        sb.table("recurring")\
          .delete()\
          .eq("Id", rid)\
          .execute()

def load_category_list() -> List[str]:
    """Return a list of all category names from Supabase."""
    sb = get_supabase()
    data = sb.table("categories").select('"Name"').order("Name").execute().data or []
    return [r["Name"] for r in data]

def load_keywords_for(category: str) -> pd.DataFrame:
    """Return a DataFrame with a single column 'Keyword' for the given category."""
    sb = get_supabase()

    # 1) Find the category’s Id
    resp_cat = (
        sb.table("categories")        # note exact table name with proper casing
          .select("Id")
          .eq("Name", category)
          .execute()
    )
    cat_rows = resp_cat.data or []
    if not cat_rows:
        # no such category
        return pd.DataFrame(columns=["Keyword"])

    cat_id = cat_rows[0]["Id"]

    # 2) Fetch keywords for that Id
    resp_kw = (
        sb.table("category_keywords")  # exact name of your keywords table
          .select("Keyword")
          .eq("Category_Id", cat_id)
          .order("Keyword", desc=False)
          .execute()
    )
    kw_rows = resp_kw.data or []
    if not kw_rows:
        # category exists but has no keywords
        return pd.DataFrame(columns=["Keyword"])

    # 3) Build DataFrame directly
    df = pd.DataFrame(kw_rows)

    # 4) Ensure exactly one column named "Keyword"
    #    (if your Supabase column really is "Keyword", this is already correct)
    if "Keyword" not in df.columns:
        raise RuntimeError(f"Expected column 'Keyword' in response but got {df.columns.tolist()}")

    return df[["Keyword"]]

def upsert_category(name: str) -> int:
    """Create a new category if missing; return its Id."""
    sb = get_supabase()
    # upsert by Name
    resp = sb.table("categories").upsert({"Name": name}, on_conflict="Name").execute()
    return resp.data[0]["Id"]

def delete_category(name: str) -> None:
    """Delete a category and all its keywords."""
    sb = get_supabase()
    sb.table("categories").delete().match({"Name": name}).execute()

def upsert_keyword(category: str, keyword: str) -> None:
    """Add a keyword under a category (creating the category if needed)."""
    sb = get_supabase()
    # get or create category
    cat_id = upsert_category(category)
    sb.table("category_keywords")\
    .upsert(
        {"Category_Id": cat_id, "Keyword": keyword}
    ).execute()

def delete_keyword(category: str, keyword: str) -> None:
    """Remove a specific keyword from a category."""
    sb = get_supabase()
    # find the category id
    cat = sb.table("categories").select("Id").eq("Name", category).execute().data or []
    if not cat:
        return
    sb.table("category_keywords")\
      .delete()\
      .match({"Category_Id": cat[0]["Id"], "Keyword": keyword})\
      .execute()

def load_category_mapping() -> pd.Series:
    """
    Fetch the flat mapping of merchant Description→Category
    by reading Categories and Category_Keywords from Supabase.
    Returns a pandas Series indexed by Description, with values Category.
    """
    sb: Client = get_supabase()
    # 1) Load all categories
    cat_rows = sb.table("categories").select("Id,Name").execute().data or []
    id2name: Dict[int,str] = {r["Id"]: r["Name"] for r in cat_rows}

    # 2) Load all keywords
    kw_rows = sb.table("category_keywords") \
                .select("Category_Id,Keyword") \
                .execute().data or []

    # 3) Build mapping dict
    mapping: Dict[str,str] = {
        row["Keyword"]: id2name[row["Category_Id"]]
        for row in kw_rows
        if row["Category_Id"] in id2name
    }

    # 4) Return as a Series
    if not mapping:
        return pd.Series(dtype="object")
    return pd.Series(mapping, name="Category")