# V16 ML information extraction

The application uses a **multi-label supervised text classifier** for extracting mentions of STI names, symptoms and exposure indicators. Architecture: character n-gram TF-IDF (2–5) and one-vs-rest logistic regression. It runs in addition to conservative rule-based matching. Durations remain regex-extracted.

- Input: learner question (English or Kiswahili).
- Output: lists of named STI topics, symptom mentions, exposure indicators, duration expressions.
- Admin analytics: `sti_topic_detected`, `symptom_detected`, `exposure_detected`, `duration_detected` counts.
- The model does **not** diagnose disease or establish that symptoms are present; it extracts text mentions.
- The model is trained on synthetic, hand-authored phrases expanded using templates. `data/entity_training.csv` and `data/entity_test.csv` document its provenance.
- The held-out templates reuse vocabulary and phrases from training, so the reported evaluation is a **sanity check, not independent validation**. Do not claim clinical or real-world accuracy from these metrics.
- Rule matching supplements the learned model for explicit phrases. Negation handling is incomplete; test carefully before using data for health research.
- Raw learner text is not used to retrain the model automatically.
- Existing admin aggregates record new submissions only; past usage events are not reconstructed.
- Existing content approval policy is unchanged: only approved content is displayed.
