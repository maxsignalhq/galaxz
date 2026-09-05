# Goal result substitution

Downstream planned tasks may reference results only from their declared
`depends_on` tasks. A reference occupies an entire JSON string value and uses:

```text
${{ dependencies.<task-uuid>.result.<path.to.value> }}
```

The resolver walks nested objects and arrays, copies the referenced value, and
stores the resulting immutable payload beside the planned task before its job
is enqueued. Object and array values may be substituted, including artifact
metadata such as `result.artifacts.primary.path`.

Resolution fails before execution when the UUID is not a declared dependency,
the dependency has no result, a path is missing, or the serialized resolved
payload exceeds 64 KiB. Logs identify the task and error but never include the
interpolated value.
