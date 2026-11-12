# SPEC-registration

| | |
|---|---|
| Module | `registration` |
| Status | Approved 2026-11-04; implemented and locally verified 2026-11-05 (see `tasks/todo.md`) |
| Depends on | Existing account API |
| SRS | FR-AUTH-01…02 |

## 1. Objective

Make valid registration work reliably and make invalid registration easy to correct without weakening account security. Fix the reproduced validation gap; do not claim it is the user's exact incident without their error message.

## 2. Commands

Run from the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_patients.py -q
npm --prefix web test -- src/test/Auth.integration.test.jsx src/test/App.system.test.jsx
npm --prefix web run build
```

## 3. Structure

- `web/src/pages/Auth.jsx`: validation, inline errors, focus, and submitting states.
- `smriti/models.py`, `smriti/app.py`, `api/routers/auth.py`: server validation and registration/session contract; change only where the confirmed cause requires it.
- `web/src/lib/api.js`: preserve structured API error data for the form; avoid account-specific logic in the shared request helper.
- `tests/test_patients.py`, `web/src/test/Auth.integration.test.jsx`, `web/src/test/App.system.test.jsx`: regressions and existing consumers.
- `docs/API.md`: document any changed validation response; retain `error.code`, `message`, and `field`.

## 4. Code style

Follow existing functions, Pydantic constraints, and controlled inputs. Passwords are never trimmed or included in errors. Username and alias validation use the same trimmed values sent to the API.

```jsx
<input aria-invalid={Boolean(fieldError)} aria-describedby={fieldError ? "username-error" : undefined} />
```

## 5. Testing strategy

Backend integration tests cover valid registration/session, duplicate username, short/invalid username, short password, blank alias, and unchanged existing ownership behavior. Frontend tests cover client-side rejection without a request, server-field errors, preserved input, focus on the invalid field, double-submit prevention, and recovery. Run axe on registration as well as login. Test credentials are synthetic; never use the live patient database.

## 6. Boundaries

- **Always:** enforce username 3–32 characters with letters, digits, `.`, `_`, `-`; password 8–128 characters; alias 1–64 characters. Keep useful errors readable without relying on color.
- **Ask first:** credential-policy changes, account-claim behavior changes, database repairs, or new authentication dependencies.
- **Never:** print credentials, expose validation input objects, weaken hashing/cookies, clear other accounts, or replace generic login errors with account-existence disclosures.

## 7. Success criteria / traceability

| Requirement | Acceptance |
|---|---|
| FR-AUTH-01 | Invalid fields get actionable linked errors and focus; valid input creates one account and a working session. Both direct API calls and UI calls enforce constraints. |
| FR-AUTH-02 | Duplicate username, unreachable server, and read-only demo errors retain valid inputs and permit correction. Busy submission cannot switch modes or submit twice. Login and legacy-account tests continue to pass. |

Remove decorative layout copy from the touched form, not input labels, credential requirements, or privacy/ownership information users need before acting.

## 8. Open questions

The user's exact registration error has not been supplied. Implement and verify the reproduced validation fix first; if the reported incident persists, request its message and server error type without passwords.
