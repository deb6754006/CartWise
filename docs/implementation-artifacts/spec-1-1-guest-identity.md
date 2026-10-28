---
title: 'Story 1.1: שימוש כאורח (זהות מכשיר)'
type: 'feature'
created: '2026-10-28'
status: 'done'
baseline_revision: '21dd917c5e2f397cf918bddb7e47424d4959bdf8'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/docs/implementation-artifacts/epic-1-context.md'
  - '{project-root}/docs/planning-artifacts/architecture/architecture-CartWise-2026-10-26/ARCHITECTURE-SPINE.md'
  - '{project-root}/CLAUDE.md'
warnings: ['oversized']
deferred:
  - summary: >-
      AC1 ו-AC2 של ה-Epic, יצירת רשימה, השוואה ומכסה לפי מכשיר, ייבדקו מקצה לקצה רק אחרי Epics 2, 5 ו-8.
    evidence: |-
      ה-Story סיפק את השכבה: Subject מסוג device. כדי להכריע: בדיקות ב-Stories 2.1, 5.x ו-8.1, ו-E2E של Flow 6.
    severity: medium (unverified)
  - summary: >-
      install_id עובד כמו סיסמה קבועה, ואין rate limit על POST /v1/devices.
    evidence: |-
      maybe-false. להכריע ב-Story 10.3 (NFR-10, הגבלת קצב) וב-Story 1.2 (App Check).
    location: >-
      backend/app/modules/identity/routes.py
    severity: medium (unverified)
  - summary: >-
      אין revocation או רוטציה של device tokens (אין jti או kid).
    evidence: |-
      בחירת design. ייבחן ב-Story 1.2, יחד עם users ו-App Check.
    location: >-
      backend/app/core/tokens.py
    severity: low (unverified)
---

<intent-contract>

## Intent

**Problem:** אורח צריך להשתמש באפליקציה בלי הרשמה (FR-1), אבל השרת לא מזהה אף אחד. `core.auth.get_subject` הוא stub שמחזיר תמיד anonymous, ולכן אין למה לקשור רשימות, העדפות ומכסה של אורח (AD-11, AD-12).

**Approach:** האפליקציה רושמת את המכשיר אוטומטית בהפעלה הראשונה, ומקבלת device token חתום. השרת מזהה מכל בקשה `Subject` מסוג device. כל זה קורה בלי שום מסך הרשמה. רשימות, השוואה ומכסה (Epics 2, 5 ו-8) ייבנו על ה-`Subject` הזה.

## Boundaries & Constraints

**Always:**
- `core.auth.Subject` הוא המקור היחיד לזהות בשרת (AD-12). אף endpoint לא מפענח token בעצמו.
- device token הוא JWT מסוג HS256, עם הטענות `sub` (device_id), `typ: "device"`, `iat` ו-`exp`. תוקף ברירת המחדל הוא 30 יום. הסוד מגיע מ-`DEVICE_TOKEN_SECRET`. כש-`ENV=prod`, הסוד חובה, ולא יכול להיות ערך ברירת המחדל של dev.
- בשרת נשמר רק hash מסוג SHA-256 של מזהה ההתקנה. המזהה עצמו לא נשמר. אין שם, טלפון או מייל.
- token לא מופיע בלוגים, ולא בגוף שגיאה.
- באפליקציה, מזהה ההתקנה וה-token נשמרים ב-`expo-secure-store` בלבד.
- האפליקציה עובדת גם כשהרישום נכשל, למשל כשאין רשת. הרישום רץ ברקע, ולא חוסם את הרינדור.
- שגיאות בפורמט AD-13.

