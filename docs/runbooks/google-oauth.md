# Setting up Google (sign-in and Calendar)

One Google Cloud OAuth client serves two features: **Continue with Google** (sign-in) and **Google
Calendar sync** (optional, on the Calendar page). Both turn on with the same two settings.

The button only appears when `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are set. Without them the
app works exactly as before (email and password). Setup takes about ten minutes and costs nothing.

## 1. Create the OAuth client (Google Cloud Console)

1. Open <https://console.cloud.google.com/> and create a project (or pick one), for example `mindnest-ai`.
2. Go to **APIs & Services → OAuth consent screen** (newer consoles call it **Google Auth Platform**).
   - User type / Audience: **External**.
   - App name: `MindNest AI`. Support email and developer contact: your email.
   - Scopes: you only need `openid`, `email` and `profile` (they are the defaults).
   - While the app is in **Testing**, add every Google account that should be able to sign in under
     **Test users** (up to 100). Move to **In production** when you are ready for everyone; plain
     sign-in with these three scopes does not need Google's verification review.
3. Go to **APIs & Services → Credentials → Create credentials → OAuth client ID**.
   - Application type: **Web application**.
   - **Authorized redirect URIs**: add exactly
     `http://localhost:3000/api/v1/auth/google/callback` (sign-in) and
     `http://localhost:3000/api/v1/integrations/google-calendar/callback` (Calendar sync)
     (for a real domain later, add the same two paths on `https://your-domain` as well).
   - Leave "Authorized JavaScript origins" empty. Nothing runs in the browser; the server does the exchange.
4. Copy the **Client ID** and **Client secret**.

## 2. Give them to MindNest

Add to the `.env` file in the project folder (next to `compose.yaml`):

```
GOOGLE_CLIENT_ID=1234567890-abc.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-...
```

Then restart the API: `docker compose up -d --build api`.

Open <http://localhost:3000/login>: a "Continue with Google" button should appear above the form.

## 3. Google Calendar sync (optional)

1. In the same Google Cloud project open **APIs & Services → Library**, search for **Google Calendar API**
   and press **Enable**.
2. In **OAuth consent screen → Data access (Scopes)** add the scope
   `https://www.googleapis.com/auth/calendar.app.created`. It lets MindNest create its own calendar
   named "MindNest AI" and manage events on that calendar only. It cannot read or change any other
   calendar or event. While the app is in **Testing**, add each student's Google account under Test users.
   Before opening it to everyone, check on the consent screen whether Google asks for verification for
   this scope (its sensitivity can change; Google's scope list is the source of truth).
3. Make sure the second redirect URI from step 1 is registered.
4. Restart the stack so the calendar service starts too: `docker compose up -d --build`
   (it adds a service called `calendar-mcp`; check it with `docker compose ps`, it should be
   "healthy"). The **Google Calendar** card appears on the Calendar page.

How it behaves: the student presses **Connect**, accepts the permission, then **Review changes**. The
list shows exactly which exams, assignment deadlines and planned study tasks would be added, updated or
removed, and only the ticked ones are sent, as all-day events that do not block time. Disconnecting
stops sending and can also delete the "MindNest AI" calendar. If Google stops accepting the saved
permission (for example the student removed MindNest in their Google account), the card asks them to
connect again.

## Check it on your real Google Calendar

The automated tests replace Google with a fake, so do this once yourself. You need a Google account
that is listed under **Test users** (or any account once the app is published).

1. Open the Calendar page, press **Connect**, accept the permission. You come back to a green notice.
2. Open <https://calendar.google.com/>. In the left list under **My calendars** there is now a calendar
   called **MindNest AI**. (If it is hidden, tick it.)
3. In MindNest open **Chat** and write: `Add a 45 minute study session on <a day this week> at 18:30 called Revise cells`.
4. The chat shows an **Add to Google Calendar** card and **nothing is on Google yet**. Press **Approve**.
   The card turns green with **Open in Google Calendar**.
5. Look at Google Calendar: the event is there, on the MindNest AI calendar, at the right time. Click
   the link on the card: it opens that same event.
6. In chat write `Move it to 19:30`. A card shows the old and the new time. Press **Approve**. Refresh
   Google Calendar: the event moved.
7. In chat write `Cancel it`. Approve. The event is gone from Google Calendar.
8. Try **Cancel** on a card, and try pressing Approve on an old card after sending another message:
   nothing is sent, and the old card says it expired.

If a step fails, the card or the chat says why. The usual causes:

| What you see | Cause and fix |
|---|---|
| Connect ends with "Google Calendar could not be set up" | The **Google Calendar API** is not enabled for the project (step 1 of section 3). Enable it, wait a minute, connect again. |
| Google shows "access blocked" or "app not verified" | The account is not under **Test users**, or the consent screen has not been published. |
| "redirect_uri_mismatch" | The Calendar redirect URI in step 1 is missing or differs from `WEB_BASE_URL` (check `localhost` vs `127.0.0.1`). |
| Chat says Google Calendar needs to be connected again | Google refused the saved permission (removed under your Google account's security page, or the refresh token expired in Testing mode after 7 days). Press Connect again. |
| Chat or the Calendar page says the calendar service could not be reached | The `calendar-mcp` service is not running: `docker compose ps`, then `docker compose logs calendar-mcp`. |
| Events appear on the page's sync but the card says "not connected" | Connect again; the first connection did not finish making the "MindNest AI" calendar. |

While the consent screen is in **Testing**, Google expires the saved permission after 7 days, so
students have to connect again weekly until the app is published.

## What to expect

- A new student signing in with Google gets an account at once, with the email already confirmed.
- A student who already has an account with the same email is linked to it. If that account's email was
  never confirmed, its password is removed at that moment (so nobody who typed someone else's address
  at sign-up can keep access).
- Google-only accounts have no password. They can still choose one later with "Forgot your password?".
- If the page shows "Google sign-in did not work", check that the redirect URI above matches
  `WEB_BASE_URL` exactly (`localhost` and `127.0.0.1` count as different addresses), and that the
  account is listed as a test user while the app is in Testing.

## Keep secret

The client secret is a password. Keep it only in `.env` (already git-ignored) and never paste it
into chat, screenshots or the repository.
