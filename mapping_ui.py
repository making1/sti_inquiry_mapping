"""Administrator-only mapping, external surveillance and validation panels."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
import streamlit as st

from mapping_analytics import weekly_signals, case_rates


def render_mapping(records, coordinates, root):
    st.subheader("STI inquiry mapping and model validation")
    st.caption("Uses V18's consented inquiries and consented county profiles. Existing bilingual extraction and learner responses are retained.")
    section = st.radio("Analysis", ["Weekly inquiry signals", "Verified surveillance rates", "Model validation"], key="mapping_section", horizontal=True)
    if section == "Weekly inquiry signals":
        st.info("Signals describe unusual information-seeking activity, not confirmed outbreaks. Only completed UTC weeks with at least five distinct consented sessions are released. A baseline also requires eight preceding weeks that each meet that threshold.")
        if not st.checkbox("Reporting coverage is sufficiently consistent to interpret weekly changes", key="mapping_coverage"):
            st.caption("Confirm reporting coverage to calculate signals; missing records cannot be distinguished from absent reporting.")
            return
        weekly = weekly_signals(records)
        if weekly.empty:
            st.info("No completed county-week meets the five-session threshold. Use the existing aggregate map for overall activity.")
            return
        county = st.selectbox("County", sorted(weekly.county.unique()), key="mapping_county")
        selected = weekly[weekly.county == county].copy()
        # Explicit gaps: do not draw an apparent continuous trend across suppressed weeks.
        all_weeks = pd.date_range(weekly.week.min(), weekly.week.max(), freq="7D")
        chart = selected.set_index("week").reindex(all_weeks)
        st.line_chart(chart[["inquiries", "baseline_mean", "alert_threshold"]])
        st.caption("Mean + 3 standard deviations, with a standard-deviation floor of one. Blank baselines/signals mean insufficient releasable history, not absence of a signal. Counts are inquiries; sessions are not unique people or cases.")
        week = st.selectbox("Map week", sorted(weekly.week.unique(), reverse=True), format_func=lambda w: str(pd.Timestamp(w).date()), key="mapping_week")
        mapped = weekly[weekly.week == week].copy()
        mapped["lat"] = mapped.county.map(lambda c: coordinates[c][0])
        mapped["lon"] = mapped.county.map(lambda c: coordinates[c][1])
        st.map(mapped, latitude="lat", longitude="lon", size="sessions")
        st.dataframe(mapped.drop(columns=["lat", "lon"]), hide_index=True)
        st.download_button("Download released county-week aggregates", weekly.to_csv(index=False), "weekly_inquiry_signals.csv", "text/csv")
        st.caption("This exploratory heuristic is unvalidated for outbreaks, has no multiple-testing control, and does not allocate resources automatically. Profile linkage follows V18: latest consented profile per session.")
    elif section == "Verified surveillance rates":
        st.caption("Upload externally verified aggregate CSV: area, period, confirmed_cases, population. No inquiry counts are used as infection counts. This upload is not written to the database.")
        uploaded = st.file_uploader("Surveillance CSV", type="csv", key="mapping_surveillance")
        if uploaded is not None:
            try:
                rates = case_rates(pd.read_csv(uploaded))
                st.dataframe(rates, hide_index=True)
                period = st.selectbox("Reporting period", sorted(rates.period.astype(str).unique()), key="rates_period")
                selected = rates[rates.period.astype(str) == period]
                st.bar_chart(selected.set_index("area")[["reported_cases_per_100000"]])
                mapped = selected.copy()
                mapped["county"] = mapped.area.astype(str).str.strip().str.casefold()
                mapped = mapped[mapped.county.isin(coordinates)].copy()
                if not mapped.empty:
                    mapped["lat"] = mapped.county.map(lambda c: coordinates[c][0])
                    mapped["lon"] = mapped.county.map(lambda c: coordinates[c][1])
                    st.map(mapped, latitude="lat", longitude="lon", size="reported_cases_per_100000")
                st.download_button("Download reported case rates", rates.to_csv(index=False), "reported_case_rates.csv", "text/csv")
                st.warning("Reported case rates are not prevalence estimates. Case definitions, coverage, denominators and reporting periods must be comparable. Review source disclosure restrictions before uploading or exporting.")
            except (ValueError, TypeError, pd.errors.ParserError) as exc:
                st.error(f"Invalid surveillance data: {exc}")
    else:
        st.markdown("**V18 model evaluation artifacts**")
        st.caption("These describe V18's bundled models; synthetic results do not establish real-world performance.")
        for filename in ["metrics.json", "entity_metrics.json"]:
            path = Path(root) / "evaluation" / filename
            if path.exists():
                st.markdown(f"**{filename}**")
                st.json(json.loads(path.read_text(encoding="utf-8")))
        st.markdown("**Train and validate the standalone inquiry intent baseline**")
        st.caption("This is the mapping pipeline's TF-IDF + logistic regression experiment. It does not replace or retrain V18's deployed intent/entity models. Supply independently annotated CSV columns: inquiry_id, date, area, text, label; optional pseudonymous user_id.")
        uploaded = st.file_uploader("Annotated inquiry CSV", type="csv", key="mapping_training")
        if st.button("Run chronological validation", disabled=uploaded is None, key="mapping_validate"):
            st.session_state.pop("mapping_validation", None)
            try:
                from pipeline import read_inquiries, train
                with TemporaryDirectory(prefix="sti_validation_") as folder:
                    folder = Path(folder)
                    (folder / "input.csv").write_bytes(uploaded.getvalue())
                    data = read_inquiries(folder / "input.csv", labeled=True)
                    with st.spinner("Evaluating on future held-out inquiries…"):
                        train(data, folder)
                    st.session_state.mapping_validation = (folder / "metrics.json").read_text(encoding="utf-8")
            except (ValueError, TypeError, pd.errors.ParserError) as exc:
                st.error(f"Validation could not run: {exc}")
        if "mapping_validation" in st.session_state:
            st.json(json.loads(st.session_state.mapping_validation))
            st.download_button("Download validation metrics", st.session_state.mapping_validation, "temporal_validation.json", "application/json")
        st.caption("Temporary training files are removed after the run. Only metrics remain in this admin session. Validate extraction against mention annotations and inquiry signals against independent surveillance separately; classifier scores do not validate either.")
