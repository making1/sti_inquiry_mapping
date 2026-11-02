"""Research prototype: inquiry intent classification and area-level signals.

Run: python pipeline.py demo --out results
No individual diagnosis or prevalence inference is performed from inquiries.
"""
import argparse
import json
import re
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.pipeline import Pipeline


def clean(text):
    text = re.sub(r"\b[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}\b", " EMAIL ", str(text))
    text = re.sub(r"(?:\+?\d[\d ()-]{7,}\d)", " PHONE ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


MENTIONS = {
    "hiv": r"\bhiv\b",
    "syphilis": r"\bsyphilis\b",
    "gonorrhea": r"\bgonorrh(?:ea|oea)\b",
    "chlamydia": r"\bchlamydia\b",
    "herpes": r"\bherpes\b",
    "hpv": r"\bhpv\b|\bhuman papillomavirus\b",
    "trichomoniasis": r"\btrichomoniasis\b",
}
SYMPTOMS = {
    "painful_urination": r"\b(?:painful urination|burning when (?:I |i )?urinat\w*|pain when urinating)\b",
    "discharge": r"\bdischarge\b",
    "sores": r"\b(?:sores?|ulcers?)\b",
    "itching": r"\bitch(?:ing|y)?\b",
    "pelvic_pain": r"\bpelvic pain\b",
}


def extract(text):
    """Lexical mentions only: includes questions, negations and third parties."""
    return {
        "sti_mentions": "|".join(k for k, v in MENTIONS.items() if re.search(v, text, re.I)),
        "symptom_mentions": "|".join(k for k, v in SYMPTOMS.items() if re.search(v, text, re.I)),
    }


def read_inquiries(path, labeled=False):
    df = pd.read_csv(path)
    required = {"inquiry_id", "date", "area", "text"}
    if labeled:
        required.add("label")
    if not required.issubset(df.columns):
        raise ValueError(f"Missing columns: {sorted(required - set(df.columns))}")
    if df[list(required)].isna().any().any():
        raise ValueError("Required fields must not contain missing values")
    if df.inquiry_id.duplicated().any():
        raise ValueError("inquiry_id must be unique")
    df["date"] = pd.to_datetime(df.date, errors="raise", utc=True).dt.tz_localize(None).dt.normalize()
    df["clean_text"] = df.text.map(clean)
    if df.clean_text.str.len().eq(0).any():
        raise ValueError("Empty inquiry text")
    return df


def train(df, out):
    """Chronological holdout; purge duplicate texts and known users from training."""
    dates = sorted(df.date.unique())
    if len(dates) < 5:
        raise ValueError("Need at least five distinct dates for temporal validation")
    cutoff = dates[min(len(dates) - 1, int(len(dates) * 0.8))]
    tr, te = df[df.date < cutoff].copy(), df[df.date >= cutoff].copy()
    tr = tr[~tr.clean_text.isin(te.clean_text)].drop_duplicates("clean_text")
    if "user_id" in df:
        tr = tr[~tr.user_id.isin(te.user_id.dropna())]
    te = te.drop_duplicates("clean_text")
    if len(tr) < 10 or len(te) < 2 or tr.label.nunique() < 2:
        raise ValueError("Insufficient independent training/test data after leakage controls")
    unseen = set(te.label) - set(tr.label)
    if unseen:
        raise ValueError(f"Test labels absent from training: {unseen}")
    model = Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, max_features=30000)),
        ("classifier", LogisticRegression(max_iter=2000, class_weight="balanced", random_state=42)),
    ])
    model.fit(tr.clean_text, tr.label)
    pred = model.predict(te.clean_text)
    labels = model.classes_.tolist()
    metrics = {
        "split": "chronological; duplicate texts and overlapping users purged from training",
        "test_start": str(pd.Timestamp(cutoff).date()),
        "train_rows": len(tr), "test_rows": len(te),
        "classification": classification_report(te.label, pred, labels=labels, output_dict=True, zero_division=0),
        "labels": labels,
        "confusion_matrix": confusion_matrix(te.label, pred, labels=labels).tolist(),
        "limitation": "Intent classification only; lexical extraction and alert validity need separate annotated/external validation.",
    }
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    # Save precisely the evaluated model, without silently refitting on the holdout.
    joblib.dump(model, out / "model.joblib")
    return model


def summarize(df, model):
    result = df[["inquiry_id", "date", "area"]].copy()
    probabilities = model.predict_proba(df.clean_text)
    result["predicted_intent"] = model.classes_[probabilities.argmax(axis=1)]
    result["model_score"] = probabilities.max(axis=1)
    entities = pd.DataFrame([extract(t) for t in df.clean_text], index=df.index)
    result = result.join(entities)
    result["week"] = result.date.dt.to_period("W-SUN").dt.start_time
    counts = result.groupby(["area", "week"]).size().rename("inquiries")
    # Fill zero-count weeks within the observation period for every known area.
    index = pd.MultiIndex.from_product([
        sorted(result.area.unique()), pd.date_range(result.week.min(), result.week.max(), freq="7D")
    ], names=["area", "week"])
    weekly = counts.reindex(index, fill_value=0).reset_index()
    def baseline(group):
        history = group.inquiries.shift(1).rolling(8, min_periods=4)
        group["baseline_mean"] = history.mean()
        group["baseline_sd"] = history.std(ddof=0)
        # Exploratory heuristic, using only earlier weeks; not a validated outbreak test.
        group["alert_threshold"] = group.baseline_mean + 3 * group.baseline_sd.clip(lower=1)
        group["signal"] = (group.inquiries > group.alert_threshold) & (group.inquiries >= 5)
        return group
    weekly = pd.concat([baseline(g.copy()) for _, g in weekly.groupby("area")], ignore_index=True)
    return result.drop(columns="week"), weekly


