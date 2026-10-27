"""Northwind Traders - Sales Analytics dashboard.

Run with:  streamlit run app.py
"""
from __future__ import annotations

import calendar
from datetime import timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import data_model as dm

st.set_page_config(page_title="Northwind Traders - Sales Analytics", page_icon="📊", layout="wide")

BLUE = "#2563eb"
ORANGE = "#ea580c"
CATEGORICAL = px.colors.qualitative.Safe


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def money(x: float) -> str:
    return f"${x:,.0f}"


def style(fig, title: str | None = None, height: int = 380):
    fig.update_layout(
        template="plotly_white",
        title=title,
        height=height,
        margin=dict(l=10, r=10, t=55 if title else 20, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    return fig


def show(fig):
    """st.plotly_chart across Streamlit versions."""
    try:
        st.plotly_chart(fig, width="stretch")
    except TypeError:
        st.plotly_chart(fig, use_container_width=True)


def table(df: pd.DataFrame, money_cols=(), pct_cols=(), height: int | None = None):
    cfg = {}
    for c in money_cols:
        if c in df.columns:
            cfg[c] = st.column_config.NumberColumn(format="$%.0f")
    for c in pct_cols:
        if c in df.columns:
            cfg[c] = st.column_config.NumberColumn(format="%.1f%%")
    kwargs = dict(hide_index=True, column_config=cfg)
    if height:
        kwargs["height"] = height
    try:
        st.dataframe(df, width="stretch", **kwargs)
    except TypeError:
        st.dataframe(df, use_container_width=True, **kwargs)


# --------------------------------------------------------------------------
# Data loading (cached)
# --------------------------------------------------------------------------
@st.cache_data(show_spinner="Loading and joining the 7 tables...")
def load(data_dir: str):
    tables = dm.load_tables(data_dir)
    fact = dm.build_fact(tables)
    return tables, fact


st.sidebar.title("📊 Northwind Traders")
default_dir = dm.find_data_dir() or ""
data_dir = st.sidebar.text_input("Folder with the CSV files", value=default_dir)
if not data_dir or dm.find_data_dir(data_dir) is None:
    st.error(
        "Could not find all 7 CSV files (" + ", ".join(t + ".csv" for t in dm.TABLES) + "). "
        "Put them in a `data/` folder next to app.py, or type the folder path in the sidebar."
    )
    st.stop()

tables, fact = load(dm.find_data_dir(data_dir))


# --------------------------------------------------------------------------
# Sidebar filters (applied to the joined table, so every chart respects them)
# --------------------------------------------------------------------------
st.sidebar.header("Filters")
min_d, max_d = fact["orderDate"].min().date(), fact["orderDate"].max().date()
picked = st.sidebar.date_input("Order date range", (min_d, max_d), min_value=min_d, max_value=max_d)
if isinstance(picked, (tuple, list)) and len(picked) == 2:
    d0, d1 = pd.Timestamp(picked[0]), pd.Timestamp(picked[1])
else:
    d0, d1 = pd.Timestamp(min_d), pd.Timestamp(max_d)


def pick(label: str, col: str):
    options = sorted(fact[col].dropna().unique().tolist())
    return st.sidebar.multiselect(label, options, default=options)


sel_country = pick("Customer country", "customerCountry")
sel_cat = pick("Category", "categoryName")
sel_emp = pick("Employee", "employeeName")
sel_ship = pick("Shipper", "shipperName")

base = fact[
    fact["customerCountry"].isin(sel_country)
    & fact["categoryName"].isin(sel_cat)
    & fact["employeeName"].isin(sel_emp)
    & fact["shipperName"].isin(sel_ship)
]
f = base[(base["orderDate"] >= d0) & (base["orderDate"] <= d1)]

st.title("Northwind Traders - Sales Analytics")
st.caption(
    f"{d0:%d %b %Y} to {d1:%d %b %Y} · {len(f):,} order lines · "
    "revenue = unit price × quantity × (1 − discount)"
)

if f.empty:
    st.warning("No data for the current filters. Widen the date range or re-select some filter values.")
    st.stop()

orders = dm.orders_from_fact(f)


def kpis(frame: pd.DataFrame) -> dict:
    o = dm.orders_from_fact(frame) if len(frame) else frame
    if len(frame) == 0:
        return dict(revenue=0.0, orders=0, customers=0, aov=float("nan"), units=0, freight=0.0,
                    on_time=float("nan"), disc=float("nan"))
    shipped = o[o["shippedDate"].notna()]
    n = o["orderID"].nunique()
    return dict(
        revenue=frame["revenue"].sum(),
        orders=n,
        customers=o["customerID"].nunique(),
        aov=frame["revenue"].sum() / n,
        units=int(frame["quantity"].sum()),
        freight=o["freight"].sum(),
        on_time=1 - shipped["lateFlag"].mean() if len(shipped) else float("nan"),
        disc=frame["discountAmt"].sum() / frame["gross"].sum(),
    )


cur = kpis(f)
span = (d1 - d0).days + 1
prev_frame = base[(base["orderDate"] >= d0 - timedelta(days=span)) & (base["orderDate"] < d0)]
prev = kpis(prev_frame) if len(prev_frame) else None


def delta(key: str):
    if prev is None or not prev[key] or pd.isna(prev[key]):
        return None
    return f"{(cur[key] - prev[key]) / prev[key]:+.1%}"


tab_names = ["Overview", "Sales trends", "Products & categories", "Customers & geography",
             "Employees", "Shipping & delivery", "Data & model"]
tabs = st.tabs(tab_names)

# ==========================================================================
# 1. OVERVIEW
# ==========================================================================
with tabs[0]:
    c = st.columns(4)
    c[0].metric("Revenue", money(cur["revenue"]), delta("revenue"), help="Change vs the previous period of the same length")
    c[1].metric("Orders", f"{cur['orders']:,}", delta("orders"))
    c[2].metric("Avg order value", money(cur["aov"]), delta("aov"))
    c[3].metric("Active customers", f"{cur['customers']:,}", delta("customers"))
    c = st.columns(4)
    c[0].metric("Units sold", f"{cur['units']:,}")
    c[1].metric("Freight cost", money(cur["freight"]))
    c[2].metric("Avg discount given", f"{cur['disc']:.1%}")
    c[3].metric("Shipped on time", "n/a" if pd.isna(cur["on_time"]) else f"{cur['on_time']:.1%}")

    m = (
        f.groupby("orderMonth")
        .agg(Revenue=("revenue", "sum"), Orders=("orderID", "nunique"))
        .reset_index()
    )
    fig = go.Figure()
    fig.add_bar(x=m["orderMonth"], y=m["Revenue"], name="Revenue", marker_color=BLUE)
    fig.add_scatter(x=m["orderMonth"], y=m["Orders"], name="Orders", yaxis="y2",
                    mode="lines+markers", line=dict(color=ORANGE))
    fig.update_layout(yaxis=dict(title="Revenue ($)"),
                      yaxis2=dict(title="Orders", overlaying="y", side="right", showgrid=False))
    show(style(fig, "Monthly revenue and order count"))

    left, right = st.columns(2)
    cat = f.groupby("categoryName", as_index=False)["revenue"].sum().sort_values("revenue", ascending=False)
    with left:
        fig = px.pie(cat, names="categoryName", values="revenue", hole=0.5,
                     color_discrete_sequence=CATEGORICAL)
        fig.update_traces(textinfo="percent+label", sort=False)
        fig.update_layout(showlegend=False)
        show(style(fig, "Revenue by category"))
    with right:
        ctry = (f.groupby("customerCountry", as_index=False)["revenue"].sum()
                .sort_values("revenue", ascending=False).head(10).iloc[::-1])
        fig = px.bar(ctry, x="revenue", y="customerCountry", orientation="h",
                     color_discrete_sequence=[BLUE])
        fig.update_layout(xaxis_title="Revenue ($)", yaxis_title=None)
        show(style(fig, "Top 10 countries by revenue"))

    st.subheader("Key takeaways")
    bullets = []
    mm = f.groupby("orderMonth")["revenue"].sum()
    bullets.append(f"**Best month:** {mm.idxmax():%B %Y} with {money(mm.max())} in revenue.")
    cs = f.groupby("categoryName")["revenue"].sum().sort_values(ascending=False)
    bullets.append(f"**Top category:** {cs.index[0]} brings {cs.iloc[0] / cs.sum():.0%} of revenue.")
    cn = f.groupby("customerCountry")["revenue"].sum().sort_values(ascending=False)
    bullets.append(f"**Top market:** {cn.index[0]} ({cn.iloc[0] / cn.sum():.0%} of revenue); "
                   f"the top 3 countries make up {cn.head(3).sum() / cn.sum():.0%}.")
    cu = f.groupby("customerName")["revenue"].sum().sort_values(ascending=False)
    bullets.append(f"**Customer concentration:** the top 10 customers generate {cu.head(10).sum() / cu.sum():.0%} "
                   f"of revenue; the largest is {cu.index[0]} ({money(cu.iloc[0])}).")
    es = f.groupby("employeeName")["revenue"].sum().sort_values(ascending=False)
    bullets.append(f"**Top salesperson:** {es.index[0]} with {money(es.iloc[0])}.")
    ps = f.groupby("productName")["revenue"].sum().sort_values(ascending=False)
    bullets.append(f"**Top product:** {ps.index[0]} with {money(ps.iloc[0])}.")
    disc_share = f.loc[f["discount"] > 0, "revenue"].sum() / f["revenue"].sum()
    bullets.append(f"**Discounting:** {disc_share:.0%} of revenue comes from discounted order lines.")
    unshipped = int(orders["shippedDate"].isna().sum())
    if not pd.isna(cur["on_time"]):
        bullets.append(f"**Delivery:** {1 - cur['on_time']:.1%} of shipped orders left after the required date; "
                       f"{unshipped} orders have not shipped yet.")
    st.markdown("\n".join(f"- {b}" for b in bullets))

# ==========================================================================
# 2. SALES TRENDS
# ==========================================================================
with tabs[1]:
    c1, c2 = st.columns(2)
    gran = c1.radio("Group by", ["Month", "Quarter", "Week", "Year"], horizontal=True, key="gran")
    metric = c2.radio("Metric", ["Revenue", "Orders", "Units"], horizontal=True, key="metric")
    freq = {"Month": "M", "Quarter": "Q", "Week": "W", "Year": "Y"}[gran]

    g = (
        f.assign(period=f["orderDate"].dt.to_period(freq).dt.to_timestamp())
        .groupby("period")
        .agg(Revenue=("revenue", "sum"), Orders=("orderID", "nunique"), Units=("quantity", "sum"))
        .reset_index()
    )
    fig = px.line(g, x="period", y=metric, markers=True, color_discrete_sequence=[BLUE])
    fig.update_layout(xaxis_title=None)
    show(style(fig, f"{metric} by {gran.lower()}"))

    left, right = st.columns(2)
    with left:
        cum = f.groupby("orderDate", as_index=False)["revenue"].sum().sort_values("orderDate")
        cum["cumulative"] = cum["revenue"].cumsum()
        fig = px.area(cum, x="orderDate", y="cumulative", color_discrete_sequence=[BLUE])
        fig.update_layout(xaxis_title=None, yaxis_title="Cumulative revenue ($)")
        show(style(fig, "Cumulative revenue"))
    with right:
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        wd = (f.assign(day=f["orderDate"].dt.day_name()).groupby("day")["revenue"].sum()
              .reindex(days).fillna(0).reset_index())
        fig = px.bar(wd, x="day", y="revenue", color_discrete_sequence=[BLUE])
        fig.update_layout(xaxis_title=None, yaxis_title="Revenue ($)")
        show(style(fig, "Revenue by weekday"))

    hm = (f.assign(year=f["orderDate"].dt.year, month=f["orderDate"].dt.month)
          .pivot_table(index="year", columns="month", values="revenue", aggfunc="sum")
          .reindex(columns=range(1, 13)))
    hm.columns = [calendar.month_abbr[i] for i in hm.columns]
    hm.index = hm.index.astype(str)
    fig = px.imshow(hm, aspect="auto", color_continuous_scale="Blues", labels=dict(color="Revenue ($)"))
    show(style(fig, "Seasonality: revenue by year and month (blank = no orders in range)", height=260))

# ==========================================================================
# 3. PRODUCTS & CATEGORIES
# ==========================================================================
with tabs[2]:
    prod = (
        f.groupby(["productName", "categoryName", "discontinued"], as_index=False)
        .agg(revenue=("revenue", "sum"), units=("quantity", "sum"), orders=("orderID", "nunique"),
             listPrice=("listPrice", "first"))
        .sort_values("revenue", ascending=False)
    )
    left, right = st.columns(2)
    with left:
        cat = f.groupby("categoryName", as_index=False).agg(revenue=("revenue", "sum"), units=("quantity", "sum"))
        cat = cat.sort_values("revenue")
        fig = px.bar(cat, x="revenue", y="categoryName", orientation="h", color_discrete_sequence=[BLUE])
        fig.update_layout(xaxis_title="Revenue ($)", yaxis_title=None)
        show(style(fig, "Revenue by category"))
    with right:
        fig = px.treemap(prod, path=["categoryName", "productName"], values="revenue",
                         color_discrete_sequence=CATEGORICAL)
        show(style(fig, "Category → product revenue"))

    n = st.slider("Number of products to show", 5, 25, 10, key="topn_products")
    left, right = st.columns(2)
    with left:
        top = prod.head(n).iloc[::-1]
        fig = px.bar(top, x="revenue", y="productName", orientation="h", color="categoryName",
                     color_discrete_sequence=CATEGORICAL)
        fig.update_layout(xaxis_title="Revenue ($)", yaxis_title=None)
        show(style(fig, f"Top {n} products by revenue", height=max(380, 26 * n + 120)))
    with right:
        bottom = prod.tail(n)
        fig = px.bar(bottom, x="revenue", y="productName", orientation="h", color="categoryName",
                     color_discrete_sequence=CATEGORICAL)
        fig.update_layout(xaxis_title="Revenue ($)", yaxis_title=None)
        show(style(fig, f"Bottom {n} products by revenue", height=max(380, 26 * n + 120)))

    left, right = st.columns(2)
    with left:
        fig = px.scatter(prod, x="listPrice", y="units", size="revenue", color="categoryName",
                         hover_name="productName", color_discrete_sequence=CATEGORICAL)
        fig.update_layout(xaxis_title="List price ($)", yaxis_title="Units sold")
        show(style(fig, "Price vs volume (bubble = revenue)"))
    with right:
        d = (f.assign(discountPct=(f["discount"] * 100).round().astype(int).astype(str) + "%")
             .groupby(["discount", "discountPct"], as_index=False)
             .agg(revenue=("revenue", "sum"), avgQty=("quantity", "mean"), lines=("productID", "size"))
             .sort_values("discount"))
        fig = go.Figure()
        fig.add_bar(x=d["discountPct"], y=d["revenue"], name="Revenue", marker_color=BLUE)
        fig.add_scatter(x=d["discountPct"], y=d["avgQty"], name="Avg qty per line", yaxis="y2",
                        mode="lines+markers", line=dict(color=ORANGE))
        fig.update_layout(xaxis_title="Discount level", yaxis=dict(title="Revenue ($)"),
                          yaxis2=dict(title="Avg quantity per line", overlaying="y", side="right", showgrid=False))
        show(style(fig, "Do discounts lift order size?"))

    disc_n = int(prod["discontinued"].sum())
    st.caption(f"{disc_n} of {len(prod)} products sold in this selection are discontinued.")
    st.subheader("Product performance")
    pt = prod.assign(discontinued=prod["discontinued"].map({0: "No", 1: "Yes"}))
    table(pt[["productName", "categoryName", "listPrice", "units", "orders", "revenue", "discontinued"]],
          money_cols=["listPrice", "revenue"], height=360)

# ==========================================================================
# 4. CUSTOMERS & GEOGRAPHY
# ==========================================================================
with tabs[3]:
    country = (
        f.groupby(["customerCountry", "customerCountryMap"], as_index=False)
        .agg(revenue=("revenue", "sum"), orders=("orderID", "nunique"), customers=("customerID", "nunique"))
    )
    fig = px.choropleth(country, locations="customerCountryMap", locationmode="country names",
                        color="revenue", hover_name="customerCountry",
                        hover_data=dict(customerCountryMap=False, orders=True, customers=True),
                        color_continuous_scale="Blues")
    fig.update_geos(showframe=False, showcoastlines=False, projection_type="natural earth")
    show(style(fig, "Revenue by customer country", height=420))

    cust = (
        f.groupby(["customerID", "customerName", "customerCity", "customerCountry"], as_index=False)
        .agg(revenue=("revenue", "sum"), orders=("orderID", "nunique"), last_order=("orderDate", "max"))
        .sort_values("revenue", ascending=False)
    )
    cust["avg_order_value"] = cust["revenue"] / cust["orders"]
    cust["days_since_last_order"] = (d1 - cust["last_order"]).dt.days

    n = st.slider("Number of customers to show", 5, 25, 10, key="topn_customers")
    left, right = st.columns(2)
    with left:
        top = cust.head(n).iloc[::-1]
        fig = px.bar(top, x="revenue", y="customerName", orientation="h", color="customerCountry",
                     color_discrete_sequence=CATEGORICAL)
        fig.update_layout(xaxis_title="Revenue ($)", yaxis_title=None)
        show(style(fig, f"Top {n} customers", height=max(380, 26 * n + 120)))
    with right:
        p = cust["revenue"].reset_index(drop=True)
        par = pd.DataFrame({"rank": range(1, len(p) + 1), "share": p.cumsum() / p.sum() * 100})
        fig = px.line(par, x="rank", y="share", color_discrete_sequence=[BLUE])
        fig.add_hline(y=80, line_dash="dot", line_color="grey")
        fig.update_layout(xaxis_title="Customers ranked by revenue", yaxis_title="Cumulative % of revenue")
        show(style(fig, "Pareto: how concentrated is revenue?"))

    left, right = st.columns(2)
    with left:
        fig = px.histogram(cust, x="orders", nbins=20, color_discrete_sequence=[BLUE])
        fig.update_layout(xaxis_title="Orders per customer", yaxis_title="Customers")
        show(style(fig, "Order frequency"))
    with right:
        cc = f.groupby(["customerCountry", "customerCity"], as_index=False)["revenue"].sum()
        fig = px.treemap(cc, path=["customerCountry", "customerCity"], values="revenue")
        show(style(fig, "Country → city revenue"))

    st.subheader("Customer table")
    ct = cust.assign(last_order=cust["last_order"].dt.date)
    table(ct[["customerName", "customerCity", "customerCountry", "orders", "revenue", "avg_order_value",
              "last_order", "days_since_last_order"]],
          money_cols=["revenue", "avg_order_value"], height=360)

# ==========================================================================
# 5. EMPLOYEES
# ==========================================================================
with tabs[4]:
    emp = (
        f.groupby(["employeeName", "employeeTitle", "employeeCity", "managerName"], dropna=False, as_index=False)
        .agg(revenue=("revenue", "sum"), orders=("orderID", "nunique"), customers=("customerID", "nunique"),
             units=("quantity", "sum"))
        .sort_values("revenue", ascending=False)
    )
    emp["avg_order_value"] = emp["revenue"] / emp["orders"]
    emp["managerName"] = emp["managerName"].fillna("-")

    left, right = st.columns(2)
    with left:
        fig = px.bar(emp.iloc[::-1], x="revenue", y="employeeName", orientation="h", color="employeeTitle",
                     color_discrete_sequence=CATEGORICAL)
        fig.update_layout(xaxis_title="Revenue ($)", yaxis_title=None)
        show(style(fig, "Revenue by employee"))
    with right:
        fig = px.scatter(emp, x="orders", y="avg_order_value", size="revenue", color="employeeCity",
                         hover_name="employeeName", color_discrete_sequence=CATEGORICAL)
        fig.update_layout(xaxis_title="Orders handled", yaxis_title="Avg order value ($)")
        show(style(fig, "Volume vs order value (bubble = revenue)"))

    em = f.groupby(["orderMonth", "employeeName"], as_index=False)["revenue"].sum()
    fig = px.line(em, x="orderMonth", y="revenue", color="employeeName", color_discrete_sequence=CATEGORICAL)
    fig.update_layout(xaxis_title=None, yaxis_title="Revenue ($)")
    show(style(fig, "Monthly revenue by employee"))

    ec = (f.pivot_table(index="employeeName", columns="categoryName", values="revenue", aggfunc="sum")
          .fillna(0))
    fig = px.imshow(ec, aspect="auto", color_continuous_scale="Blues", text_auto=".2s",
                    labels=dict(color="Revenue ($)"))
    show(style(fig, "Employee × category revenue", height=420))

    st.subheader("Team overview")
    table(emp[["employeeName", "employeeTitle", "managerName", "employeeCity", "orders", "customers",
               "revenue", "avg_order_value"]].rename(columns={"managerName": "reportsTo"}),
          money_cols=["revenue", "avg_order_value"])

# ==========================================================================
# 6. SHIPPING & DELIVERY
# ==========================================================================
with tabs[5]:
    ship = (
        orders.groupby("shipperName", as_index=False)
        .agg(orders=("orderID", "nunique"), freight=("freight", "sum"), avg_freight=("freight", "mean"),
             revenue=("revenue", "sum"), avg_days=("daysToShip", "mean"), late_rate=("lateFlag", "mean"))
    )
    ship["freight_pct_revenue"] = ship["freight"] / ship["revenue"] * 100
    ship["late_rate"] = ship["late_rate"] * 100

    c = st.columns(3)
    avg_days = orders["daysToShip"].mean()
    c[0].metric("Avg days to ship", "n/a" if pd.isna(avg_days) else f"{avg_days:.1f}")
    c[1].metric("Orders not yet shipped", f"{int(orders['shippedDate'].isna().sum()):,}")
    c[2].metric("Freight as % of revenue", f"{orders['freight'].sum() / orders['revenue'].sum():.1%}")

    left, right = st.columns(2)
    with left:
        fig = px.pie(ship, names="shipperName", values="orders", hole=0.5, color_discrete_sequence=CATEGORICAL)
        fig.update_traces(textinfo="percent+label")
        fig.update_layout(showlegend=False)
        show(style(fig, "Order share by shipper"))
    with right:
        fig = px.bar(ship, x="shipperName", y="avg_freight", color_discrete_sequence=[BLUE])
        fig.update_layout(xaxis_title=None, yaxis_title="Avg freight per order ($)")
        show(style(fig, "Average freight cost by shipper"))

    left, right = st.columns(2)
    with left:
        shipped = orders[orders["daysToShip"].notna()]
        fig = px.box(shipped, x="shipperName", y="daysToShip", color_discrete_sequence=[BLUE])
        fig.update_layout(xaxis_title=None, yaxis_title="Days from order to shipment")
        show(style(fig, "Time to ship by shipper"))
    with right:
        fig = px.bar(ship, x="shipperName", y="late_rate", color_discrete_sequence=[ORANGE])
        fig.update_layout(xaxis_title=None, yaxis_title="% shipped after required date")
        show(style(fig, "Late shipments by shipper"))

    tm = (orders[orders["shippedDate"].notna()].groupby("orderMonth", as_index=False)["lateFlag"].mean())
    tm["on_time"] = (1 - tm["lateFlag"]) * 100
    fig = px.line(tm, x="orderMonth", y="on_time", markers=True, color_discrete_sequence=[BLUE])
    fig.update_layout(xaxis_title=None, yaxis_title="% shipped on time", yaxis_range=[0, 105])
    show(style(fig, "On-time shipping rate by order month"))

    cf = (orders.groupby("customerCountry", as_index=False)
          .agg(orders=("orderID", "nunique"), avg_freight=("freight", "mean"), late_rate=("lateFlag", "mean"))
          .sort_values("avg_freight", ascending=False))
    cf["late_rate"] = cf["late_rate"] * 100
    st.subheader("Freight and lateness by destination country")
    table(cf, money_cols=["avg_freight"], pct_cols=["late_rate"], height=320)

    open_orders = orders[orders["shippedDate"].isna()][
        ["orderID", "orderDate", "requiredDate", "customerName", "customerCountry", "shipperName", "revenue"]
    ].assign(orderDate=lambda d: d["orderDate"].dt.date, requiredDate=lambda d: d["requiredDate"].dt.date)
    if len(open_orders):
        st.subheader("Orders not yet shipped")
        table(open_orders, money_cols=["revenue"])

# ==========================================================================
# 7. DATA & MODEL
# ==========================================================================
with tabs[6]:
    st.subheader("How the 7 tables are joined")
    st.graphviz_chart(
        """
        digraph {
            rankdir=LR; node [shape=box, style="rounded,filled", fillcolor="#eff6ff", color="#2563eb"];
            order_details -> orders [label="orderID"];
            order_details -> products [label="productID"];
            products -> categories [label="categoryID"];
            orders -> customers [label="customerID"];
            orders -> employees [label="employeeID"];
            orders -> shippers [label="shipperID"];
            employees -> employees [label="reportsTo"];
        }
        """
    )
    st.markdown(
        "`order_details` is the fact table (one row per product on an order). Every join is many-to-one, so the "
        "joined table keeps exactly one row per order line. Order-level amounts such as **freight** are summed "
        "from a one-row-per-order table so they are never double counted."
    )
    sizes = pd.DataFrame({"table": list(tables), "rows": [len(v) for v in tables.values()],
                          "columns": [v.shape[1] for v in tables.values()]})
    table(sizes)

    st.subheader("Joined, filtered data")
    st.caption(f"{len(f):,} rows × {f.shape[1]} columns")
    st.dataframe(f.head(500), hide_index=True)
    st.download_button("Download filtered data (CSV)", f.to_csv(index=False).encode("utf-8"),
                       file_name="northwind_joined_filtered.csv", mime="text/csv")
