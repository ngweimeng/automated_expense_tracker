import os
import json
import pandas as pd
import re
import streamlit as st
from pathlib import Path
from datetime import timedelta
import datetime


from gmail_api import init_gmail_service, get_email_message_details, search_emails
from utils import load_from_db, save_to_db, categorize_transactions, load_recurring, save_recurring_row, delete_recurring, load_category_mapping, load_category_list, upsert_category, delete_category, upsert_keyword, delete_keyword, load_keywords_for
from dateutil import parser as date_parser
from zoneinfo import ZoneInfo
from email.utils import parsedate_to_datetime

# Page config
st.set_page_config(page_title="Configuration", layout="wide", page_icon="⚙️")
st.title("💰 WeiMeng's Budget Tracker")
st.markdown("## *Configuration*")

# Initialize categories
st.session_state.category_map = load_category_mapping()

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
st.subheader("🤖 Step 1: Automatic Import")

with st.expander("Fetch transactions automatically via Gmail API (Wise & Instarem only)", expanded=False):
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
        for msg in search_emails(service, wise_q, max_results=30):
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
col1, col2 = st.columns(2)

with col1:
    st.subheader("📝 Step 2: Manual Entry")

    with st.expander("Add one-off transactions manually", expanded=False):
        # 1) Session‐state buffer for manual entries
        if "manual_df" not in st.session_state:
            st.session_state["manual_df"] = pd.DataFrame(
                columns=["Date","Description","Amount","Currency","Source","Add?"]
            )

        # 2) Form to add into the buffer (not yet DB)
        with st.form("manual_entry", clear_on_submit=True):
            date_val = st.date_input("Date")
            time_val = st.time_input("Time (UTC)")
            dt = datetime.datetime.combine(date_val, time_val)
            desc = st.text_input("Description")
            amt  = st.number_input("Amount", min_value=0.0, format="%.2f")
            curr = st.selectbox("Currency", ["EUR","SGD","USD","GBP"])
            submitted = st.form_submit_button("Enter Transaction")
            if submitted:
                st.session_state["manual_df"] = pd.concat([
                    st.session_state["manual_df"],
                    pd.DataFrame([{
                        "Date":        dt,
                        "Description": desc,
                        "Amount":      amt,
                        "Currency":    curr,
                        "Source":      "Manual",
                        "Add?":        False
                    }])
                ], ignore_index=True)
                st.success("Added successfully to Staging")

        # 3) Display buffer with Add? checkboxes
        if not st.session_state["manual_df"].empty:
            st.markdown("**Manual Transactions in Staging**")

            df_manual = st.session_state["manual_df"].copy()
            # convert to UTC‐aware string for consistent dedupe
            df_manual["Date"] = (
                pd.to_datetime(df_manual["Date"], utc=True)
                .dt.strftime("%Y-%m-%d %H:%M:%S %Z")
            )
            df_manual["Amount"] = df_manual["Amount"].astype(float)
            # sort newest first
            df_manual = df_manual.sort_values("Date", ascending=False)

            edited_manual = st.data_editor(
                df_manual,
                column_config={
                    "Add?": st.column_config.CheckboxColumn("Add to Raw")
                },
                hide_index=True,
                use_container_width=True
            )

            # 4) Add selected into DB with dedupe logic
            if st.button("Add from Staging to Raw", key="add_manual"):
                to_add = edited_manual.loc[edited_manual["Add?"]].drop(columns=["Add?"])
                if to_add.empty:
                    st.info("No manual rows selected to add.")
                else:
                    # load existing for dedupe
                    raw = load_from_db()[["Date","Description","Amount","Currency","Source"]]
                    raw["Date"]   = pd.to_datetime(raw["Date"], utc=True) \
                                    .dt.strftime("%Y-%m-%d %H:%M:%S %Z")
                    raw["Amount"] = raw["Amount"].astype(float)

                    merged = to_add.merge(
                        raw,
                        on=["Date","Description","Amount","Currency","Source"],
                        how="left",
                        indicator=True
                    )
                    new_rows = merged[merged["_merge"]=="left_only"].drop(columns=["_merge"])
                    dup_count = len(to_add) - len(new_rows)

                    # save new ones
                    total = 0
                    if not new_rows.empty:
                        for source, grp in new_rows.groupby("Source"):
                            save_to_db(grp.drop(columns=["Source"]), source)
                            total += len(grp)

                    # feedback + listings
                    if total:
                        st.success(f"Added {total} manual transaction{'s' if total>1 else ''}:")
                        st.dataframe(new_rows, use_container_width=True)
                    if dup_count:
                        st.warning(f"Skipped {dup_count} duplicate{'s' if dup_count>1 else ''}.")