**Never:**
- אין מסך הרשמה או התחברות, אין Firebase ואין טבלת `users`. כל אלה ב-Story 1.2.
- אין App Check. הוא דורש פרויקט Firebase, ונדחה ל-Story 1.2.
- אין רשימות, השוואה או מכסה. Stories אחרים ישתמשו ב-`Subject`.
- אין סוד אמיתי בריפו. ערך ה-dev מותר רק ב-`ENV` מסוג dev או test.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| רישום ראשון | `POST /v1/devices` `{"install_id": "<uuid>"}` | 201. `{"device_id", "device_token", "expires_at"}`. נוצרת שורה ב-`devices` עם hash של המזהה | — |
| רישום חוזר | אותו `install_id` שוב | 200, אותו `device_id`, ו-token חדש. `last_seen_at` מתעדכן. אין שורה כפולה | — |
| install_id לא תקין | חסר, ריק, או לא באורך 16–128 תווים | 422, `validation_error` | AD-13 |
| בקשה עם token תקין | `GET /v1/me` עם `Authorization: Bearer <device_token>` | 200, `{"kind":"device","id":"<device_id>"}` | — |
| בלי token | `GET /v1/me` בלי כותרת | 401, `auth_required` | AD-13 |
| token פג או מזויף | חתימה שגויה, `exp` שעבר, `typ` אחר, או מכשיר שלא קיים | 401, `invalid_token` | ה-token לא מופיע בלוג |
| prod בלי סוד | `ENV=prod`, ו-`DEVICE_TOKEN_SECRET` חסר או שווה לערך ה-dev | `Settings` נכשל בעלייה | — |
| אפליקציה: הפעלה ראשונה | אין token ב-secure-store | נוצר install_id (UUID), נשלחת קריאה ל-`/v1/devices`, וה-token נשמר | — |
| אפליקציה: token קרוב לפקיעה | נשארו פחות מ-3 ימים, או שהתקבל 401 | רישום מחדש עם אותו install_id | — |
| אפליקציה: אין רשת | הקריאה נכשלת | הממשק ממשיך לעבוד. ניסיון נוסף בהפעלה הבאה, או בבקשה הבאה | נרשם warn ב-dev בלבד |

</intent-contract>

## Code Map

- `backend/app/core/auth.py` -- stub. `Subject(kind, id)`, `ANONYMOUS` ו-`get_subject()`. מחליפים אותו במימוש אמיתי, ומשאירים את הממשק.
- `backend/app/core/config.py` -- `Settings` עם `ENV: Literal["dev","test","prod"]`, ו-validator קיים שחוסם את ה-URL של dev ב-prod. מוסיפים `DEVICE_TOKEN_SECRET` ו-`DEVICE_TOKEN_TTL_DAYS` באותו סגנון.
- `backend/app/core/errors.py` -- `AppError(code, message_he, status, details)` לפורמט AD-13.
- `backend/app/core/ids.py` -- `new_id()` מסוג UUIDv7. `backend/app/core/db.py` -- `Base`, `get_session`.
- `backend/app/modules/identity/{models,schemas,repository,service,routes}.py` -- כרגע ריקים. כאן נבנים הטבלה, הסכמות והלוגיקה. `routes.py` מגדיר `APIRouter(prefix="/identity")`.
- `backend/app/modules/registry.py`, `backend/app/main.py` -- הרישום תחת `/v1`. `/v1/devices` ו-`/v1/me` הם routers של identity בלי prefix, או router נוסף ב-registry.
- `backend/migrations/versions/0001_extensions.py` -- המיגרציה הקודמת. החדשה היא `0002_devices`. `env.py` כבר מייבא את ה-models של כל המודולים.
- `backend/tests/integration/test_db.py` -- דפוס ה-fixture של testcontainers ו-`CARTWISE_REQUIRE_DOCKER`.
- `mobile/src/api/client.ts` -- `openapi-fetch`, ו-`API_URL` מ-`EXPO_PUBLIC_API_URL`. מוסיפים middleware של Authorization.
- `mobile/app/_layout.tsx` -- root, עם splash ו-`ensureRTL`. כאן מפעילים את ה-bootstrap של הזהות ברקע.
- `mobile/scripts/gen-api.mjs` -- מייצר מחדש את `schema.ts` אחרי שמוסיפים endpoints. ב-CI יש בדיקה שהוא מעודכן (`api-schema`).
- `.env.example` -- מוסיפים את `DEVICE_TOKEN_SECRET` (placeholder) ואת `DEVICE_TOKEN_TTL_DAYS`, במקטע backend.

## Tasks & Acceptance

