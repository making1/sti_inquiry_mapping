"""Aggregate county-week analytics; no raw inquiry text or database writes."""
import pandas as pd


def weekly_signals(records, now=None, minimum_sessions=5):
    columns = ["county", "week", "inquiries", "sessions", "baseline_mean", "alert_threshold", "signal"]
    df = pd.DataFrame(records)
    if df.empty:
        return pd.DataFrame(columns=columns)
    df = df.dropna(subset=["day", "county", "session"]).copy()
    if df.empty:
        return pd.DataFrame(columns=columns)
    df["week"] = pd.to_datetime(df.day).dt.to_period("W-SUN").dt.start_time
    today = pd.Timestamp(now if now is not None else pd.Timestamp.now(tz="UTC"))
    if today.tzinfo is not None:
        today = today.tz_convert("UTC").tz_localize(None)
    current_week = today.to_period("W-SUN").start_time
    df = df[df.week < current_week]  # Never compare the current partial week to whole weeks.
    if df.empty:
        return pd.DataFrame(columns=columns)
    counts = df.groupby(["county", "week"]).agg(inquiries=("session", "size"), sessions=("session", "nunique"))
    weeks = pd.date_range(df.week.min(), current_week - pd.Timedelta(7, unit="D"), freq="7D")
    grid = pd.MultiIndex.from_product([sorted(df.county.unique()), weeks], names=["county", "week"])
    counts = counts.reindex(grid, fill_value=0).reset_index()
    released = []
    for _, group in counts.groupby("county"):
        group = group.copy()
        history = group.inquiries.shift(1).rolling(8, min_periods=8)
        group["baseline_mean"] = history.mean()
        group["alert_threshold"] = group.baseline_mean + 3 * history.std(ddof=0).clip(lower=1)
        eligible = group.sessions.ge(minimum_sessions)
        # A released baseline must not reveal a suppressed historical cell.
        safe_history = eligible.shift(1, fill_value=False).rolling(8, min_periods=8).sum().eq(8)
        group.loc[~safe_history, ["baseline_mean", "alert_threshold"]] = float("nan")
        group["signal"] = pd.Series(pd.NA, index=group.index, dtype="boolean")
        available = safe_history & eligible
        group.loc[available, "signal"] = group.loc[available, "inquiries"].gt(group.loc[available, "alert_threshold"])
        released.append(group.loc[eligible, columns])
    return pd.concat(released, ignore_index=True)


def case_rates(frame):
    required = {"area", "period", "confirmed_cases", "population"}
    if not required.issubset(frame):
        raise ValueError(f"Missing columns: {sorted(required - set(frame.columns))}")
    frame = frame[list(sorted(required))].copy()
    if frame.isna().any().any() or frame.duplicated(["area", "period"]).any():
        raise ValueError("Missing values or duplicate area/period records")
    for col in ["confirmed_cases", "population"]:
        frame[col] = pd.to_numeric(frame[col], errors="raise")
    import numpy as np
    if not np.isfinite(frame[["confirmed_cases", "population"]].to_numpy()).all():
        raise ValueError("Counts and populations must be finite")
    if (frame.confirmed_cases < 0).any() or (frame.population <= 0).any():
        raise ValueError("Cases must be nonnegative and population positive")
    frame["reported_cases_per_100000"] = frame.confirmed_cases / frame.population * 100000
    return frame
