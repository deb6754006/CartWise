---
title: 'Story 1.3: הגדרת מועדונים'
type: 'feature'
created: '2026-11-02'
status: 'done'
baseline_revision: 'b387debb28f36ab10de2145649f4c84e6c7fe279'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/docs/implementation-artifacts/epic-1-context.md'
  - '{project-root}/docs/implementation-artifacts/spec-1-2-google-signin.md'
  - '{project-root}/docs/planning-artifacts/architecture/architecture-CartWise-2026-10-26/ARCHITECTURE-SPINE.md'
  - '{project-root}/CLAUDE.md'
warnings: ['oversized']
deferred:
  - summary: >-
      AC2 של ה-Story (מחירי מועדון נכנסים להשוואה רק עבור מועדון שסומן, ורק של אותה רשת) לא נבדק מקצה לקצה.
    evidence: |-
      ההשוואה נבנית ב-Epic 5. כאן נחשפת רק `identity.service.club_ids_for_subject`, ש-Epic 5 יקרא לה. כדי להכריע: בדיקת מחיר אפקטיבי עם מועדון מסומן ומועדון של רשת אחרת.
    severity: medium (unverified)
  - summary: >-
      אין עדיין רשתות ומועדונים אמיתיים ב-production. עד אז המסך מציג מצב ריק.
    evidence: |-
      הרשתות נבחרות ב-Story 3.1 ומחכות לאישור המשתמשת. כדי להכריע: למלא `chains` ו-`clubs` עבור הרשתות שאושרו, ב-Story 3.1 או 3.2.
    severity: medium (unverified)
  - summary: >-
      מחיקת חשבון צריכה למחוק גם את שורות `user_clubs` של המשתמש.
    evidence: |-
      ל-`subject_id` אין FK, כי הוא user או device. כדי להכריע: לטפל בזה ב-Story 1.7.
    severity: low (unverified)
  - summary: >-
      ב-Epics אין AC שמנסח במלואו את הדרישה של AC2 מ-Story 1.3.
    evidence: |-
      ב-Story 5.2 מופיע רק המקרה השלילי: מועדון שהמשתמש לא חבר בו לא נכנס (`epics.md:244`). המקרה החיובי קיים ב-FR-19, אבל לא כ-AC. כדי להכריע: לכלול ב-Story 5.2 גם מועדון מסומן שנכנס לחישוב, וגם מועדון של רשת אחרת שלא נכנס.
    location: >-
      docs/planning-artifacts/prds/prd-CartWise-2026-10-26/epics.md:244
    severity: medium (unverified)
  - summary: >-
      הניווט מהפרופיל למועדונים לא נבדק מול עץ הנתיבים האמיתי.
    evidence: |-
      `profile.test.tsx` מרכיב עץ שטוח ידני, ולכן שינוי שם של `app/clubs.tsx` לא יכשיל בדיקה. כדי להכריע: בדיקה עם `(tabs)/_layout` ו-`clubs`, כשמוסיפים את שאר שורות הפרופיל או את Onboarding (Story 1.6).
    location: >-
      mobile/__tests__/profile.test.tsx
    severity: low
  - summary: >-
      כשמשתמש מחובר לא מקבל ID token, הבקשות יוצאות עם device token, והסימונים נשמרים על המכשיר.
    evidence: |-
      התנהגות קיימת מ-Story 1.2: `authMiddleware` עובר ל-device כש-`getUserIdToken` מחזיר null. הסימונים עוברים לחשבון רק ב-link הבא. כדי להכריע: להחליט אם כתיבה של משתמש מחובר צריכה להיכשל במקום ליפול ל-device.
    location: >-
      mobile/src/api/client.ts
    severity: low
  - summary: >-
      הרשמה בלי device token, או ממכשיר של חשבון אחר, מסתיימת בלי העברת סימוני האורח ובלי הודעה.
    evidence: |-
      התנהגות קיימת מ-Story 1.2 ב-`session.ts`: `link` ממשיך בלי device_token כש-`ensureDeviceToken` נכשל או אחרי 409. הסימונים לא נמחקים, והם נשארים על המכשיר. כדי להכריע: לנסות שוב לקשר את המכשיר כשהרישום שלו מצליח בהמשך.
    location: >-
      mobile/src/identity/session.ts
    severity: low
