# Going live: running MindNest AI on a server

This is the whole path from an empty Linux server to students signing in. Allow an afternoon the
first time, mostly waiting for downloads. Nothing here was run on a real server while writing it,
so do the first pass on a cheap test machine and fix anything that surprises you before real
students arrive (the notes in "If something fails" help).

## What you need

- A Linux server (Ubuntu 24.04 is fine) with a public IP address.
  - With the built-in model service on CPU (`models` profile): 4 CPU cores, **12 GB RAM**, 40 GB disk.
  - Without it (models on another machine, see below): 2 cores, 4 GB RAM, 30 GB disk.
- A domain name whose DNS "A" record points at the server's IP.
- Docker with the Compose plugin: <https://docs.docker.com/engine/install/>.
- A mail provider with SMTP (for confirmation and password-reset emails). Any ordinary one works:
  you need its host, port, login and a sender address on your domain.
- Optional: a Google Cloud OAuth client for "Continue with Google" and Calendar sync
  (see [google-oauth.md](google-oauth.md); register the **https** addresses).
- Open the firewall for ports 22 (so you can log in), 80 and 443 only. Nothing else is published by
  the stack: the database, Redis and file storage have no ports on the server at all.

## 1. Get the code and write the settings

```bash
git clone <your repository> mindnest && cd mindnest
cp .env.production.example .env.production
chmod 600 .env.production
```

Fill in every empty value of `.env.production` (the comments explain each). Make secrets with:

```bash
openssl rand -hex 24                                         # passwords and keys
python3 -c "import secrets; print(secrets.token_urlsafe(48))"  # SECRET_KEY
```

Then check the file. This reads it and prints every problem; it never prints the secrets:

```bash
scripts/prod.sh check
```

It refuses development passwords, short or repeated secrets, `localhost` addresses, mail settings
without encryption, and so on. Fix everything it reports.

**Save SECRET_KEY in a password manager now**, outside the server. It encrypts the AI keys students
save in Settings. If you lose it, a restored backup cannot decrypt them and every student has to
enter their key again.

## 2. Start

```bash
scripts/prod.sh up -d --build
scripts/prod.sh ps
scripts/prod.sh logs -f api
```

The first build downloads a few GB and takes 10 to 20 minutes. The first start of the `models`
service downloads the two language models (a few GB more); the site works meanwhile, but search and
uploads only finish once `scripts/prod.sh logs models` says both models are ready.

Caddy asks Let's Encrypt for the certificate on its own when the first visitor arrives (or at
start). If it cannot, `scripts/prod.sh logs caddy` shows why; almost always it is DNS not pointing
at the server yet, or port 80/443 blocked.

Check from your own computer:

- `https://your-domain/api/v1/ready` shows `{"status":"ok","database":"ok"}`.
- `https://your-domain/login` opens the sign-in page, over HTTPS, with the lock icon.
- `https://your-domain/api/docs` shows "Not Found". (The interactive API docs are switched off
  in production.)

## 3. Create the first administrator

Sign up on the site with your own email and open the confirmation link from your inbox. Then:

```bash
scripts/prod.sh run --rm migrate python -m mindnest_core.adminctl grant you@your-domain.org
```

Reload the site: the **Admin** item appears in the menu. More in [admin.md](admin.md).

## 4. Turn on backups

Run one by hand and make sure you can restore it (see [backup-restore.md](backup-restore.md)).
Then schedule it:

```bash
( crontab -l 2>/dev/null; echo "30 2 * * * cd $PWD && scripts/backup.sh >> /var/log/mindnest-backup.log 2>&1" ) | crontab -
```

Copy the backup folder off the server too (another machine or a storage bucket). A backup that
lives only on the server dies with the server.

## Updating to a new version

```bash
git pull
scripts/prod.sh up -d --build
```

Database changes are applied automatically by the `migrate` step. Take a backup first
(`scripts/backup.sh`) for anything bigger than a small fix.

## Everyday commands

| What | Command |
| --- | --- |
| What is running | `scripts/prod.sh ps` |
| Follow a log | `scripts/prod.sh logs -f api` (also `worker`, `eval-worker`, `web`, `caddy`, `models`) |
| Restart one part | `scripts/prod.sh restart api` |
| Stop everything (data is kept) | `scripts/prod.sh down` |
| Disk used by Docker | `docker system df` |
| Open a database prompt | `scripts/prod.sh exec postgres psql -U mindnest -d mindnest` |

Use a free uptime monitor (UptimeRobot, Better Stack and similar) on `https://your-domain/api/v1/ready`
so you hear about an outage before students do.

## Using another machine for the models (for example one with a GPU)

Leave `models` out of `COMPOSE_PROFILES`, run the model service on the other machine
(`uvicorn mindnest_models.main:app --host 0.0.0.0 --port 8100`, see the README), and set
`MODEL_SERVICE_URL=http://<its private address>:8100`. **The model service has no login.** Only ever
expose it on a private network or VPN, never on the public internet; prodcheck cannot see your
firewall, so this one is on you.

## Using a hosted bucket instead of the bundled storage

Create a private bucket with any S3-compatible provider, set `S3_ENDPOINT_URL` (https), `S3_ACCESS_KEY`,
`S3_SECRET_KEY`, `S3_BUCKET`, and remove `storage` from `COMPOSE_PROFILES`. The app talks to the
provider with region `us-east-1`, which S3-compatible services such as Cloudflare R2, Backblaze B2
and Wasabi accept. Plain AWS S3 buckets in another region are not supported yet.

## Changing a password later

Database passwords are set only when the data volume is first created. To rotate one, change it in
`.env.production` **and** in the database, then restart:

```bash
scripts/prod.sh exec postgres psql -U mindnest -d mindnest -c "ALTER ROLE mindnest_app PASSWORD 'the-new-password'"
scripts/prod.sh up -d
```

(`mindnest` is changed the same way, and its new password also goes into `POSTGRES_PASSWORD`.)
Do not rotate `SECRET_KEY` unless you accept that every saved AI key stops working.

## Where the real client address comes from

The API limits sign-ins and sign-ups per address, and reads the address from the first entry of
`X-Forwarded-For`. In this setup that is safe because **only Caddy is reachable from outside and
Caddy replaces that header** with the address it actually saw. If you put another proxy or a CDN in
front of Caddy, or publish the `web` or `api` ports, visitors can forge the header and dodge the
limits. Keep the layout as shipped.

## If something fails

| Symptom | Likely cause |
| --- | --- |
| `scripts/prod.sh up` stops with "... is not set" | A value is missing in `.env.production`. |
| `migrate` exits with "Roles mindnest_app and mindnest_eval are missing" | The data volume was created before the role script ran. On a **new, empty** install: `scripts/prod.sh down -v` and start again. With real data, create the roles by hand (see `infra/compose/initdb-prod/01-roles.sh`). |
| `api` restarts with "SECRET_KEY must be changed" | `SECRET_KEY` is still the development value. |
| Browser shows a certificate error | DNS does not point here yet, or ports 80/443 are closed. `scripts/prod.sh logs caddy`. |
| Sign-up works but no email arrives | Wrong SMTP details; the API logs "Could not send email" with the reason. Check spam, and that your provider allows the sender address. |
| Uploaded files stay "processing" | The `models` service is still downloading (see its log), or has run out of memory (`docker stats`). |
| Students get "AI key" errors | Normal until they save their own provider key in Settings (the app uses students' own keys). |
| "Continue with Google" does nothing | The https redirect URIs in Google Cloud Console must match your domain exactly. |
