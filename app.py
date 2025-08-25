import streamlit as st
import pandas as pd
import altair as alt
from datetime import datetime, timedelta
from dateutil import tz

# ---- Page setup ----
st.set_page_config(page_title="Blood Sugar Tracker", page_icon="🩸", layout="wide")
st.write("✅ App booted")  # visible early so deploy issues don't look like a black screen

# ---- Storage (CSV on disk; ephemeral on Streamlit Cloud) ----
DATA_PATH = "glucose_log.csv"
COLUMNS = ["datetime", "glucose_mgdl", "context", "carbs_g", "insulin_units", "notes"]

@st.cache_data
def load_data():
    try:
        df = pd.read_csv(DATA_PATH, parse_dates=["datetime"])
        for c in COLUMNS:
            if c not in df.columns:
                df[c] = None
        return df[COLUMNS].sort_values("datetime")
    except Exception:
        return pd.DataFrame(columns=COLUMNS)

def save_data(df: pd.DataFrame):
    try:
        df[COLUMNS].sort_values("datetime").to_csv(DATA_PATH, index=False)
    except Exception as e:
        st.warning(f"Could not save CSV: {e}")

df = load_data()

# ---- Sidebar settings ----
st.sidebar.header("⚙️ Settings")
local_tz = tz.tzlocal()
default_low = st.sidebar.number_input("Target range low (mg/dL)", 70, 200, 70, step=1)
default_high = st.sidebar.number_input("Target range high (mg/dL)", 90, 300, 180, step=1)
window_days = st.sidebar.selectbox("Trend window", [7, 14, 30, 90], index=2)

st.sidebar.download_button(
    "⬇️ Download CSV",
    data=df.to_csv(index=False),
    file_name="glucose_log.csv",
    mime="text/csv",
)
uploaded = st.sidebar.file_uploader("⬆️ Import CSV (same columns)", type=["csv"])
if uploaded is not None:
    try:
        incoming = pd.read_csv(uploaded, parse_dates=["datetime"])
        merged = pd.concat([df, incoming], ignore_index=True).drop_duplicates()
        save_data(merged)
        st.sidebar.success("Imported & saved")
        df = load_data()
    except Exception as e:
        st.sidebar.error(f"Import failed: {e}")

# ---- Input form ----
st.title("🩸 Blood Sugar Tracker")

with st.expander("➕ Add a reading", expanded=True):
    c1, c2, c3, c4 = st.columns([1, 1, 1, 2])
    date_in = c1.date_input("Date", value=datetime.now().date())
    time_in = c2.time_input("Time", value=datetime.now().time().replace(second=0, microsecond=0))
    glucose = c3.number_input("Glucose (mg/dL)", min_value=10, max_value=800, step=1)
    context = c4.selectbox("Context", ["fasting", "pre-meal", "post-meal (1h)", "post-meal (2h)", "bedtime", "other"])
    c5, c6 = st.columns([1, 1])
    carbs = c5.number_input("Carbs (g)", min_value=0.0, step=1.0, value=0.0)
    insulin = c6.number_input("Insulin (units)", min_value=0.0, step=0.5, value=0.0)
    notes = st.text_input("Notes (optional)")

    if st.button("Add reading", type="primary"):
        try:
            # Normalize to UTC; this avoids tz-localize errors later
            dt = datetime.combine(date_in, time_in)
            ts = pd.Timestamp(dt).tz_localize("UTC")
            new_row = {
                "datetime": ts,
                "glucose_mgdl": int(glucose),
                "context": context,
                "carbs_g": float(carbs),
                "insulin_units": float(insulin),
                "notes": notes.strip(),
            }
            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
            save_data(df)
            st.success("Saved!")
        except Exception as e:
            st.exception(e)

# ---- Filters ----
st.subheader("📅 Your log")

try:
    min_date = (df["datetime"].min().date() if not df.empty else datetime.now().date())
    max_date = (df["datetime"].max().date() if not df.empty else datetime.now().date())
except Exception:
    min_date = max_date = datetime.now().date()

fc1, fc2, fc3 = st.columns([1, 1, 2])
start_date = fc1.date_input("From", value=max(min_date, datetime.now().date() - timedelta(days=window_days)))
end_date = fc2.date_input("To", value=max_date)
ctx_filter = fc3.multiselect(
    "Context filter", ["fasting", "pre-meal", "post-meal (1h)", "post-meal (2h)", "bedtime", "other"]
)