---

<intent-contract>

## Intent

**Problem:** המשתמש לא יכול לסמן באילו מועדונים הוא חבר (FR-3), ולכן בהמשך ההשוואה לא תדע אילו מחירי מועדון זמינים לו. בנוסף, עדיין אין בשרת טבלאות של רשתות ומועדונים.

**Approach:** מוסיפים `chains` ו-`clubs` למודול catalog, ו-`user_clubs` למודול identity, עם ה-endpoints `GET /v1/chains`, `GET /v1/clubs` ו-`GET/PUT /v1/me/clubs`. באפליקציה נבנה מסך "המועדונים שלי" (SCR-CLUBS), שנפתח מהפרופיל, עם מתג לכל מועדון. הרכיב משותף, כדי ש-Onboarding (Story 1.6) ישתמש בו.

## Boundaries & Constraints

**Always:**
- הסימונים שייכים ל-subject: device לאורח, ו-user למשתמש רשום. המסך זמין גם לאורח, ולא מציג הרשמה.
- בהרשמה הסימונים של המכשיר עוברים למשתמש, באותה טרנזקציה של ה-link, כאיחוד (union) בלי כפילויות, ואז נמחקים מהמכשיר. `user_clubs` שייכת ל-identity, ולכן ההעברה היא קריאה ישירה ב-`service.link`, ולא transfer hook. היא רצה בכל link שבו המכשיר מקושר לאותו משתמש, כולל link חוזר אחרי התנתקות. על כן היא חייבת להיות idempotent.
- `PUT /v1/me/clubs` מחליף את כל הקבוצה. מזהה לא מוכר דוחה את כל הבקשה, בלי שינוי.
- AD-2: identity בודק מזהי מועדונים רק דרך `catalog.service`, ומשתמש בנתוני catalog רק דרכו.
- AD-13 בכל התגובות והשגיאות. כל ה-endpoints דורשים `require_subject` (AD-12). הלקוח TypeScript מיוצר מה-OpenAPI.
- מחרוזות ב-`he.json`, וטוקנים מ-`tokens.ts`. המסך נגיש: כל מתג מקבל שם ומצב.
- נתוני פיתוח מכילים רק רשתות בדויות, לפי הלשון של ה-AC וה-mockup ("רשת א׳", "רשת ב׳", "רשת ג׳").

