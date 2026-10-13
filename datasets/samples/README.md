# Synthetic demonstration files

All company statements and numbers in this directory were created for NexusAI tests and demos. They do not describe a real company, employee policy or financial result. Dates and currency labels are illustrative.

- `hr-policy.txt`: source-location and policy-retrieval demonstration.
- `operations-note.txt`: support-hours/retention search, plus a note illustrating why retrieved statements do not prove causation.
- `sales.csv`: two illustrative monthly observations. In Phase 3 these are indexed as textual CSV records, not imported into an analytics fact table. Do not treat two observations as a training dataset or anomaly benchmark.

PDF and DOCX fixtures are generated in memory by `tests/test_parsing.py`; these verify extraction without committing generated binary artifacts.
