# `elt/` — the ELT layer

Three sub-folders, three owners:

| Folder | Owner | Stage |
|---|---|---|
| `staging/` | Person 2 | DDL for the raw landing zone (`stg_flight_ops`) |
| `extract/` | Person 2 | OLTP → staging, no cleaning |
| `transform/` | Person 3 | staging → clean DataFrame |

Loading into the star schema is `warehouse/load/` (Person 4).

Extract-**Load**-Transform, not ETL: raw rows land untyped in
`stg_flight_ops` first, so a bad row is a *reportable defect* rather than a
crashed extract.