**Never:**
- לא מבקשים, לא שומרים ולא מקבלים מספר מועדון או פרט מזהה אחר. אין עמודה כזו.
- לא מכניסים שמות של רשתות אמיתיות לקוד, למיגרציות או ל-seed: הבחירה בהן שייכת ל-Story 3.1, באישור המשתמשת. המיגרציה לא מכניסה נתונים בכלל.
- לא בונים השוואה או חישוב מחיר (Epic 5), Onboarding (Story 1.6), ושאר שורות הפרופיל (מותגים, טווח, כיסוי, פרטיות, התנתקות, מחיקה).
- אין הגבלת קצב ו-App Check (Story 10.3).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| רשימת רשתות | `GET /v1/chains` | 200, רשימה ממוינת לפי שם: `id`, `name` | — |
| רשימת מועדונים | `GET /v1/clubs` | 200, רשימה ממוינת לפי שם הרשת ואז שם המועדון: `id`, `name`, `chain_id`, `chain_name` | — |
| בלי token | כל אחד מה-endpoints החדשים | 401 `auth_required` | AD-13 |
| קריאת סימונים | `GET /v1/me/clubs`, אין סימונים | 200 `{"club_ids": []}` | — |
| שמירה | `PUT /v1/me/clubs` `{"club_ids": [a, b]}` | 200 `{"club_ids": [a, b]}`. `GET` מחזיר אותה קבוצה | — |
| כפילות במזהים | `{"club_ids": [a, a]}` | 200, נשמר פעם אחת | — |
| ניקוי | `{"club_ids": []}` | 200, כל הסימונים נמחקים | — |
| מזהה לא מוכר | `{"club_ids": [a, zzz]}`, כש-`zzz` לא קיים | 422 `unknown_club`, והסימונים הקודמים נשארים | AD-13, הודעה בעברית |
| גוף לא תקין | שדה נוסף כמו `member_number`, מזהה שאינו UUID, או יותר מ-200 מזהים | 422 בפורמט AD-13, בלי שמירה | AD-13 |
| בידוד | שני subjects שונים | כל אחד רואה ומשנה רק את שלו | — |
| link ראשון | למכשיר `a`, למשתמש החדש כלום | למשתמש `a`, למכשיר כלום | שגיאה ב-link: rollback מלא |
| link למשתמש קיים | למכשיר `a, b`, למשתמש `b, c` | למשתמש `a, b, c`, למכשיר כלום | — |
| link חוזר אחרי התנתקות | מכשיר שמקושר לאותו משתמש, עם סימונים חדשים כאורח | הסימונים עוברים למשתמש | — |
| מכשיר של משתמש אחר | link מחזיר 409 | אין העברה | rollback |
| אפליקציה: טעינה | פתיחת המסך | Skeleton של כרטיסים | — |
| אפליקציה: אין מועדונים | `GET /v1/clubs` מחזיר רשימה ריקה | הודעה: "עוד אין מועדונים זמינים. הם יופיעו כאן כשנוסיף רשתות" | — |
| אפליקציה: טעינה נכשלה | שגיאת רשת או שרת | הודעה בעברית וכפתור "נסו שוב", ואין מתגים | — |
| אפליקציה: שינוי מתג | לחיצה | המתג משתנה מיד, ו-`PUT` נשלח עם הקבוצה המלאה | — |
| אפליקציה: שינויים מהירים | כמה לחיצות בזמן שבקשה רצה | לכל היותר בקשה אחת רצה. בסופה נשלח המצב האחרון | — |
| אפליקציה: שמירה נכשלה | `PUT` נכשל | המתגים חוזרים למצב האחרון שנשמר, ומוצגת הודעה: "לא הצלחנו לשמור. נסו שוב" | — |
| אפליקציה: מזהה ישן | סימון שמור למועדון שכבר לא מוחזר מ-`GET /v1/clubs` | לא מוצג, ולא נשלח ב-`PUT` הבא | — |

</intent-contract>

## Code Map

- `backend/app/modules/catalog/{models,repository,service,routes,schemas}.py` -- כרגע ריקים, ול-router יש `prefix="/catalog"`. מסירים את ה-prefix: לפי architecture.md §API הנתיבים הם `/chains` ו-`/clubs`, כמו identity (`identity/routes.py:20`). אם בדיקה קיימת מסתמכת על ה-prefix, מעדכנים אותה.
- `backend/app/modules/identity/service.py:76` -- `link()`. נקודת ההעברה: שני הענפים שבהם המכשיר שייך ל-`user.id`. הענף של 409 נשאר ללא העברה.
- `backend/app/modules/identity/repository.py` -- `lock_device` ו-`set_device_user`. ההעברה מתווספת כאן, עם `insert ... on_conflict_do_nothing`.
- `backend/app/modules/identity/routes.py:66` -- `/me` מראה את הטיפול ב-`subject.id` ובאנונימי. `subject.id` הוא str.
- `backend/migrations/versions/0003_users.py` -- תבנית למיגרציה, כולל `op.f` לשמות אילוצים.
- `backend/migrations/env.py` -- לוודא שמודלי catalog נטענים (autogenerate, ו-FK בין מודולים).
- `backend/tests/integration/test_link.py`, `conftest.py`, `pg.py` -- `FakeVerifier`, `_id_token` ו-fixtures. לשימוש חוזר.
- `mobile/app/_layout.tsx` -- Root `Stack` בלי headers. מסך ב-`mobile/app/clubs.tsx` נפתח מעל הטאבים, ועליו להציג חזרה משלו.
- `mobile/app/(tabs)/profile.tsx` -- כרגע `Placeholder`.
- `mobile/src/api/client.ts` -- `authMiddleware` מוסיף token. קוראים דרך ה-client המיוצר.
- `mobile/src/components/SignInSheet.tsx`, `mobile/__tests__/signin-sheet.test.tsx` -- דוגמה לסגנון של רכיב ובדיקה.
- `docs/planning-artifacts/ux-designs/ux-CartWise-2026-10-26/mockups/screens-1-onboarding-home.html:62` -- SCR-ONB-4 (SCR-CLUBS זהה לו). `mockups/screens-5-spend-profile.html:55` -- SCR-PROFILE. `EXPERIENCE.md:140-150` -- מצבי טעינה ושגיאה כלליים.

