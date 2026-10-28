# Migration recovery guard

`migrate_once.py` no longer infers that migrations 001–010 ran merely because
`core.tenants` exists. Recovery is an explicit operator assertion: only after
independently confirming every fixed contract/001–010 file was committed in
the documented initial provisioning incident may the operator set
`EVO_RECOVER_INITIAL_PROVISIONING=1`. Recovery never records 011, later files,
or the seed; normal processing applies them. Database or ledger lookup errors
stop processing rather than being mistaken for unapplied files.

If 011 is already marked but `runtime.performance_measurements` is absent,
the script stops without changing the marker. An operator must inspect and
reconcile the actual database and ledger before retrying. The presence of that
table is only a basic inconsistency check; it does not prove the full migration,
permissions, policies or triggers are correct. The script has not inspected or
modified the live database.
The previous recovery could also have falsely marked any other future file
present at the time. The operator must audit such existing markers against
deployment evidence; this patch does not validate them or erase them.

Migration SQL execution and ledger marking remain separate transactions; a
crash between them can leave an applied migration unrecorded. Investigate such
cases rather than blindly replaying an unknown non-idempotent migration.
Apply 011 before deploying the new API through the approved release flow.