**Execution:**
- `backend/pyproject.toml` -- להוסיף `pyjwt>=2.8`, ולעדכן את `uv.lock`.
- `backend/app/core/config.py` -- `DEVICE_TOKEN_SECRET: str` (ערך dev מוגדר כקבוע `DEV_DEVICE_TOKEN_SECRET`), ו-`DEVICE_TOKEN_TTL_DAYS: int = 30`. ה-validator דוחה את הקבוע, או ערך ריק, כש-`ENV=prod`.
- `backend/app/core/tokens.py` -- `issue_device_token(device_id) -> (token, expires_at)`, ו-`decode_device_token(token) -> device_id`, שמעלה `AppError(401, "invalid_token")`. חתימה ובדיקה דרך pyjwt, עם `algorithms=["HS256"]` ודרישת `typ=device`.
- `backend/app/core/auth.py` -- `get_subject(request, session)`: בלי כותרת מחזיר `ANONYMOUS`. עם `Bearer` מפענח את ה-token, ומוודא דרך `identity.service` שהמכשיר קיים. אם הכול תקין, מחזיר `Subject("device", id)`. אחרת זורק 401 `invalid_token`. בנוסף, `require_subject` דוחה anonymous עם 401 `auth_required`.
- `backend/app/modules/identity/models.py` -- `Device`: `id` (uuid, PK, `new_id`), `install_id_hash` (char(64), unique), `user_id` (uuid, nullable, בלי FK. ה-FK יתווסף ב-1.2), `created_at`, `last_seen_at`, `attestation_ok_at` (nullable), כולם `timestamptz` ב-UTC.
- `backend/migrations/versions/0002_devices.py` -- יצירת הטבלה, ו-downgrade שמוחק אותה.
- `backend/app/modules/identity/{schemas,repository,service}.py` -- `DeviceRegisterIn(install_id: str, 16..128)`, `DeviceRegisterOut`, `MeOut`. `register_device(install_id)`: upsert לפי hash, ועדכון `last_seen_at`. `device_exists(device_id)`.
- `backend/app/modules/identity/routes.py` -- `POST /v1/devices` מחזיר 201 בפעם הראשונה, ו-200 בפעם החוזרת. `GET /v1/me` דורש `require_subject`.
- `backend/tests/unit/test_tokens.py`, `backend/tests/integration/test_identity.py` -- כל שורות המטריצה בצד השרת, כולל prod בלי סוד. ה-integration רץ מול testcontainers.
- `mobile/package.json` -- להוסיף `expo-secure-store` ו-`expo-crypto` דרך `npx expo install`.
- `mobile/src/identity/device.ts` -- `ensureDeviceToken()`: קורא מ-secure-store, ואם צריך יוצר install_id עם `Crypto.randomUUID()`. קורא ל-`/v1/devices`, שומר את ה-token ואת `expires_at`, ומרענן כשנשארו פחות מ-3 ימים. `getDeviceToken()` ו-`clearDeviceToken()`.
- `mobile/src/api/client.ts` -- middleware שמוסיף `Authorization`. ב-401 של `invalid_token`, הוא מנקה את ה-token, רושם מחדש פעם אחת ומנסה שוב.
- `mobile/app/_layout.tsx` -- `ensureDeviceToken()` רץ ב-`useEffect` ברקע, בלי לחכות לו, ושגיאות נבלעות.
- `mobile/__tests__/device.test.ts`, ותוספת ל-`client.test.ts` -- שורות המטריצה בצד האפליקציה, עם mock ל-secure-store, ל-crypto ול-fetch.
- `mobile/openapi.json`, `mobile/src/api/schema.ts` -- נוצרים מחדש עם `npm run gen:api`.
- `.env.example` -- הוספה במקטע backend.

**Acceptance Criteria:**
- Given התקנה חדשה, when האפליקציה עולה, then המכשיר נרשם ברקע ומקבל device token, ואף מסך הרשמה לא מוצג.
- Given אורח עם token, when הוא שולח בקשה, then השרת מזהה `Subject(kind="device", id=<device_id>)`. זה ה-subject שהמכסה והרשימות יקשרו אליו (AD-11).
- Given הפקודות ב-Verification, then כולן עוברות, וה-schema מעודכן.

## Spec Change Log

## Review Triage Log

## Design Notes