## Tasks & Acceptance

**Execution:**
- `backend/app/modules/catalog/models.py` -- `Chain` (`id`, `name`, `gov_chain_code` nullable + unique, `publishes_files` ברירת מחדל true) ו-`Club` (`id`, `chain_id` FK, `name`, unique על `chain_id` + `name`) -- לפי architecture.md §נתונים.
- `backend/app/modules/catalog/{repository,service,schemas,routes}.py` -- `list_chains`, `list_clubs`, `existing_club_ids(session, ids) -> set[UUID]` ו-`ensure_chain_with_club(session, chain_name, club_name)` (idempotent). `GET /chains` ו-`GET /clubs` עם `require_subject`, והסרת ה-prefix.
- `backend/app/modules/identity/models.py` -- `UserClub`: `subject_id` (Uuid, בלי FK), `club_id` (FK ל-`clubs.id`, `ondelete=CASCADE`, עם אינדקס), ו-PK מורכב.
- `backend/migrations/versions/0004_chains_clubs.py` -- שלוש הטבלאות ו-downgrade. בלי נתונים.
- `backend/app/modules/identity/{repository,service,schemas,routes}.py` -- `club_ids_for_subject` (זו גם הנקודה ש-Epic 5 יקרא לה), `set_clubs` עם `unknown_club` ו-dedupe בטרנזקציה אחת, והעברה ב-`link`. `GET/PUT /me/clubs`. סכימת הקלט דוחה שדות נוספים (`extra="forbid"`), ומגבילה ל-200 מזהים.
- `backend/scripts/seed_dev_catalog.py` -- רשתות בדויות "רשת א׳", "רשת ב׳" ו-"רשת ג׳", לכל אחת "מועדון רשת X", דרך `catalog.service`. idempotent. מסרב לרוץ כשהסביבה היא prod -- כדי שאפשר יהיה לראות את המסך מקומית.
- `backend/README.md` -- איך מריצים את ה-seed, ושב-production הרשתות יתווספו אחרי Story 3.1.
- `backend/tests/integration/test_clubs.py` -- כל שורות המטריצה בצד השרת, כולל rollback ב-link, סכימת `user_clubs` בלי עמודת מספר מועדון, ו-seed idempotent ומסרב ב-prod.
- `mobile/openapi.json`, `mobile/src/api/schema.ts` -- `npm run gen:api`.
- `mobile/src/profile/useClubs.ts` -- טעינה משותפת של `/v1/clubs` ו-`/v1/me/clubs`, `toggle`, שמירה סדרתית עם המצב האחרון, וחזרה למצב שנשמר בכשל.
- `mobile/src/components/ClubsList.tsx` -- המתגים, הודעת ה-🔒, Skeleton, מצב ריק, ושגיאות -- רכיב בלי ניווט, כדי ש-Story 1.6 ישתמש בו.
- `mobile/app/clubs.tsx` -- SCR-CLUBS: כותרת "המועדונים שלי", כפתור חזרה, ותת-כותרת "כך נראה לכם את המחיר שתשלמו באמת".
- `mobile/app/(tabs)/profile.tsx` -- כותרת "פרופיל", קטע "ההשוואה שלי" ושורה "המועדונים שלי" עם מספר הסימונים, שמתעדכן בכל חזרה למסך (`useFocusEffect`). אם הטעינה נכשלה, השורה מוצגת בלי מספר.
- `mobile/src/i18n/he.json` -- כל המחרוזות החדשות.
- `mobile/__tests__/{use-clubs,clubs-list,clubs-screen,profile}.test.tsx` -- שורות המטריצה בצד האפליקציה, כולל שמירה סדרתית וחזרה בכשל.

