import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import date
from pandas.tseries.offsets import MonthEnd
from utils import (
    load_from_db,
    categorize_transactions,
    load_category_list,
    load_category_mapping,
    load_recurring
)

today = date.today()
month_label = today.strftime("%B %Y")

# ── 0) Init your categories state ─────────────────────────────────────────────
if "category_list" not in st.session_state:
    st.session_state.category_list = load_category_list()
if "category_map" not in st.session_state:
    st.session_state.category_map = load_category_mapping()

# ── 1) Page setup ─────────────────────────────────────────────────────────────
st.set_page_config(page_title="Dashboard", layout="wide", page_icon="📊")
st.title("💰 WeiMeng's Budget Tracker")

# ── 2) Pick display currency ──────────────────────────────────────────────────
col1, col2 = st.columns(2)
with col1:
    st.markdown("## *Dashboard*")
with col2:
    display_currency = st.selectbox(
        "🔄 Display all amounts in:", ["EUR", "SGD"], index=0
    )
    currency_symbols = {"SGD": "S$", "EUR": "€", "USD": "$", "GBP": "£"}
    symbol = currency_symbols.get(display_currency, display_currency + " ")

# ── 3) Static FX rates (hard-coded) ────────────────────────────────────────────
FX = {
    ("EUR", "SGD"): 1.50,     # 1 EUR → 1.50 SGD
    ("SGD", "EUR"): 1/1.50,   # 1 SGD → 0.67 EUR
}

# ── 4) Load & categorize your raw data ────────────────────────────────────────
df = load_from_db()
df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
df = categorize_transactions(df)

# ── 5) Convert amounts into the chosen display currency ──────────────────────
def convert_to_display(row):
    src = row["Currency"]
    amt = row["Amount"]
    if src == display_currency:
        return amt
    return amt * FX.get((src, display_currency), 1.0)

df["AmtDisplay"] = df.apply(convert_to_display, axis=1)

# ── 6) Bail if no data ────────────────────────────────────────────────────────
valid = df["Date"].dropna()
if valid.empty:
    st.info("No transactions to display.")
    st.stop()

# ── Salary & Budgeting Segment ────────────────────────────────────────────────
st.markdown("---")
st.subheader(f"💼 {month_label}'s Salary & Budgeting")

col_inc, col_bud = st.columns(2)

with col_inc:
    # default monthly net income in EUR
    income_eur = st.number_input(
        "Monthly net income (EUR)",
        min_value=0.0,
        value=4250.0,
        step=50.0,
        format="%.2f"
    )

with col_bud:
    # what % of income they plan to spend
    budget_pct = st.slider(
        "Budget % of income", 
        min_value=0, 
        max_value=100, 
        value=50,    # default 50%
        step=1, 
        format="%d%%"
    )
    # compute the EUR amount and show it live
    budget_amount_eur = income_eur * budget_pct / 100
    st.write(f"➡️ Budgeted spend: €{budget_amount_eur:,.2f} / month")


# ── This Month's Key Metrics ─────────────────────────────────────────────────
st.markdown("---")
st.subheader(f"📅 {month_label}'s Key Metrics")

# current month string
today      = date.today()
curr_month = today.strftime("%Y-%m")

# filter transactions for this month
mask   = df["Date"].dt.to_period("M").astype(str) == curr_month
m_df   = df.loc[mask]

# actual spent in display currency
m_total = m_df["AmtDisplay"].sum()

# compute remaining & saved in display currency
# note: if you want to convert budget_amount_eur→display, you'd need FX here;
# otherwise we assume income/budget in EUR and metrics in EUR.
# To keep everything in your display_currency, you could:
#    rate_eur = FX.get(("EUR", display_currency), 1.0)
#    budget_amount = budget_amount_eur * rate_eur
#    income = income_eur * rate_eur
#    then use those in the metrics below.
# For now we'll show budgets in EUR if display_currency=="EUR", else leave as-is.

if display_currency != "EUR":
    # convert your EUR inputs into display_ccy
    rate_eur = FX.get(("EUR", display_currency), 1.0)
    budget_amount = budget_amount_eur * rate_eur
    income         = income_eur * rate_eur
else:
    budget_amount = budget_amount_eur
    income         = income_eur

m_remaining = budget_amount - m_total
m_saved     = income - m_total

# render the three metrics
mc1, mc2, mc3 = st.columns(3)
mc1.metric(
    "Total Spent This Month",
    f"{symbol}{m_total:,.2f}",
    help=f"{curr_month}-01 to {today}"
)
mc2.metric(
    "Budget Remaining",
    f"{symbol}{m_remaining:,.2f}",
    help=f"{budget_pct}% of {symbol}{income:,.2f} = {symbol}{budget_amount:,.2f}"
)
mc3.metric(
    "Total Saved This Month",
    f"{symbol}{m_saved:,.2f}",
    help="Income minus spend"
)
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


# ───────── Expense summary─────────────────────────────────────────────
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

# ───────── Fixed Costs ─────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("🏠 Fixed Costs")
# load recurring transactions
t = load_recurring()
recur_df = t if isinstance(t, pd.DataFrame) else pd.DataFrame(t)
# categorize recurring items (no Date column expected)
recur_df = categorize_transactions(recur_df)
# convert to display currency
recur_df["AmtDisplay"] = recur_df.apply(convert_to_display, axis=1)
# layout: detailed table and category pie chart
table_col, pie_col = st.columns([1, 1])
with table_col:
    fmt = lambda x: f"{symbol}{x:,.2f}"
    styled_rc = recur_df[["Description", "Category", "AmtDisplay"]]
    styled_rc = styled_rc.style.format({"AmtDisplay": fmt})
    st.dataframe(styled_rc, use_container_width=True)
with pie_col:
    total_fixed = recur_df["AmtDisplay"].sum()
    st.metric("Total Fixed Costs", f"{symbol}{total_fixed:,.2f}")
    rc_pie = px.pie(
        recur_df, values="AmtDisplay", names="Category",
        title="Fixed Costs by Category", hover_data=["AmtDisplay"]
    )
    rc_pie.update_traces(
        hovertemplate="%{label}: " + symbol + "%{value:,.2f} (%{percent})"
    )
    st.plotly_chart(rc_pie, use_container_width=True)

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

    weekly_totals = (
        filtered
        .groupby(["ISOYear","WeekNum"])["AmtDisplay"]
        .sum()
        .reset_index()
    )
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

# build the line chart, now always using "Label" on the x-axis
fig_time = px.line(
    agg_df,
    x="Label",
    y="AmtDisplay",
    title=f"{agg_level} Spending Trend",
    labels={
        "Label":       agg_level,        
        "AmtDisplay":  f"Amount ({display_currency})"
    },
    markers=True
)

# if daily, format the axis as dates
if agg_level == "Daily":
    fig_time.update_xaxes(tickformat="%b %d, %Y")

fig_time.update_yaxes(tickprefix=symbol)

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