with col2:
    st.subheader("📆 Step 3: Recurring Subscriptions")
    with st.expander("Manage recurring subscriptions", expanded=False):


        # ───────── Active Recurring Definitions ────────────────────────────────────
        st.markdown("**All active subscriptions**")
        recur_df = load_recurring()   # pulls from your Recurring_Transactions table
        if not recur_df.empty:
            # show the list
            display = recur_df.copy().reset_index(drop=True)
            st.data_editor(
                display[["id","Day","Description","Amount","Currency","Source"]],
                column_config={"id": st.column_config.TextColumn("PK", disabled=True)},
                hide_index=True,
                use_container_width=True
            )

            # allow deletion by primary key
            to_delete = st.multiselect(
                "Remove subscriptions (select ID)",
                options=recur_df["id"].tolist(),
                format_func=lambda pk: f"{pk} – {recur_df.loc[recur_df['id']==pk,'Description'].item()}"
            )
            if st.button("Delete Selected", key="rm_recur"):
                delete_recurring(to_delete)
                st.success(f"Deleted {len(to_delete)} subscription{'s' if len(to_delete)>1 else ''}.")
                st.rerun()
        else:
            st.info("No recurring subscriptions defined yet.")

        st.markdown("---")

        # ───────── Add a New Subscription Definition ───────────────────────────────
        st.markdown("**Add a new recurring subscription**")
        with st.form("add_recur", clear_on_submit=True):
            day       = st.number_input("Day of Month", 1, 28, 1)
            desc      = st.text_input("Description")
            amt       = st.number_input("Amount", min_value=0.0, format="%.2f")
            currency  = st.selectbox("Currency", ["EUR","SGD","USD","GBP"])
            submitted = st.form_submit_button("Save Subscription")
            if submitted:
                new_id = save_recurring_row({
                    "day":        int(day),
                    "description": desc,
                    "amount":      float(amt),
                    "currency":    currency,
                    "source":      "Manual Recurring"
                })
                st.success(f"Saved subscription (ID {new_id}).")
                st.rerun()

        # ───────── Auto-Record Today’s Subscriptions ────────────────────────────────
        today      = datetime.datetime.now(tz=ZoneInfo("Europe/Luxembourg"))
        today_day  = today.day
        due        = recur_df.query("Day == @today_day") if not recur_df.empty else pd.DataFrame()

        if not due.empty:
            # Build the list of rows to insert
            rows = []
            for _, r in due.iterrows():
                dt = today.replace(hour=0, minute=0, second=0, microsecond=0)
                rows.append({
                    "Date":        dt,
                    "Description": r["Description"],
                    "Amount":      r["Amount"],
                    "Currency":    r["Currency"],
                    "Source":      r["Source"],
                })

            # Load existing transactions for dedupe
            raw = load_from_db()[["Date","Description","Amount","Currency","Source"]]
            raw["Date"]   = (
                pd.to_datetime(raw["Date"], utc=True)
                .dt.strftime("%Y-%m-%d %H:%M:%S %Z")
            )
            raw["Amount"] = raw["Amount"].astype(float)

            # Normalize and dedupe the new rows
            new_df = pd.DataFrame(rows)
            new_df["Date"]   = (
                pd.to_datetime(new_df["Date"], utc=True)
                .dt.strftime("%Y-%m-%d %H:%M:%S %Z")
            )
            new_df["Amount"] = new_df["Amount"].astype(float)

            merged = new_df.merge(
                raw,
                on=["Date","Description","Amount","Currency","Source"],
                how="left",
                indicator=True
            )
            to_save = merged[merged["_merge"] == "left_only"].drop(columns=["_merge"])

            # Insert without any notifications
            if not to_save.empty:
                for src, grp in to_save.groupby("Source"):
                    save_to_db(grp.drop(columns=["Source"]), src)

