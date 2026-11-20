# ADR-0009: Self-built auth: Argon2 passwords and a JWT in an HttpOnly cookie

- **Status:** Accepted
- **Date:** 2026-11-20
- **Tickets:** SMA-56 (decided by the project owner); applies to SMA-57 to SMA-61

## Context
v1.0 has no login: `AUTH_MODE=local` treats every request from this computer as one seeded
user. v1.1 (Stage 5) needs real accounts before anything is deployed publicly. The guide
left one question open until now: build auth ourselves, or use a hosted provider like Clerk.

What mattered:
- **This is a learning project.** Understanding passwords, tokens, cookies and CSRF is a
  goal, not a cost.
- **The design is already written for it** (guide section 9): an HttpOnly cookie, a
  double-submit CSRF token, and Bearer tokens for `/mcp`. The code is too:
  `get_current_user` is the only place that decides who the user is, and `users.password_hash`
  already exists.
- **Clerk** (checked 20 Nov 2026) is free up to 50,000 monthly retained users and brings
  sign-in screens, password reset, email verification and social login. But its session
  cookie is set by its JavaScript (not HttpOnly), users get a second id to map, tests would
  fake Clerk, local development needs internet and keys, user data would live at a third
  party, and MCP tokens would still be ours to build.

## Decision
Build auth ourselves with established libraries only (never hand-made crypto):

- **Passwords:** `pwdlib[argon2]`, `PasswordHash.recommended()` (Argon2id; the FastAPI docs'
  recommendation). The spike measured 86 ms per hash ([experiments/auth_spike](../../experiments/auth_spike/README.md)).
  At least 8 characters, at most 128, no "must contain a symbol" rules; email addresses are
  stored lower-case and unique.
- **Session token:** a JWT made with `PyJWT`, HS256, signed with `JWT_SECRET` from
  `backend/.env` (at least 32 random bytes; the app refuses to start in `jwt` mode without
  it). Claims: `sub` (user id), `iat`, `exp`. Lifetime **8 hours**, no refresh tokens in
  v1.1. Always decoded with `algorithms=["HS256"]` and `exp`/`sub` required.
- **Cookie:** `studymate_session`, `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`, max age
  8 hours. JavaScript can't read it; logout deletes it.
- **Login safety:** one message for "no such email" and "wrong password", and the same work
  in both cases (a dummy hash is checked when the email is unknown), so neither the answer
  nor its timing reveals which emails have accounts. Failed logins are limited per email and
  IP address.
- **`AUTH_MODE`:** `local` stays exactly as today for development (loopback only, the seeded
  user). New `jwt` mode: `get_current_user` reads and checks the cookie; still the only
  source of `user_id`. `ENV=production` requires `jwt`.
- **CSRF (SMA-58):** double-submit `X-CSRF-Token` header plus an `Origin` check on every
  state-changing request, as in the guide.
- **MCP personal access tokens (SMA-61):** long random tokens shown once; only a SHA-256
  hash is stored (a random 32-byte token can't be guessed, so it doesn't need a slow
  password hash), with an expiry and a revoke button.

## Consequences
- We learn and own the whole flow, it costs nothing, works offline, and tests stay fast
  (no outside service to fake).
- We also own the risk. Mitigations: well-known libraries, the decisions above, tests for
  every rejection path, and the two-account isolation suite (SMA-60).
- **Not in v1.1:** "forgot password", email verification, social login and two-step login
  (they need an email service). Until then, a forgotten password needs a script run by the
  admin. Each is a future ticket.
- A stolen cookie works until it expires (no server-side session list). The 8-hour lifetime
  and HttpOnly limit the damage; a token version per user can add "log out everywhere" later.
- Browsers accept `Secure` cookies on `http://localhost`, so development needs no HTTPS;
  SMA-59 confirms this in the browser.

## Alternatives considered
- **Clerk (hosted):** faster, with password reset, email checks and social login included,
  free for our scale. Rejected for v1.1: much less learning, a JavaScript-readable session
  cookie instead of HttpOnly, a second user id, outside dependency in tests and local
  development, and user data at a third party. Could be revisited if the app needs social
  login or 2FA.
- **Other hosted options (Auth0, Supabase Auth, Firebase Auth):** the same trade-off as Clerk.
- **Server-side sessions** (a random session id in the cookie, looked up in a `sessions`
  table on every request): easy to revoke, but one more table and query per request. A JWT
  needs no lookup, and the guide plans for one; revisit if "log out everywhere" becomes
  important.
- **Refresh tokens:** a short access token plus a long refresh token is the usual pattern
  for public APIs and mobile apps; too much moving machinery for v1.1's single web app.