**Acceptance Criteria:**
- Given אורח בפרופיל, when הוא לוחץ על "המועדונים שלי", then נפתח SCR-CLUBS עם מתג לכל מועדון, ובלי מסך הרשמה.
- Given שסימנתי מועדון, when אני יוצא וחוזר, then הסימון נשמר, והפרופיל מציג את המספר הנכון.
- Given כל הזרימה (מסך, API, DB), then אין שדה, בקשה או עמודה של מספר מועדון.
- Given אורח שסימן מועדונים, when הוא נרשם, then הסימונים מופיעים בחשבון שלו.
- Given שני מועדונים של רשתות שונות, when מסומן רק אחד, then `club_ids_for_subject` מחזירה רק אותו. זה מה ש-Epic 5 ישתמש בו.

## Spec Change Log

## Review Triage Log

### 2026-11-02 — Review pass
- verdicts: 34 findings — high 0, medium 4, low 26, false 1, maybe-false 3
- findings:
  - Intent Alignment:
    - `maybe-false` `defer` AC2 מוחלף בבדיקה של `club_ids_for_subject`, במקום בבדיקה של השוואה אמיתית — ההשוואה נבנית ב-Epic 5. כדי להכריע: בדיקת מחיר אפקטיבי. רשום ב-deferred.
    - `maybe-false` `defer` ב-Epics אין AC שמנסח את AC2 במלואו — ב-Story 5.2 מופיע רק המקרה השלילי. כדי להכריע: AC מלא ב-Story 5.2. רשום ב-deferred.
    - `maybe-false` `defer` AC1 מתקיים כמנגנון, וב-production המסך ריק — הרשתות נבחרות ב-Story 3.1. כדי להכריע: מילוי הנתונים אחרי האישור. רשום ב-deferred.
    - `low` `reject` אין בדיקה שחוצה את הגבול בין האפליקציה לשרת — הלקוח מיוצר מה-OpenAPI, ו-CI בודק את זה (`api-schema`). בדיקת e2e היא יותר מתיקון ישיר.
  - Blind Hunter:
    - `low` `reject` ה-seed מוגן רק לפי `ENV` — נדרשת הרצה ידנית עם `DATABASE_URL` של production בלי `ENV`. זה לא סביר, והתיקון מוסיף guard.
    - `low` `reject` אין התאוששות מ-`unknown_club` — קורה רק כשמועדון נמחק בזמן שהמסך פתוח. כניסה מחדש פותרת את זה.
    - `medium` `patch` `PUT` תקוע חוסם את כל הטעינות — אומת: אין timeout. נוסף `withTimeout` עם 15 שניות.
    - `low` `reject` כשל שמירה אחרי יציאה מהמסך לא מציג הודעה — הפרופיל מציג את המספר הנכון מהשרת. משוב גלובלי דורש תשתית toast שעדיין אין.
    - `low` `reject` הודעת הכשל עלולה להיות מחוץ למסך — ב-MVP יש 2–3 רשתות, ולכן הרשימה קצרה. הניסוח נקבע במטריצה.
    - `low` `reject` מועדונים עם שם זהה לא ניתנים להבחנה — הנתונים בשליטת המפעיל. לתת שמות מבחינים כשייכנסו רשתות ב-Story 3.1.
    - `low` `reject` המצב לא קשור לזהות המחוברת — הפרופיל טוען מחדש בפוקוס. כתיבה חוזרת עם device token מתאחדת לחשבון ב-link הבא. שמירה שמגיעה אחרי link דורשת הרשמה תוך פחות מזמן השמירה.
    - `low` `reject` `set_clubs` בודק לפני הנעילה, ו-FK נותן 500 — נדרש מחיקת מועדון במילישניות שבין הבדיקה להכנסה. האפליקציה מציגה אותה הודעה בשני המקרים.
    - `low` `patch` בבדיקות המקביליות אין בדיקת `is_alive` — נוספה בדיקה, וה-threads הם daemon.
    - `low` `patch` `test_exactly_200_ids_are_accepted` שולח מזהה אחד — עכשיו 200 מועדונים שונים, עם בדיקת הקבוצה.
    - `low` `reject` אין ניקוי של סימוני אורחים — בקוד אין עדיין מחיקת מכשירים, ולכן אין שורות יתומות. מחיקת משתמש רשומה ב-deferred.
    - `false` `reject` `openapi.json` ו-`schema.ts` לא ב-patch — במכוון. CI בודק שהם תואמים ל-`gen:api`, ו-`gen:api` רץ באימות.
  - Edge Case Hunter:
    - `low` `reject` FK נותן 500 במקום 422 — אותו ממצא כמו ב-Blind Hunter, ואותו נימוק.
    - `medium` `patch` `PUT` תקוע חוסם את `loadClubs` — אותה קבוצה: `withTimeout`.
    - `medium` `patch` `GET` תקוע משאיר את המסך בטעינה — אותה קבוצה: `withTimeout`, ו-timeout מוביל ל-load-error.
    - `low` `reject` `unknown_club` כשהמסך פתוח — אותו ממצא כמו ב-Blind Hunter, ואותו נימוק.
    - `low` `reject` כשל אחרי unmount — אותו ממצא כמו ב-Blind Hunter, ואותו נימוק.
    - `low` `reject` `PUT` של קבוצה ישנה דורס שינוי ממכשיר אחר — נדרש מסך פתוח בזמן שינוי במכשיר שני. הקבוצה נטענת בכל כניסה, וגרסאות הן יותר מתיקון ישיר.
    - `low` `patch` לחיצה כפולה פותחת שני מסכים — `dangerouslySingular`, עם בדיקה.
    - `low` `defer` ID token חסר גורם לנפילה ל-device — אומת ב-`client.ts`. התנהגות קיימת מ-Story 1.2. רשום ב-deferred.
    - `low` `reject` `PUT` אחרי `not_linked` נשלח שוב עם device token — אומת ב-`client.ts`, אבל המשתמש הופך לאורח, והסימונים מתאחדים לחשבון ב-link הבא.
    - `low` `reject` `PUT` של אורח אחרי `move_user_clubs` — נדרשת הרשמה עם Google בזמן קצר משמירה אחת. הסימון לא נמחק.
    - `low` `reject` יותר מ-200 מועדונים נכשלים — ב-MVP יש 2–3 רשתות.
    - `low` `reject` seed בלי `ENV` — אותו ממצא כמו ב-Blind Hunter, ואותו נימוק.
    - `low` `patch` `join` בלי `is_alive` — אותו תיקון כמו ב-Blind Hunter.
    - `low` `defer` (claim) הרשמה בלי העברת סימונים ובלי הודעה — אומת ב-`session.ts`. התנהגות קיימת מ-Story 1.2, והסימונים לא נמחקים. רשום ב-deferred.
  - Verification Gap:
    - `medium` `patch` הנעילה ב-`move_user_clubs` לא נבדקת מול `PUT` מקביל — `test_concurrent_put_and_link_do_not_lose_marks`, עם השהיה לפני ה-`DELETE`. בדיקת מוטציה: הסרת שתי הנעילות מכשילה אותה.
    - `low` `patch` נרמול NFC לא נבדק — `test_ensure_chain_with_club_stores_nfc_and_dedupes`.
    - `low` `patch` ההגנה מתשובה ישנה בפרופיל לא נבדקת — 'a late answer from before leaving does not overwrite the count'.
    - `low` `defer` הניווט לא נבדק מול עץ הנתיבים האמיתי — הסיכון מתממש רק בשינוי מבנה הנתיבים. רשום ב-deferred, ל-Story 1.6.