# ───────── Manage Categories & Keywords ────────────────────────────────────────
st.markdown("---")
col1, col2 = st.columns(2)

with col1:
    st.subheader("🔧 Step 4: Manage Categories")
    with st.expander("View/Add/Delete Present Categories", expanded=False):

        # 1) Show current categories
        cats = load_category_list()
        if cats:
            st.write("**Existing categories:**", ", ".join(cats))
        else:
            st.info("No categories defined yet.")
        
        # 2) Add a new category
        with st.form("add_category", clear_on_submit=True):
            new_cat = st.text_input("New category name")
            if st.form_submit_button("Create Category") and new_cat:
                upsert_category(new_cat)
                st.success(f"Created category '{new_cat}'")
                st.rerun()

        # 3) Delete selected categories
        to_del = st.multiselect(
            "Delete categories",
            options=cats,
            help="Also deletes all associated keywords"
        )
        if st.button("Delete Selected Categories") and to_del:
            for cat in to_del:
                delete_category(cat)
            st.success(f"Deleted {len(to_del)} category(ies).")
            st.rerun()

with col2:
    st.subheader("🗝️ Step 5: Manage Category Keywords")
    with st.expander("View/Add/Delete Keywords/Descriptions in each Categories", expanded=False):

        # 1) Pick a category to view/edit its keywords
        selected = st.selectbox("Select category", options=cats or [""])
        if selected:
            kw_df = load_keywords_for(selected)
            st.write(f"**Keywords in '{selected}':**")
            if not kw_df.empty:
                st.dataframe(kw_df, use_container_width=True)
            else:
                st.info("No keywords defined for this category.")

            # 2) Add a new keyword
            with st.form("add_keyword", clear_on_submit=True):
                new_kw = st.text_input("New keyword")
                if st.form_submit_button("Add Keyword") and new_kw:
                    upsert_keyword(selected, new_kw)
                    st.success(f"Added keyword '{new_kw}' to '{selected}'")
                    st.rerun()

            # 3) Delete selected keywords
            to_del_kw = st.multiselect(
                "Remove keywords",
                options=kw_df["Keyword"].tolist()
            )
            if st.button("Delete Selected Keywords") and to_del_kw:
                for kw in to_del_kw:
                    delete_keyword(selected, kw)
                st.success(f"Removed {len(to_del_kw)} keyword(s) from '{selected}'")
                st.rerun()

# ───────── Categorize & View Raw Transactions ────────────────────────────────
st.markdown("---")
raw_df = load_from_db()
# Convert stored UTC strings into Europe/Luxembourg tz
raw_df["Date"] = (
    pd.to_datetime(raw_df["Date"], utc=True)
      .dt.tz_convert("Europe/Luxembourg")
)
# Auto-categorize
cat_df = categorize_transactions(raw_df)
if "Date" in cat_df:
    cat_df["Date"] = pd.to_datetime(cat_df["Date"], errors="coerce")

if not cat_df.empty:
    st.subheader("🗂️ Raw Transactions (Categorized)")
    st.dataframe(
        cat_df[["Date", "Description", "Amount", "Currency", "Category", "Source"]],
        use_container_width=True
    )
else:
    st.info("No transactions available.")