- **היקף:** ה-AC של ה-Epic מדבר על "ליצור רשימה ולהשוות", אבל הרשימות וההשוואה נבנות ב-Epics 2 ו-5. ה-Story הזה מספק את השכבה שהן נשענות עליה: אורח מזוהה בלי הרשמה. החלק של "בלי מסך הרשמה" ייבדק שוב ב-E2E של Flow 6.
- **רישום חוזר:** אותו install_id מקבל token חדש. זה מאפשר רענון בלי refresh token. App Check (Story 1.2) יקשה על התחזות אם install_id ידלוף.

## Verification

**Commands:**
- `cd backend && uv sync && uv run ruff check . && uv run ruff format --check . && uv run mypy app` -- expected: נקי
- `cd backend && CARTWISE_REQUIRE_DOCKER=1 uv run pytest -q` -- expected: כל הבדיקות עוברות, ואף בדיקה לא דולגה
- `cd mobile && npm run gen:api && cd .. && test -z "$(git status --porcelain -- mobile/openapi.json mobile/src/api/schema.ts)" || echo "schema changed — commit it"` -- expected: ה-schema החדש נוצר, ונכנס ל-commit
- `cd mobile && npm run lint && npm run typecheck && npm test -- --ci` -- expected: עוברים

### 2026-10-28 — Review pass
- verdicts: 39 findings — high 0, medium 12, low 17, false 5, maybe-false 5
- findings:
  - Intent Alignment:
    - `maybe-false` `defer` לפי הקריאה המילולית, AC1 ו-AC2 (רשימה, השוואה ומכסה לפי מכשיר) לא מתממשים — הרשימות, ההשוואה והמכסה נבנות ב-Epics 2, 5 ו-8, לפי סדר הבנייה שנקבע. ה-Story מספק את השכבה הנדרשת (Subject מסוג device). ה-AC ייבדקו מקצה לקצה ב-Stories 2.1, 5.x ו-8.1, וב-E2E של Flow 6.
    - `false` `reject` ה-UI של Onboarding ורשימות לא נגעו — מחוץ להיקף, לפי ה-spec.
    - `false` `reject` אין בדיקה שלא מוצג מסך הרשמה — אין שום קוד שמציג הרשמה. זה ייבדק ב-E2E.
    - `false` `reject` תוספות שלא התבקשו (TTL, retry, /me) — כולן כתובות במפורש ב-spec ובמטריצה.
  - Blind Hunter:
    - `false` `reject` קבצים שנוצרו אוטומטית ו-lock לא ב-diff — במכוון. האימות כלל gen:api ו-lint, ו-api-schema יבדוק ב-CI.
    - `maybe-false` `defer` install_id הוא סיסמה קבועה בלי rate limit — הגבלת קצב לפי NFR-10 (Story 10.3). App Check ב-Story 1.2. ה-matrix מגדיר 16 עד 128 תווים.
    - `medium` `patch` הסוד ב-prod יכול להיות חלש — מינימום 32 תווים.
    - `maybe-false` `defer` אין revocation או רוטציה של tokens — בחירת design (Design Notes). ייבחן ב-Story 1.2, עם App Check ו-users.
    - `low` `patch` session ל-DB גם לבקשה אנונימית — הכותרת נבדקת קודם.
    - `low` `patch` `last_seen_at` מתעדכן רק ברישום — תועד ב-docstring.
    - `medium` `patch` race של clear ב-401 מקבילים — clear מותנה, ו-generation.
    - `medium` `patch` אין timeout או backoff לרישום, וכל בקשה ממתינה — AbortController, backoff ודילוג על health ו-devices.
    - `medium` `patch` תלות בשעון של המכשיר — lifetime מתוך ה-JWT.
    - `low` `patch` `xmax = 0` לא מתועד — נוספה הערה.
    - `false` `reject` iOS Keychain שורד הסרה — ה-MVP הוא Android בלבד. ייבחן עם iOS בגרסה 1.1.
    - `low` `patch` MeOut.id str ו-assert — UUID, ובדיקה מפורשת במקום assert. אינדקס על user_id: ב-1.2.
  - Verification Gap:
    - `medium` `patch` בדיקת ה-catch ב-root-layout לא מזהה שה-catch חסר — catch spy.
    - `medium` `patch` (other) 401 מקבילים לא נבדקים — קבוצת ה-race.
  - Edge Case Hunter:
    - `low` `patch` lone surrogate מחזיר 500 — validator שמחזיר 422.
    - `low` `patch` TTL ענק גורם ל-OverflowError — `le=365`.
    - `medium` `patch` TTL של 3 ימים או פחות מרענן תמיד — קבוצת ה-lifetime.
    - `medium` `patch` שעון מקדים — קבוצת ה-lifetime.
    - `medium` `patch` סוד חלש ב-prod — קבוצת המינימום של 32.
    - `medium` `patch` clear מוחק token של בקשה מקבילה — קבוצת ה-race.
    - `medium` `patch` clear בזמן run שכבר בתהליך — קבוצת ה-race.
    - `low` `patch` setItemAsync נכשל, והמכשיר לא נרשם לעולם — catch, ושימוש ב-id גם בלי לשמור אותו.
    - `low` `patch` DB לא זמין בבדיקת device_exists — 503 `db_unavailable`.
    - `maybe-false` `reject` endpoint ציבורי עם token פג מחזיר 401 — תואם למטריצה (`invalid_token`), והלקוח נרשם מחדש. אין עדיין endpoints ציבוריים עם subject.
    - `low` `patch` הבדיקה דולפת ל-env — `monkeypatch.delenv`.
    - `low` `reject` (claim) retry גם על `auth_required` — הרחבה סבירה: בלי token, נרשמים מחדש. בפועל זה לא מזיק.
    - `low` `patch` (Blind) pending map דולף ומשכפל body — ניקוי בכל נתיב.

