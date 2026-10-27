"""Data layer for the Northwind Traders dashboard.

Loads the 7 CSV tables, validates the keys and joins them into one
line-level fact table (one row per order line) plus helpers to roll it up
to one row per order.

Relationships (all many-to-one, so joins never duplicate order lines):

    order_details.orderID    -> orders.orderID
    order_details.productID  -> products.productID
    products.categoryID      -> categories.categoryID
    orders.customerID        -> customers.customerID
    orders.employeeID        -> employees.employeeID
    orders.shipperID         -> shippers.shipperID
    employees.reportsTo      -> employees.employeeID   (manager, self-join)
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

TABLES = [
    "employees",
    "orders",
    "shippers",
    "customers",
    "categories",
    "products",
    "order_details",
]

# Names Plotly's choropleth understands.
COUNTRY_FIX = {"UK": "United Kingdom", "USA": "United States"}


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------
def _has_all_tables(folder: Path) -> bool:
    return all((folder / f"{t}.csv").exists() for t in TABLES)


def find_data_dir(preferred: str | None = None) -> str | None:
    """Return the first folder that contains all 7 CSV files."""
    here = Path(__file__).resolve().parent
    candidates = []
    if preferred:
        candidates.append(Path(preferred).expanduser())
    candidates += [here / "data", here, Path.cwd() / "data", Path.cwd()]
    for folder in candidates:
        if folder.is_dir() and _has_all_tables(folder):
            return str(folder)
    return None


def _read_csv(path: Path, **kwargs) -> pd.DataFrame:
    # customers.csv and products.csv are Windows-1252 encoded.
    try:
        return pd.read_csv(path, encoding="utf-8", **kwargs)
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="cp1252", **kwargs)


def load_tables(data_dir: str) -> dict[str, pd.DataFrame]:
    folder = Path(data_dir)
    tables = {t: _read_csv(folder / f"{t}.csv") for t in TABLES}
    for col in ("orderDate", "requiredDate", "shippedDate"):
        tables["orders"][col] = pd.to_datetime(tables["orders"][col])
    return tables


# --------------------------------------------------------------------------
# Joining
# --------------------------------------------------------------------------
def build_fact(t: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Join all tables into one row per order line."""
    # order lines ---------------------------------------------------------
    od = t["order_details"].rename(columns={"unitPrice": "soldPrice"}).copy()
    od["gross"] = od["soldPrice"] * od["quantity"]
    od["revenue"] = od["gross"] * (1 - od["discount"])
    od["discountAmt"] = od["gross"] - od["revenue"]

    # orders --------------------------------------------------------------
    orders = t["orders"].copy()
    orders["orderMonth"] = orders["orderDate"].dt.to_period("M").dt.to_timestamp()
    orders["daysToShip"] = (orders["shippedDate"] - orders["orderDate"]).dt.days
    shipped = orders["shippedDate"].notna()
    late = (orders["shippedDate"] > orders["requiredDate"]).astype(float)
    orders["lateFlag"] = late.where(shipped)  # 1 late, 0 on time, NaN not shipped

    # dimensions ----------------------------------------------------------
    cust = t["customers"].rename(
        columns={
            "companyName": "customerName",
            "contactName": "contactName",
            "city": "customerCity",
            "country": "customerCountry",
        }
    )
    emp = t["employees"].rename(
        columns={
            "employeeName": "employeeName",
            "title": "employeeTitle",
            "city": "employeeCity",
            "country": "employeeCountry",
        }
    )
    mgr = emp[["employeeID", "employeeName"]].rename(
        columns={"employeeID": "reportsTo", "employeeName": "managerName"}
    )
    emp = emp.merge(mgr, on="reportsTo", how="left")

    prod = t["products"].rename(columns={"unitPrice": "listPrice"})
    prod = prod.merge(
        t["categories"][["categoryID", "categoryName"]], on="categoryID", how="left", validate="many_to_one"
    )
    ship = t["shippers"].rename(columns={"companyName": "shipperName"})

    # joins ---------------------------------------------------------------
    fact = (
        od.merge(orders, on="orderID", how="left", validate="many_to_one")
        .merge(prod, on="productID", how="left", validate="many_to_one")
        .merge(cust, on="customerID", how="left", validate="many_to_one")
        .merge(emp, on="employeeID", how="left", validate="many_to_one")
        .merge(ship, on="shipperID", how="left", validate="many_to_one")
    )

    # integrity checks ----------------------------------------------------
    if len(fact) != len(od):
        raise ValueError("Join changed the number of order lines - check the keys.")
    for col in ("customerName", "employeeName", "productName", "categoryName", "shipperName"):
        missing = int(fact[col].isna().sum())
        if missing:
            raise ValueError(f"{missing} order lines have no match for {col}.")

    fact["customerCountryMap"] = fact["customerCountry"].replace(COUNTRY_FIX)
    return fact


ORDER_FIRST_COLS = [
    "orderDate", "orderMonth", "requiredDate", "shippedDate", "freight",
    "daysToShip", "lateFlag", "customerID", "customerName", "customerCity",
    "customerCountry", "customerCountryMap", "employeeID", "employeeName",
    "employeeTitle", "shipperID", "shipperName",
]


def orders_from_fact(f: pd.DataFrame) -> pd.DataFrame:
    """One row per order. Freight is an order-level amount, so it must be
    summed here and never from the line-level table."""
    agg = {c: (c, "first") for c in ORDER_FIRST_COLS}
    agg.update(
        revenue=("revenue", "sum"),
        gross=("gross", "sum"),
        discountAmt=("discountAmt", "sum"),
        units=("quantity", "sum"),
        lines=("productID", "nunique"),
    )
    return f.groupby("orderID", as_index=False).agg(**agg)
