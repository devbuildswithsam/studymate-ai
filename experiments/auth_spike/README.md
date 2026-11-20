# Auth spike (SMA-56, ADR-0009)

Throwaway check that the libraries chosen for self-built auth behave the way
[ADR-0009](../../docs/adr/0009-self-built-auth.md) assumes. Not part of the app.

```bat
cd experiments\auth_spike
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python spike.py
```

## Result (20 Nov 2026, Windows 11, Python 3.12)

Installed: `pwdlib 0.4.2`, `argon2-cffi 25.1.0`, `PyJWT 2.15.1`. All 8 checks passed.

| Check | Result |
|---|---|
| One Argon2 hash (`PasswordHash.recommended()`) | **86 ms**: `argon2id`, 64 MB memory, 3 passes, 4 lanes |
| Right password verifies / wrong one fails | PASS / PASS |
| Same password hashes differently (random salt) | PASS |
| Valid token decodes to its user | PASS |
| Expired token, token signed with another secret, tampered token | all rejected |
| `"alg": "none"` token (no signature) | rejected |

## What it means for the app

- The stored hash string carries the algorithm, settings and salt, so the settings can be
  raised later and old hashes still verify.
- 86 ms per hash is fine for login, and expensive for someone guessing millions of passwords.
- PyJWT is only safe when decoding **names the allowed algorithm**:
  `jwt.decode(token, secret, algorithms=["HS256"])`. Never decode without it.
