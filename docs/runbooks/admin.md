# Admin page

The **Admin** menu item appears only for accounts marked as administrators. Nobody can become an
administrator from the website; it is done on the server, as the database owner.

## Make someone an admin

The person must first sign up and confirm their e-mail address. Then, in the project folder:

```
docker compose run --rm migrate python -m mindnest_core.adminctl grant you@example.com
docker compose run --rm migrate python -m mindnest_core.adminctl list
docker compose run --rm migrate python -m mindnest_core.adminctl revoke you@example.com
```

(Running it as `migrate` uses the database owner's login, which the API itself never has in production.)
Each grant and revoke is written to the activity log. Rights take effect on the next page load.

## What an admin can and cannot see

- **Can see:** counts (accounts, files, storage, questions asked, AI answers and failures, quizzes,
  groups), each student's name, e-mail address, status, join date, last-seen date and usage counts,
  the name, group and report reasons of reported files, and how often the AI safety layer stepped in.
- **Cannot see:** any student's files, notes, chats, quizzes, assignment drafts, calendar or AI keys.
  This is enforced inside the database (row-level security still applies to admins), not just in the page.
- **Can do:** suspend or reactivate a student account (they are signed out at once; their data is kept),
  remove a reported shared file, or dismiss the reports on it. Admin accounts cannot be suspended here.
- **Every change is logged** with who did it, to whom and the reason given (Safety and activity tab).

## Suspending a student

Students tab, **Suspend**. Add a reason (it is kept in the log). They cannot sign in again, by password or
Google, until you press **Reactivate**.

## Reported files

Group members can report a file in a study group. After 3 different reports it is hidden from the group.
The Reports tab lists every reported file with the reasons and notes. **Dismiss reports** brings the file
back; **Remove file** deletes it for good (students who already copied it into their own subjects keep
their copy).
