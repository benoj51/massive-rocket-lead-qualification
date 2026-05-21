# Mount a persistent volume on Railway — long-term fix for cache loss

## The problem

Railway containers have an ephemeral filesystem. Every deploy starts a
fresh container, and anything written under `/app/cache` during the
previous container's life is gone. That's why notes, projects,
contacts have been disappearing on you.

## The proper fix (5 minutes via the dashboard)

Railway supports persistent volumes that survive redeploys. Mount one
at `/app/cache` and the platform never loses data again.

### Steps

1. Open https://railway.app → your project → the `web-production-b7cb5`
   service.
2. Click the **Variables / Settings** tab (the exact name varies by
   Railway version — look for a tab containing "Volumes" or "Storage").
3. Click **+ New Volume** (or **Attach Volume**).
4. **Mount path**: `/app/cache`
5. **Size**: 1 GB is plenty (we're storing JSON files; a hundred
   leads with full call history is maybe ~10 MB).
6. Save / Apply. Railway will restart the service automatically.

After the restart, every `cache/` write persists across deploys.

## Verification

After the volume mount:

1. Open the deployed app, add a note to any lead.
2. Trigger a redeploy (push a small commit, or click Redeploy in the
   Railway dashboard).
3. Open the same lead — your note should still be there.

If notes disappear again, the volume isn't mounted correctly. Open
Railway logs and look for the path `/app/cache` in the container's
mount table — `df -h /app/cache` from a Railway shell should show
the mounted volume, not the container's root.

## What about all the existing v1.0.0g protections?

The Notion-mirror backup (v1.0.0g) is a **safety net**, not a
substitute. With it in place:
- Every save (call, project, contact) writes a compressed JSON blob
  to the lead's Notion page in a hidden "State Backup" property.
- If the Railway cache wipes, the drawer surfaces an **⟲ Restore**
  button when it notices the local cache is empty + Notion has a
  backup for that lead.
- One click rehydrates that lead's full local state.

This protects historical data even if you forget to mount the volume.
**Mount the volume anyway** — restore is per-lead and manual; the
volume mount is permanent and automatic.

## What this release adds

v1.0.0g ships:
- `state_backup.py` — gather + encode + restore helpers
- `POST /api/lead/<id>/backup/mirror` — explicit "save backup now"
- `GET  /api/lead/<id>/backup` — JSON download of full state
- `POST /api/lead/<id>/restore` — pull from Notion and rehydrate
- `⟲ Restore` button in the drawer header — visible only when
  local cache for THIS lead is empty AND Notion has a backup
- Auto-mirror on every call save + project save
- "State Backup" as a writable Notion property (chunked rich-text,
  gzip+base64-encoded JSON — fits multi-KB payloads cleanly)

## A note on what's recoverable

If you've already lost data:
- **Lead-level fields** (status, vertical, fit summary, etc.) are
  in Notion — they survived. Open any lead and they'll still be there.
- **Calls, projects, contacts** that existed BEFORE v1.0.0g shipped
  don't have backups. They're gone unless someone has them somewhere
  else.
- **From v1.0.0g onwards**, every save writes a Notion backup. You
  can recover any lead by clicking Restore.

If you have screenshots or external records of any pre-v1.0.0g notes,
you can paste them back into the drawer manually — the Restore flow
is intended for after-redeploy gaps, not pre-feature recovery.