## Design Notes

- **רשתות ב-production:** עד Story 3.1 הרשימה ריקה, והמסך מציג מצב ריק. אין עדיין משתמשים, ולכן זה לא פוגע באיש. זה גם לא מקדים החלטה שהמשתמשת אמורה לאשר, ולא ממציא נתוני שוק.
- **למה ההעברה לא hook:** ה-hooks קיימים כדי ש-identity לא יגע בטבלאות של מודולים אחרים (AD-2). `user_clubs` היא של identity. קריאה ישירה גם רצה ב-link חוזר, ש-hooks לא רצים בו.
- **`subject_id` בלי FK:** הוא מצביע על `users` או על `devices`. UUIDv7 ייחודי בין השתיים, כפי שנקבע במודל הנתונים.

## Verification

**Commands:**
- `cd backend && uv sync --locked && uv run ruff check . && uv run ruff format --check . && uv run mypy app && CARTWISE_REQUIRE_DOCKER=1 uv run pytest -q` -- expected: הכול עובר
- `cd mobile && npm run gen:api && npm run lint && npm run typecheck && npm test -- --ci` -- expected: עובר
- `cd mobile && npx expo export --platform android --output-dir <tmp>` -- expected: נבנה. אחר כך מוחקים את התיקייה.

## Auto Run Result