def dashboard(weekly, areas, out, surveillance=None):
    """Export aggregate visuals only; individual inquiry text stays out of HTML."""
    import plotly.express as px
    areas = pd.read_csv(areas)
    if not {"area", "latitude", "longitude"}.issubset(areas):
        raise ValueError("Areas CSV needs area, latitude, longitude")
    if areas.area.duplicated().any():
        raise ValueError("Areas must have one centroid per area")
    if not (areas.latitude.between(-90, 90).all() and areas.longitude.between(-180, 180).all()):
        raise ValueError("Invalid area coordinates")
    latest = weekly[weekly.week == weekly.week.max()].merge(areas, on="area", validate="one_to_one")
    if len(latest) != weekly.area.nunique():
        raise ValueError("Missing area centroids")
    figures = [px.line(weekly, x="week", y="inquiries", color="area", markers=True,
                       title="Inquiry activity over time (not infection counts)"),
               px.scatter_geo(latest, lat="latitude", lon="longitude", size="inquiries", color="signal",
                              hover_name="area", title="Latest week: inquiry volume and exploratory signals")]
    if surveillance:
        s = pd.read_csv(surveillance)
        needed = {"area", "period", "confirmed_cases", "population"}
        if not needed.issubset(s):
            raise ValueError(f"Surveillance CSV requires {needed}")
        if s.duplicated(["area", "period"]).any():
            raise ValueError("Duplicate area/period surveillance records")
        if (s.population <= 0).any() or (s.confirmed_cases < 0).any():
            raise ValueError("Invalid surveillance counts or denominators")
        s["reported_case_rate_per_100000"] = s.confirmed_cases / s.population * 100000
        s.to_csv(out / "surveillance_rates.csv", index=False)
        figures.append(px.bar(s, x="area", y="reported_case_rate_per_100000", color="period",
                              barmode="group", title="Externally reported case rates (not prevalence estimates)"))
    html = "<html><head><meta charset='utf-8'><title>STI inquiry research</title></head><body>"
    html += "<h1>STI inquiry research dashboard</h1><p>Inquiry signals are not confirmed outbreaks or prevalence. Scores are uncalibrated. Review signals with surveillance staff before resource decisions. First/last weeks may be partial; missing reporting is indistinguishable from zero activity.</p>"
    for i, fig in enumerate(figures):
        html += fig.to_html(full_html=False, include_plotlyjs=True if i == 0 else False)
    (out / "dashboard.html").write_text(html + "</body></html>", encoding="utf-8")


def demo_data(out):
    rng = np.random.default_rng(42)
    intents = {
        "testing": ["Where can I get a {sti} test", "I need screening for {sti}", "How do I book a {sti} testing appointment"],
        "symptoms": ["Could {sti} explain my itching", "I have sores and worry about {sti}", "Does {sti} cause discharge"],
        "prevention": ["How can I prevent {sti}", "What protection reduces {sti} risk", "I want information about avoiding {sti}"],
        "treatment": ["Where is treatment for {sti} available", "I need a clinic for {sti} care", "Who offers follow up for {sti}"],
    }
    rows = []
    for week in range(24):
        for area in ["Example North", "Example South", "Example East"]:
            n = 45 if week == 22 and area == "Example North" else int(rng.integers(8, 16))
            for j in range(n):
                label = rng.choice(list(intents))
                text = rng.choice(intents[label]).format(sti=rng.choice(list(MENTIONS)))
                # Distinct synthetic wording IDs preserve an executable smoke test;
                # scores from this templated corpus are not real-world evidence.
                text += f"; synthetic context code z{len(rows):06d}"
                rows.append({"inquiry_id": len(rows), "date": pd.Timestamp("2025-01-06") + pd.Timedelta(7 * week + j % 7, unit="D"),
                             "area": area, "text": text, "label": label})
    pd.DataFrame(rows).to_csv(out / "demo_inquiries.csv", index=False)
    pd.DataFrame({"area": ["Example North", "Example South", "Example East"],
                  "latitude": [1.0, -1.0, 0.0], "longitude": [20.0, 20.0, 22.0]}).to_csv(out / "demo_areas.csv", index=False)
    return out / "demo_inquiries.csv", out / "demo_areas.csv"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["demo", "train", "predict"])
    p.add_argument("--data", type=Path)
    p.add_argument("--areas", type=Path)
    p.add_argument("--model", type=Path)
    p.add_argument("--surveillance", type=Path)
    p.add_argument("--out", type=Path, default=Path("results"))
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    if args.command == "demo":
        args.data, args.areas = demo_data(args.out)
    if not args.data or not args.areas:
        p.error("--data and --areas are required")
    df = read_inquiries(args.data, labeled=args.command != "predict")
    if args.command == "predict":
        if not args.model:
            p.error("predict requires --model (trusted local joblib file only)")
        model = joblib.load(args.model)
    else:
        model = train(df, args.out)
    extracted, weekly = summarize(df, model)
    extracted.to_csv(args.out / "extracted.csv", index=False)
    weekly.to_csv(args.out / "weekly_signals.csv", index=False)
    dashboard(weekly, args.areas, args.out, args.surveillance)
    print(f"Saved model/metrics where applicable, extracted.csv, weekly_signals.csv and dashboard.html to {args.out.resolve()}")


if __name__ == "__main__":
    main()
