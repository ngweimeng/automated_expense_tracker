import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import date
from pandas.tseries.offsets import MonthEnd
from utils import init_categories, load_from_db, categorize_transactions, load_category_list, load_category_mapping

if "category_list" not in st.session_state:
    st.session_state.category_list = load_category_list()
if "category_map" not in st.session_state:
    st.session_state.category_map  = load_category_mapping()

st.set_page_config(page_title="Dashboard", layout="wide", page_icon="📊")
st.title("💰 WeiMeng's Budget Tracker")
st.markdown("## *Dashboard*")

# 1) Load & categorize your raw data
df = load_from_db()
df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
df = categorize_transactions(df)

# 2) Ask user which currency they want to see everything in
st.markdown("---")
display_currency = st.selectbox(
    "🔄 Display all amounts in:",
    ["SGD", "EUR"],
    index=0
)

currency_symbols = {
    "SGD": "S$",
    "EUR": "€",
    "USD": "$",
    "GBP": "£",
}

symbol = currency_symbols.get(display_currency, display_currency + " ")

# 3) Static FX rates (you can replace with real‐time lookup if you like)
FX = {
    ("EUR","SGD"): 1.50,    # 1 EUR = 1.50 SGD
    ("SGD","EUR"): 1/1.50,  # 1 SGD = 0.67 EUR
}

# 4) Make a converted‐amount column on the fly
def convert(row):
    src = row["Currency"]
    amt = row["Amount"]
    if src == display_currency:
        return amt
    rate = FX.get((src, display_currency))
    # if no rate known, just leave as‐is
    return amt * rate if rate else amt

df["AmtDisplay"] = df.apply(convert, axis=1)

# now carry on using df["AmtDisplay"] instead of df["Amount"]...
valid = df["Date"].dropna()
if valid.empty:
    st.info("No transactions to display.")
    st.stop()

# --Filters-----------------------------------
st.markdown("---")
st.subheader("📊 Dashboard Filters")
# Display current date, week, and month
today = date.today()
iso_year, iso_week, _ = today.isocalendar()
curr_week = f"{iso_year}-W{iso_week:02d}"
curr_month = today.strftime("%Y-%m")
min_data, max_data = valid.min().date(), valid.max().date()

# Layout for info and control columns
control_col, info_col = st.columns([1, 1])
with info_col:
    st.markdown(
        f"**Today:** {today}   \n"
        f"**Current Week:** {curr_week}   \n"
        f"**Current Month:** {curr_month}   \n"
        f"**Data Availiable:** {min_data} to {max_data}."
    )

with control_col:
    filter_type = st.selectbox("Filter by period", ["Date Range", "Month", "Week", "Day"], index=1)

    if filter_type == "Date Range":
        min_d, max_d = valid.min(), valid.max()
        start_d, end_d = st.date_input("Select time period", (min_d, max_d), min_d, max_d)
        filtered = df[(df["Date"] >= pd.to_datetime(start_d)) & (df["Date"] <= pd.to_datetime(end_d))]

    elif filter_type == "Month":
        df["Month"] = df["Date"].dt.to_period("M").astype(str)
        months = sorted(df["Month"].unique())
        selected = st.multiselect("Select month(s)", months, default=[months[-1]])
        filtered = df[df["Month"].isin(selected)]
        if selected:
            first, last = min(selected), max(selected)
            start_d = pd.to_datetime(f"{first}-01")
            end_d = pd.to_datetime(f"{last}-01") + MonthEnd(1)
        else:
            start_d, end_d = valid.min(), valid.max()

    elif filter_type == "Week":
        # ISO Year-Week format
        df["YearWeek"] = df["Date"].dt.strftime("%G-W%V")
        weeks = sorted(df["YearWeek"].unique())
        selected = st.multiselect("Select week(s)", weeks, default=weeks[-1])
        filtered = df[df["YearWeek"].isin(selected)]
        if selected:
            first = selected[0]
            last = selected[-1]
            y1, w1 = first.split("-W")
            y2, w2 = last.split("-W")
            start_d = pd.to_datetime(f"{y1}-W{w1}-1", format="%G-W%V-%u")
            end_d = pd.to_datetime(f"{y2}-W{w2}-1", format="%G-W%V-%u") + pd.Timedelta(days=6)
        else:
            start_d, end_d = valid.min(), valid.max()

    else:  # Day filter
        df["DayStr"] = df["Date"].dt.strftime("%Y-%m-%d")
        days = sorted(df["DayStr"].unique())
        selected = st.multiselect("Select day(s)", days, default=days[-1])
        filtered = df[df["DayStr"].isin(selected)]
        if selected:
            dates = pd.to_datetime(selected)
            start_d, end_d = dates.min(), dates.max()
        else:
            start_d, end_d = valid.min(), valid.max()

# ───────── Key metrics ─────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("🎯 Key Metrics")

total    = filtered["AmtDisplay"].sum()
days     = (end_d - start_d).days + 1
avg      = total / days if days > 0 else 0

cats     = filtered.groupby("Category")["AmtDisplay"].sum()
top_cat, top_amt = (cats.idxmax(), cats.max()) if not cats.empty else ("—", 0.0)

c1, c2, c3 = st.columns(3)
c1.metric(
    "Total Spent",
    f"{symbol}{total:,.2f}",
    border=True,
    help=f"over {days} days"
)
c2.metric(
    "Avg. Daily Spend",
    f"{symbol}{avg:,.2f}",
    border=True,
    help=f"over {days} days"
)
c3.metric(
    "Top Category",
    top_cat,
    f"{symbol}{top_amt:,.2f}",
    border=True,
    help="Category with highest spend"
)