Status: done

**סיכום:** אפשר לסמן מועדונים במסך "המועדונים שלי", שנפתח מהפרופיל, גם כאורח. הסימונים נשמרים בשרת ועוברים לחשבון בהרשמה. לא מבקשים ולא שומרים מספר מועדון.

**קבצים:**
- `backend/app/modules/catalog/*` -- `Chain`, `Club`, `GET /v1/chains` ו-`GET /v1/clubs`.
- `backend/app/modules/identity/*` -- `UserClub`, `GET/PUT /v1/me/clubs`, העברה ב-`link`, ו-`club_ids_for_subject` בשביל Epic 5.
- `backend/migrations/versions/0004_chains_clubs.py` -- שלוש טבלאות, בלי נתונים.
- `backend/scripts/seed_dev_catalog.py`, `backend/README.md` -- נתוני פיתוח בדויים בלבד.
- `backend/tests/integration/test_clubs.py` -- המטריצה בצד השרת, מקביליות, סכימה ו-seed.
- `mobile/src/profile/useClubs.ts` -- טעינה, שמירה סדרתית, חזרה למצב השמור ו-timeout.
- `mobile/src/components/ClubsList.tsx` -- המתגים והמצבים. Story 1.6 ישתמש בו.
- `mobile/app/clubs.tsx`, `mobile/app/(tabs)/profile.tsx` -- SCR-CLUBS והפרופיל.
- `mobile/src/i18n/he.json`, `mobile/openapi.json`, `mobile/src/api/schema.ts` -- מחרוזות ולקוח מיוצר.
- `mobile/__tests__/{use-clubs,clubs-list,clubs-screen,profile}.test.tsx` -- המטריצה בצד האפליקציה.

**ממצאי הסקירה:** 34 ממצאים. התיקונים כיסו 10 שורות: 4 medium ו-6 low. ה-medium מתחלקים לשתי קבוצות: timeout (3 שורות) ומקביליות (שורה אחת). 6 שורות נדחו ל-deferred. 18 נדחו, והנימוק של כל אחת רשום ב-Review Triage Log.

**בנוסף לממצאים:** הוחלף `Result.tuples()` ב-`catalog/repository.py`, שמסומן deprecated ב-SQLAlchemy 2.1.

**המלצה לסקירת המשך:** `true`. תוקנו שתי קבוצות medium: timeout בבקשות המסך, ובדיקת המקביליות של `PUT` מול link. הסיכון שלא אומת: התנהגות ה-timeout על מכשיר אמיתי, ובמיוחד `PUT` שפג לו הזמן אבל מגיע לשרת.

**אימות:**
- backend: ruff, format ו-mypy עברו. `CARTWISE_REQUIRE_DOCKER=1 pytest`: 200 עברו.
- mobile: `gen:api`, lint ו-typecheck עברו, ו-191 בדיקות עברו.
- `expo export` ל-Android: עבר.
- gitleaks על הקבצים שהשתנו: `no leaks found`.
- בדיקות מוטציה של המימוש: הסרת הנעילות, ה-NFC, `dangerouslySingular` וה-guard של `current` מכשילה בדיקה.

**סיכונים שנשארו:**
- המסך לא נבדק במכשיר או באמולטור, רק בבדיקות אוטומטיות.
- `PUT` שפג לו ה-timeout יכול עדיין להישמר בשרת. האפליקציה תציג כשל ומצב ישן, עד הטעינה הבאה.
- ה-timeout לא חל על השגת ה-token ב-`authMiddleware`, ו-`getUserIdToken` לא נבדק מהבחינה הזו.
- `_lock_subject_clubs(session, to_subject)` לא נבדקה לבדה.
- כשל שמירה אחרי יציאה מהמסך לא מציג הודעה.
