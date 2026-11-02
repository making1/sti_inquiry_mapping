# Integrated STI inquiry assistant and mapping

This package combines your V18 Streamlit assistant with the standalone STI inquiry mapping pipeline. Your original V18 and Project 1 folders were not modified. Private databases and real secrets are excluded.

## Start on Windows

Extract this package to a new folder. In PowerShell, change to that folder and run:

```powershell
python -m pip install -r requirements.txt
$env:ADMIN_USERNAME = "research_admin"
$env:ADMIN_PASSWORD = Read-Host "Choose an admin password"
python -m streamlit run app.py
```

The requirements pin scikit-learn 1.8.0 to match V18's bundled model files. Install them before launching.

Open the local URL printed by Streamlit, normally http://localhost:8501. Select **Admin**, sign in with the credentials you configured, then open **Mapping & validation**.

The credential variables apply to this terminal session. For hosted use, configure Streamlit Secrets as described in the existing README. The package starts with a fresh database, and educational content remains pending review until an actual reviewer approves it.

## What is integrated

- **Learner assistant:** existing English/Kiswahili sequential chat, V18 ML-assisted extraction, consent collection, content approval and analytics.
- **Weekly inquiry signals:** queries existing consented inquiry records, links only consented demographic profiles, and uses recognized county centroids. Select “Reporting coverage…” to calculate weekly trends, a county-week map, exploratory signal flags and downloadable aggregates.
- **Verified surveillance rates:** upload aggregate `area,period,confirmed_cases,population` CSV. Displays rates per 100,000, a chart and map for recognized county names. This information is separate from inquiry counts and is not persisted to SQLite.
- **Model validation:** displays bundled V18 evaluation artifacts, plus a separate TF-IDF/logistic regression training experiment with a chronological holdout. Upload independently annotated `inquiry_id,date,area,text,label` data, optionally `user_id`, then run validation and download metrics. It does not replace V18's deployed models or train automatically on private conversations.
- **Standalone pipeline:** `pipeline.py` is also available for the original command-line workflow and synthetic demo: `python pipeline.py demo --out demo_results`.

## Live map data

In the learner interface, explicitly consent to both inquiry storage and demographic storage and enter a recognized county name such as `Nakuru`. A county-week needs **five distinct consented sessions**, not five messages from one session. Current incomplete UTC weeks are excluded. A releasable signal baseline needs eight preceding completed weeks, each with at least five distinct sessions. These protections mean a new database will not immediately show signals. The existing V18 overall county map remains available and uses its original all-time threshold.

No demo data is inserted into the live database. Existing V18 synthetic datasets remain clearly separate in `data/` and `evaluation/`.

To use existing V18 records, stop both apps and back up the existing `sti_app.db`. You may then copy that database into the integrated folder before starting it. The existing table schemas are unchanged; no automated data migration is needed. Keep that database private and do not add it to GitHub or a shared ZIP.

## Interpretation and validation limits

Inquiry counts are information-seeking activity, not diagnosed infections, prevalence or confirmed outbreaks. The signal heuristic uses the previous eight completed weeks: mean plus three standard deviations, with an SD floor of one. Sparse county-weeks and derived baselines that could expose them are suppressed. A missing signal value means insufficient releasable history. Signals require independent epidemiological validation; no automated allocation policy is included.

Latest consented county profile per session is used, following V18. Sessions are not necessarily unique people. Missing reporting cannot be distinguished from zero activity. The existing V18 overall analytics and historical daily charts retain their original behavior; the stricter county-week protections apply to the new panel and its CSV.

Surveillance CSV rows must be aggregate records that you are authorized to analyze. Uploaded case rates are not estimates of prevalence. For a prevalence measure you need an appropriate infected-person numerator, time definition and population denominator, or a validated representative estimator. No such estimator or confirmed outbreak detector is supplied here.

Classifier validation removes exact duplicate texts and overlapping known users from the training side of the temporal split. It evaluates intent classification, not entity extraction or outbreak detection. V18's bundled scores are synthetic prototype results. Validate extraction with independent mention annotations, and evaluate alerts against external outbreak definitions and dates before operational decisions.

The experiment temporarily writes uploaded training data to the operating system's temporary folder, removes it after execution, and retains metrics in the admin session. The TF-IDF model is discarded after that experiment. No raw inquiry exports or replacement model downloads are added to the interface.

## Tests

```powershell
python -m unittest discover -s tests -v
```

See `VALIDATION.txt` for checks actually performed on this integrated version. See the original `README.md` and `docs/` for V18's content governance and persistence limitations.
