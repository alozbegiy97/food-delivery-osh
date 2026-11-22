# Empty PostgreSQL init directory

This folder is mounted over `/docker-entrypoint-initdb.d` in the `db` and
`db-test` containers. It replaces the `postgis/postgis` image's own init
script so that the PostGIS extension is installed **only** by the Alembic
migration `0001_enable_postgis` (Alembic is the single schema mechanism).

The entrypoint only executes `*.sh`, `*.sql` and `*.sql.gz` files, so this
README is ignored. Do not add schema scripts here.
