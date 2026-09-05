# Operational data lifecycle

Galaxz local mode supports a per-category retention policy in
`config/retention.json`. Categories are `jobs`, `tasks`, `goals`, `reviews`,
and `artifacts`; values are integer day counts. A value of zero means data
older than the purge invocation is eligible for deletion.

`core.storage.lifecycle.SQLiteLifecycle.export()` creates a portable ZIP with
consistent SQLite snapshots and a `manifest.json` containing creation time,
sizes, and SHA-256 checksums. `verify_export()` validates the package before
restore. Purging removes expired rows and artifact objects, then unreferenced
object-storage payloads. Use dry-run mode in an administrative wrapper first.

Backups must be encrypted before leaving the host. The supported recipe is:

```sh
scripts/backup_operational.sh /var/backups/galaxz /path/to/secret-file /tmp/export.zip
scripts/restore_drill.sh /var/backups/galaxz/latest.zip.enc /path/to/secret-file /tmp/galaxz-restore
```

The scripts fail closed on missing inputs, use OpenSSL AES-256-CBC with PBKDF2,
write restrictive permissions, and verify the export manifest after decryption.
The restore drill never replaces a live database; it extracts into the supplied
clean directory. Monitoring should alert on non-zero exit status and on an
archive older than the configured backup SLA.
