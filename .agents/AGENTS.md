# RCKangaroo Project Rules & Directives

> [!IMPORTANT]
> **CRITICAL DIRECTIVE: NEVER DELETE OR OVERWRITE IMPORTANT FILES OR DATABASE RECORDS**

1. **Database & Offsets Protection**:
   - NEVER drop tables, clear jobs, or delete `pool.db` records without explicit confirmation.
   - ALWAYS preserve `current_offset_hex`, completed chunk records, and saved hex offsets for Puzzle 140.
   - ALWAYS perform automatic startup backups of `pool.db` before applying schema or structural updates.

2. **Official Scripts & Deployment Directive**:
   - ALWAYS use official deployment and inspection scripts:
     - `e:\RCkangaroo\pool\deploy_vps.py`
     - `e:\RCkangaroo\pool\fetch_live_vps.py`
   - DO NOT create disposable diagnostic scripts when official scripts already exist.

3. **Concurrency & SQLite Safety**:
   - Maintain SQLite `PRAGMA journal_mode = WAL;` and `busy_timeout = 60000;` at all times.
   - Use atomic updates with `db_lock` for chunk assignments, heartbeats, and job completion.

4. **Range Preservation**:
   - Map worker names (e.g. `Vast-2x-A1` .. `Vast-2x-A10`) cleanly to their assigned ranges (`0-10%`, `10-20%`, ..., `90-100%`).
   - Reassign abandoned `ASSIGNED` chunks (timeout > 20 mins) back to `PENDING` status before advancing `current_offset_hex`.