# ───────── Expense summary + pie ─────────────────────────────────────────────
st.markdown("---")
st.subheader("📂 Expense Summary")

piechart_col, dataframe_col = st.columns([1, 1])

with dataframe_col:
    summary = (
        filtered
        .groupby("Category")["AmtDisplay"]
        .sum()
        .reset_index()
        .sort_values("AmtDisplay", ascending=False)
    )
    # append total row
    summary.loc[len(summary)] = ["Total", summary["AmtDisplay"].sum()]

    # format with dynamic symbol
    fmt = lambda x: f"{symbol}{x:,.2f}"
    styled = summary.style.format({"AmtDisplay": fmt})

    st.dataframe(styled, use_container_width=True)

with piechart_col:
    fig = px.pie(
        summary.iloc[:-1],
        values="AmtDisplay",
        names="Category",
        title="Expenses by Category",
        hover_data=["AmtDisplay"]
    )
    # show symbol in hover
    fig.update_traces(
        hovertemplate="%{label}: " + symbol + "%{value:,.2f} (%{percent})"
    )
    st.plotly_chart(fig, use_container_width=True)

# ───────── Spending Over Time ────────────────────────────────────────────────
st.markdown("---")
st.subheader("📈 Spending Over Time")

agg_level = st.selectbox("Aggregate by", ["Daily","Weekly","Monthly"], index=0)

if agg_level == "Daily":
    # 1) floor to midnight so every transaction on the same calendar day collapses
    filtered["Day"] = filtered["Date"].dt.normalize()
    # 2) group by that new column
    agg_df = (
        filtered
        .groupby("Day")["AmtDisplay"]
        .sum()
        .reset_index()
        .rename(columns={"Day": "Date"})
    )
    # 3) use that date-only column for labeling
    agg_df["Label"] = agg_df["Date"].dt.strftime("%Y-%m-%d")

elif agg_level == "Weekly":
    filtered["ISOYear"] = filtered["Date"].dt.isocalendar().year
    filtered["WeekNum"] = filtered["Date"].dt.isocalendar().week

    def week_label(y, w):
        sd = pd.to_datetime(f"{y}-W{w}-1", format="%G-W%V-%u")
        ed = sd + pd.Timedelta(days=6)
        return f"{y}-W{str(w).zfill(2)} ({sd.strftime('%b %d')} – {ed.strftime('%b %d')})"

    week_info = (
        filtered[["ISOYear","WeekNum"]]
        .drop_duplicates()
        .sort_values(["ISOYear","WeekNum"])
        .reset_index(drop=True)
    )
    week_info["Label"] = week_info.apply(
        lambda r: week_label(r["ISOYear"], r["WeekNum"]),
        axis=1
    )

    weekly_totals = filtered.groupby(["ISOYear","WeekNum"])["AmtDisplay"].sum().reset_index()
    agg_df = weekly_totals.merge(week_info, on=["ISOYear","WeekNum"])[["Label","AmtDisplay"]]

else:  # Monthly
    filtered["MonthLabel"] = filtered["Date"].dt.strftime("%B %Y")
    agg_df = (
        filtered
        .groupby("MonthLabel")["AmtDisplay"]
        .sum()
        .reset_index()
        .rename(columns={"MonthLabel":"Label"})
    )

# build the line chart, with dynamic axis title
fig_time = px.line(
    agg_df,
    x="Date",
    y="AmtDisplay",
    title=f"{agg_level} Spending Trend",
    labels={
        "Date":       agg_level,        
        "AmtDisplay": f"Amount ({display_currency})"
    },
    markers=True
)

fig_time.update_xaxes(tickformat="%b %d, %Y")

fig_time.update_yaxes(tickprefix=symbol)

# show the symbol in the hover text too
fig_time.update_traces(
    hovertemplate="%{x}<br>" + symbol + "%{y:,.2f}"
)

st.plotly_chart(fig_time, use_container_width=True)


# ───────── High Expense Alerts ────────────────────────────────────────────────
st.markdown("---")
st.subheader("🚨 High Expense Alerts")

threshold = st.slider(
    f"Highlight transactions above this amount ({display_currency})",
    min_value=0.0,
    max_value=filtered["AmtDisplay"].max() * 1.5,  # or some sane upper‐bound
    value=200.0,
    step=1.0
)

# filter on the converted column
high_df = filtered[filtered["AmtDisplay"] > threshold]

cols = ["Date", "Description", "AmtDisplay", "Category", "Source"]
if not high_df.empty:
    st.warning(
        f"Found {len(high_df)} transaction(s) above "
        f"{display_currency} {threshold:,.2f}"
    )
    st.dataframe(
        high_df[cols],
        use_container_width=True,
        hide_index=True,
        column_config={
            # format each cell with your currency
            "AmtDisplay": st.column_config.NumberColumn(
                format=f"%.2f {display_currency}"
            )
        }
    )
else:
    st.success(
        f"No transactions exceed {display_currency} {threshold:,.2f}"
    )

# ───────── Transactions Table ────────────────────────────────────────────────
st.markdown("---")
st.subheader("🧾 Transactions")

options = ["All"] + sorted(filtered["Category"].unique().tolist())
sel = st.selectbox("Filter by Category", options)

show_df = filtered if sel == "All" else filtered[filtered["Category"] == sel]

if not show_df.empty:
    st.dataframe(
        show_df[["Date", "Description", "AmtDisplay", "Category", "Source"]]
           .sort_values("Date"),
        use_container_width=True,
        column_config={
            "AmtDisplay": st.column_config.NumberColumn(
                format=f"%.2f {display_currency}"
            )
        }
    )
else:
    st.info("No transactions to display.")
