# SQLite migrations

Migration version `1` is the `MIGRATION_001` SQL constant in `cdh_d01/database.py`. `migrate()` executes it transactionally and records the version in `schema_migrations`. The migration is idempotent for a version-1 database and creates all tables, indexes, constraints, and six append-only triggers.

No root-level project metadata or shared migration system is modified by D01.