## Auto Run Result

Status: done

**סיכום:** זהות אורח. ב-backend: טבלת `devices` (רק hash של מזהה ההתקנה), device token מסוג HS256 (סוד של 32 תווים לפחות ב-prod, TTL בין 1 ל-365 ימים), `core.auth.get_subject` ו-`require_subject` (ה-session נפתח רק כשיש token, ו-503 כש-DB לא זמין), `POST /v1/devices` (מחזיר 201 או 200), ו-`GET /v1/me`. באפליקציה: `ensureDeviceToken` עם secure-store, timeout, backoff, רענון לפי ה-lifetime של ה-JWT (עמיד לשעון לא מסונכרן), ו-clear מותנה. client middleware עם retry יחיד, ו-bootstrap ברקע ב-root layout.

**קבצים:**
- backend: `core/{config,tokens,auth,db}.py`, `modules/identity/*`, `migrations/versions/0002_devices.py`, הבדיקות (`tests/unit/test_tokens.py`, `tests/integration/{conftest,pg,test_identity}.py`), `pyproject.toml` ו-`uv.lock`.
- mobile: `src/identity/device.ts`, `src/api/{client,config}.ts`, `app/_layout.tsx`, `app.json` (plugin של secure-store), `package.json` ו-lock, `__tests__/*`, `openapi.json` ו-`schema.ts`.
- שורש: `.env.example`, `.gitleaks.toml`.

**ממצאי הסקירה:** 39 ממצאים. 12 קבוצות patch הוחלו, רובן medium. 3 פריטים נדחו ל-deferred: AC מקצה לקצה, rate limit ו-revocation. השאר נדחו או נמצאו false, והנימוק של כל אחד רשום ב-Review Triage Log. ממצא ה-lone surrogate לא היה בעיה בפועל, כי pydantic כבר דוחה אותו. נוספו בדיקות שמוכיחות זאת.

**המלצה לסקירת המשך:** `true`. היו כמה patches בדרגת medium בלוגיקה מקבילית באפליקציה: clear מותנה, generation, backoff ורענון לפי lifetime. הם נבדקו ביחידה, אבל לא עברו סקירה עצמאית נוספת.

**אימות:**
- backend: `uv sync --locked`, ruff, format ו-mypy עברו. `CARTWISE_REQUIRE_DOCKER=1 pytest`: 106 עברו.
- mobile: lint, typecheck ו-98 בדיקות עברו. `gen:api` עודכן.
- gitleaks על הקבצים שנכנסים ל-git: `no leaks found`.

**סיכונים שנשארו:**
- `xmax = 0` הוא פרט ספציפי ל-Postgres.
- ה-token הישן נשאר תקף עד שהוא פג.
- AC1 ו-AC2 מקצה לקצה ייבדקו ב-Epics הבאים.
