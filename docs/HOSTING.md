# Hosting

GitHub-first architecture: repository for code/schema/importers, Actions for CI and reproducible refresh/build jobs, and Pages for the public static browser. Raw upstream datasets remain outside Git. `scripts/build_static_site.py` produces a browser-searchable entity index from a permitted SQLite snapshot.

When scale exceeds static hosting, keep GitHub as the code/CI/frontend control plane and move large artifacts to object storage and query workloads to PostgreSQL or a graph database/API. Never commit restricted data, credentials, or controlled-access human data.
