# Behavioral analytics

The application automatically records pseudonymous routine-use indicators without a post-interaction questionnaire.

Indicators:
- unique users: distinct pseudonymous user hashes
- sessions: distinct application session IDs
- return visits: number of sessions associated with each pseudonymous user hash
- user messages: processed user inquiries
- conversation turns: paired user-message/assistant-response counts
- session duration: seconds between first and last recorded activity
- requested STI topics: topic/intent attached to each processed user message
- response completion: completed responses divided by assistant responses
- drop-off: session containing a user message but no completed assistant response
- service-link interactions: recorded clicks for testing, prevention, and referral resource buttons

Limitations: browser/session state is not a durable identity mechanism; clearing browser state, changing device, redeployment, or SQLite loss can affect unique-user and return-visit estimates. These metrics are behavioral analytics, not clinical outcomes.


## V6 aggregate NLP reporting
Raw NLP JSON is hidden from learners. Predicted intent and extracted STI topic, symptom, exposure and duration values are recorded as pseudonymous events and shown to administrators only as grouped counts. Empty extraction means no supported phrase was matched; it is not evidence that a symptom or condition is absent.
