"""DuckDB warehouse: star schema over the three source domains.

    dim_dosha  <──┬── fact_patient_intake        (patient cohort, PII-free)
                  ├── fact_prakriti_assessment   (constitution assessments)
                  └── dim_condition ──< bridge_condition_symptom >── dim_symptom
                                         (knowledge base)              │
                                                        symptom_alias ─┘  (audit trail)
    meta_run / meta_lineage / dq_check           (operational metadata)

The patient, assessment and knowledge-base domains share no record keys; ``dim_dosha``
and ``dim_body_system`` are the conformed dimensions that integrate them.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import duckdb
import pandas as pd

DDL = """
CREATE TABLE IF NOT EXISTS meta_run (
    run_id VARCHAR PRIMARY KEY, started_at TIMESTAMP, finished_at TIMESTAMP,
    status VARCHAR, code_version VARCHAR, config_sha256 VARCHAR
);
CREATE TABLE IF NOT EXISTS meta_lineage (
    run_id VARCHAR, source VARCHAR, origin VARCHAR, sha256 VARCHAR,
    rows_in INTEGER, rows_out INTEGER, admitted BOOLEAN
);
CREATE TABLE IF NOT EXISTS dq_check (
    run_id VARCHAR, source VARCHAR, check_name VARCHAR, value DOUBLE,
    threshold DOUBLE, passed BOOLEAN, blocking BOOLEAN, detail VARCHAR
);
"""

# Analytical tables are rebuilt on each run (full refresh); metadata tables append.
REBUILT_TABLES = (
    "dim_dosha",
    "dim_body_system",
    "dim_symptom",
    "symptom_alias",
    "dim_condition",
    "bridge_condition_symptom",
    "fact_patient_intake",
    "fact_prakriti_assessment",
)


@contextmanager
def connect(path: Path, read_only: bool = False) -> Iterator[duckdb.DuckDBPyConnection]:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path), read_only=read_only)
    try:
        yield con
    finally:
        con.close()


def init(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(DDL)
    _migrate(con)


def _migrate(con: duckdb.DuckDBPyConnection) -> None:
    """In-place upgrades for warehouses created by older versions (metadata is append-only,
    so it must survive schema changes rather than being rebuilt)."""
    cols = {r[0] for r in con.execute("DESCRIBE meta_lineage").fetchall()}
    if "kaggle" in cols and "origin" not in cols:  # v1.0 -> v1.1: URL sources added
        con.execute("ALTER TABLE meta_lineage RENAME COLUMN kaggle TO origin")


def replace_table(con: duckdb.DuckDBPyConnection, name: str, df: pd.DataFrame) -> None:
    if name not in REBUILT_TABLES:
        raise ValueError(f"{name} is not a rebuildable table")
    con.register("_staging", df)
    con.execute(f'CREATE OR REPLACE TABLE "{name}" AS SELECT * FROM _staging')
    con.unregister("_staging")


def append(con: duckdb.DuckDBPyConnection, name: str, df: pd.DataFrame) -> None:
    if df.empty:
        return
    con.register("_staging", df)
    cols = ", ".join(f'"{c}"' for c in df.columns)
    con.execute(f'INSERT INTO "{name}" ({cols}) SELECT {cols} FROM _staging')
    con.unregister("_staging")


# --- Cross-source views used by the dashboard's integrated clinician view ------------
VIEWS = """
CREATE OR REPLACE VIEW v_dosha_overview AS
WITH patients AS (
    SELECT dosha, COUNT(*) AS patients,
           AVG(CAST(diabetes AS DOUBLE)) AS diabetes_prevalence,
           AVG(age) AS mean_age
    FROM fact_patient_intake WHERE dosha IS NOT NULL GROUP BY dosha
), assessments AS (
    SELECT dosha, COUNT(*) AS assessments FROM fact_prakriti_assessment GROUP BY dosha
), conditions AS (
    SELECT dosha, COUNT(*) AS conditions,
           AVG(CASE WHEN prognosis IN ('difficult', 'incurable') THEN 1.0 ELSE 0.0 END)
               AS share_difficult_prognosis
    FROM dim_condition WHERE dosha IS NOT NULL GROUP BY dosha
)
SELECT d.dosha, d.components, p.patients, p.diabetes_prevalence, p.mean_age,
       a.assessments, c.conditions, c.share_difficult_prognosis
FROM dim_dosha d
LEFT JOIN patients p USING (dosha)
LEFT JOIN assessments a USING (dosha)
LEFT JOIN conditions c USING (dosha)
ORDER BY d.sort_order;

CREATE OR REPLACE VIEW v_cluster_by_system AS
SELECT s.cluster_id, s.cluster_label, c.body_system, COUNT(DISTINCT b.condition_id) AS conditions
FROM bridge_condition_symptom b
JOIN dim_symptom s USING (symptom_id)
JOIN dim_condition c USING (condition_id)
WHERE s.cluster_id >= 0
GROUP BY ALL;
"""


def create_views(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(VIEWS)
