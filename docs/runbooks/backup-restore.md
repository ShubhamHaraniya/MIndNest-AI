# Backups and restoring

## What a backup contains

`scripts/backup.sh` writes one folder per run, for example `/srv/mindnest-backups/20261027-023000/`:

| File | What it holds |
| --- | --- |
| `db.dump` | Everything in the database: accounts, subjects, notes, chats, quizzes, planner, groups. |
| `files.tar` | Every uploaded file (and files shared in study groups), from file storage. |
| `SHA256SUMS` | Checksums, so a damaged copy is noticed before you rely on it. |

With `BACKUP_PASSPHRASE` set in `.env.production`, the first two are encrypted
(`db.dump.enc`, `files.tar.enc`) with AES-256. Without it they are plain files: then keep the
backup folder private (the script creates it readable only by its owner).

**Not in the backup, on purpose:** `.env.production`. Keep it (above all `SECRET_KEY`, and
`BACKUP_PASSPHRASE` if used) in a password manager. A backup plus the SECRET_KEY restores
everything; a backup without it restores everything except the students' saved AI provider keys,
which they would have to enter again. Lose the backup passphrase and encrypted backups are
unreadable, so store it separately too.

The backup does not stop the site. The database dump is a consistent snapshot; files uploaded
during the few seconds the file copy runs may or may not be included.

## Making one

```bash
scripts/backup.sh
```

Old folders are removed after `BACKUP_KEEP_DAYS` (default 14). Scheduling and off-server copies are
described in [production.md](production.md). One simple way to copy off-server, from another
machine:

```bash
rsync -a --delete-after you@server:/srv/mindnest-backups/ ~/mindnest-backups/
```

## Restoring

Use this after a disaster, or to move the site to a new server. On the (new) server, with the
code and the **same `.env.production`** in place:

```bash
scripts/restore.sh /path/to/20261027-023000
```

It verifies the checksums, asks you to type `RESTORE`, then: stops the website and workers, starts
the database, **replaces the database** with the backup, puts the files back, and starts
everything again (applying any newer migrations).

Afterwards open `https://your-domain/api/v1/ready`, sign in as an existing student, open a subject
and download one material to confirm that both the database and the files came back.

On a brand-new server do steps 1 and 2 of [production.md](production.md) first (so the database
volume and its roles exist), then run the restore.

## Practise before you need it

Once a month, restore the newest backup on a spare machine or a throw-away test server and look at
it. A backup that has never been restored is a hope, not a backup. The database part of the restore
was tested against a real Postgres while writing these scripts; the Docker wrapper around them has
not been run on a server, which is one more reason to do a practice restore early.

## Deleting a student's data

Students can delete their own subjects and materials in the app. Backups keep older copies until
they expire after `BACKUP_KEEP_DAYS`, which is worth mentioning in your privacy notice.
