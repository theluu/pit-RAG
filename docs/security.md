# Security notes

- Answers abstain when retrieval evidence is weak and citations can only reference known provision IDs.
- Document text is treated as data, never as instructions.
- JWTs carry subject and role; production must use a rotated secret, short expiry and a real identity store.
- A per-client request limit protects API routes. Use Redis-backed distributed limits for multiple replicas.
- Before public upload support, add MIME sniffing, size limits, malware scanning, object-store encryption and curator approval.
- Do not log raw user questions in public evaluation datasets. Audit administrative ingest, re-index and configuration changes.

The application is a research tool and must prominently state that it does not replace professional legal advice.