# Ensure timestamps are UTC-aware
def ensure_utc(s: pd.Series) -> pd.Series:
    def fix(x):
        x = pd.to_datetime(x, errors="coerce")
        if pd.isna(x):
            return x
        if getattr(x, "tzinfo", None) is None:
            return x.tz_localize("UTC")
        return x.tz_convert("UTC")
    return s.apply(fix)

if not df.empty:
    df["datetime"] = ensure_utc(df["datetime"])
    mask = (df["datetime"].dt.date >= start_date) & (df["datetime"].dt.date <= end_date)
    if ctx_filter:
        mask &= df["context"].isin(ctx_filter)
    view = df.loc[mask].copy()
else:
    view = df.copy()

# Convert to local time safely
def to_local(dt_series: pd.Series) -> pd.Series:
    def fix_ts(x):
        if pd.isna(x):
            return x
        try:
            if getattr(x, "tzinfo", None) is None:
                x = x.tz_localize("UTC")
            else:
                x = x.tz_convert("UTC")
            return x.tz_convert(tz.tzlocal())
        except Exception:
            return pd.to_datetime(x, utc=True).tz_convert(tz.tzlocal())
    return dt_series.apply(fix_ts)

if not view.empty:
    view["local_dt"] = to_local(view["datetime"])

# ---- Metrics ----
def est_a1c_from_eag(eag_mgdl: float) -> float:
    # NGSP: eAG (mg/dL) = 28.7 * A1C − 46.7  =>  A1C = (eAG + 46.7) / 28.7
    return round((eag_mgdl + 46.7) / 28.7, 2)

def time_in_range(series, low, high):
    if len(series) == 0:
        return 0.0, 0.0, 0.0
    total = len(series)
    in_range = ((series >= low) & (series <= high)).sum()
    low_ct = (series < low).sum()
    high_ct = (series > high).sum()
    return round(100 * in_range / total, 1), round(100 * low_ct / total, 1), round(100 * high_ct / total, 1)

k1, k2, k3, k4 = st.columns(4)
if view.empty:
    k1.metric("Readings", "0")
    k2.metric("Avg (mg/dL)", "—")
    k3.metric("Time-in-Range", "—")
    k4.metric("Est. A1C", "—")
else:
    avg = float(view["glucose_mgdl"].mean())
    tir, below, above = time_in_range(view["glucose_mgdl"], default_low, default_high)
    k1.metric("Readings", f"{len(view)}")
    k2.metric("Avg (mg/dL)", f"{avg:.0f}")
    k3.metric("Time-in-Range", f"{tir}% (↓{below}% ↑{above}%)")
    k4.metric("Est. A1C", f"{est_a1c_from_eag(avg)}%")

# ---- Chart ----
if not view.empty and "local_dt" in view.columns:
    chart_df = view[["local_dt", "glucose_mgdl"]].rename(
        columns={"local_dt": "Date/Time", "glucose_mgdl": "Glucose (mg/dL)"}
    )
    try:
        rule_low = alt.Chart(pd.DataFrame({"y": [default_low]})).mark_rule(strokeDash=[4, 4]).encode(y="y")
        rule_high = alt.Chart(pd.DataFrame({"y": [default_high]})).mark_rule(strokeDash=[4, 4]).encode(y="y")
        line = alt.Chart(chart_df).mark_line(point=True).encode(
            x=alt.X("Date/Time:T", title=""),
            y=alt.Y("Glucose (mg/dL):Q"),
            tooltip=["Date/Time:T", "Glucose (mg/dL):Q"],
        ).properties(height=300)
        st.altair_chart((line + rule_low + rule_high).interactive(), use_container_width=True)
    except Exception as e:
        st.warning("Chart could not render; showing table only.")
        st.caption(str(e))

# ---- Table ----
st.dataframe(
    (view[["local_dt", "glucose_mgdl", "context", "carbs_g", "insulin_units", "notes"]]
     .rename(columns={"local_dt": "datetime (local)", "glucose_mgdl": "glucose (mg/dL)",
                      "carbs_g": "carbs (g)", "insulin_units": "insulin (u)"}))
    if not view.empty else view,
    use_container_width=True,
    height=350,
)

st.caption("⚕️ Informational only — not medical advice. Estimated A1C is based on mean glucose and may not match lab results.")
