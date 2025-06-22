import streamlit as st
import pandas as pd
import plotly.express as px
from utils import init_categories, load_from_db, categorize_transactions

st.set_page_config(page_title="Dashboard", page_icon="📊")
st.title("💰 WeiMeng's Budget Tracker")
st.write("View spending patterns and key metrics here.")

init_categories()

df = load_from_db()
if "Date" in df.columns:
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
df = categorize_transactions(df)

valid = df["Date"].dropna()
if valid.empty:
    st.info("No transactions to display.")
    st.stop()

# Filters
st.markdown("---")
st.subheader("📊 Dashboard Filters")
min_d, max_d = valid.min(), valid.max()
start_d, end_d = st.date_input("Select time period", (min_d, max_d), min_d, max_d)

filtered = df[(df["Date"]>=pd.to_datetime(start_d)) & (df["Date"]<=pd.to_datetime(end_d))]

# Key metrics
st.markdown("---")
st.subheader("🎯 Key Metrics")
total = filtered["Amount"].sum()
days = (end_d - start_d).days + 1
avg = total/days if days>0 else 0

cats = filtered.groupby("Category")["Amount"].sum()
top_cat, top_amt = (cats.idxmax(), cats.max()) if not cats.empty else ("—", 0.0)
c1, c2, c3 = st.columns(3)
c1.metric("Total Spent", f"SGD {total:,.2f}")
c2.metric("Avg. Daily Spend", f"SGD {avg:,.2f}", help=f"over {days} days")
c3.metric("Top Category", top_cat, f"SGD {top_amt:,.2f}")

# Transactions table
st.markdown("---")
st.subheader("🧾 Transactions")
options = ["All"] + sorted(filtered["Category"].unique().tolist())
sel = st.selectbox("Filter by Category", options)
show_df = filtered if sel=="All" else filtered[filtered["Category"]==sel]
if not show_df.empty:
    st.dataframe(show_df[["Date","Description","Amount","Category","Source"]].sort_values("Date"), use_container_width=True)
else:
    st.info("No transactions to display.")

# Expense summary + pie
st.markdown("---")
st.subheader("📂 Expense Summary")
summary = filtered.groupby("Category")["Amount"].sum().reset_index().sort_values("Amount", ascending=False)
summary.loc[len(summary)] = ["Total", summary["Amount"].sum()]
st.dataframe(summary.style.format({"Amount":"{:.2f} SGD"}), use_container_width=True)
fig = px.pie(summary.iloc[:-1], values="Amount", names="Category", title="Expenses by Category")
st.plotly_chart(fig, use_container_width=True)

# Spending Over Time
st.markdown("---")
st.subheader("📈 Spending Over Time")
agg_level = st.selectbox("Aggregate by", ["Daily","Weekly","Monthly"], index=0)
# daily
if agg_level=="Daily":
    agg_df = filtered.groupby("Date")["Amount"].sum().reset_index()
    agg_df["Label"] = agg_df["Date"].dt.strftime("%Y-%m-%d")
# weekly
elif agg_level=="Weekly":
    filtered["ISOYear"] = filtered["Date"].dt.isocalendar().year
    filtered["WeekNum"] = filtered["Date"].dt.isocalendar().week
    def week_label(y,w):
        sd = pd.to_datetime(f"{y}-W{w}-1", format="%G-W%V-%u")
        ed = sd + pd.Timedelta(days=6)
        return f"{y}-W{str(w).zfill(2)} ({sd.strftime('%b %d')} – {ed.strftime('%b %d')})"
    week_info = (filtered[["ISOYear","WeekNum"]].drop_duplicates().sort_values(["ISOYear","WeekNum"]).reset_index(drop=True))
    week_info["Label"] = week_info.apply(lambda r: week_label(r["ISOYear"],r["WeekNum"]), axis=1)
    weekly_totals = filtered.groupby(["ISOYear","WeekNum"])["Amount"].sum().reset_index()
    agg_df = weekly_totals.merge(week_info, on=["ISOYear","WeekNum"])[["Label","Amount"]]
# monthly
else:
    filtered["MonthLabel"] = filtered["Date"].dt.strftime("%B %Y")
    agg_df = filtered.groupby("MonthLabel")["Amount"].sum().reset_index().rename(columns={"MonthLabel":"Label"})
fig_time = px.line(agg_df, x="Label", y="Amount", title=f"{agg_level} Spending Trend", labels={"Label":agg_level, "Amount":"Amount (SGD)"}, markers=True)
st.plotly_chart(fig_time, use_container_width=True)

# High Expense Alerts
st.markdown("---")
st.subheader("🚨 High Expense Alerts")
threshold = st.slider("Highlight transactions above this amount (SGD)", min_value=10.0, max_value=1000.0, value=200.0, step=10.0)
high_df = filtered[filtered["Amount"] > threshold]
cols = ["Date", "Description", "Amount", "Category", "Source"]
if not high_df.empty:
    st.warning(f"Found {len(high_df)} transactions above ${threshold:.2f}")
    st.dataframe(high_df[cols], use_container_width=True, hide_index=True,
                    column_config={"Amount": st.column_config.NumberColumn(format="%.2f SGD")})
else:
    st.success(f"No transactions exceed ${threshold:.2f}")
