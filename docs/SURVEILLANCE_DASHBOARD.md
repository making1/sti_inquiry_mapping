# V17 inquiry signals and data-quality dashboard

Admin → Usage analytics → STI inquiry signal maps, trends and technical discrepancy report.

**Not prevalence or outbreak surveillance.** Mentions are not cases; no population denominator, verified diagnosis or representative sampling. The dashboard shows consented inquiry counts and only maps counties with >=5 distinct consented sessions. County markers are approximate centroids. Unknown towns/counties are not geocoded.

QA: malformed stored extraction, rules-only versus ML-assisted disagreement, missing consented demographics and unrecognized counties. Disagreement is not a measured model error. No sensitive raw text is exported.

For legitimate prevalence or outbreak reports, ingest verified, licensed epidemiological records with documented disease definition, confirmed cases, reporting interval, geographic coverage, population denominators and health-authority approval. These records are **not** bundled.

Caveats: synthetic ML model is not clinically validated; location is self-reported; Streamlit Cloud SQLite storage may reset; analytics events are not backfilled.
