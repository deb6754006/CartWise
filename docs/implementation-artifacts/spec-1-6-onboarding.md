---
title: 'Story 1.6: Onboarding'
type: 'feature'
created: '2026-11-02'
status: 'done'
baseline_revision: 'edd8dc8769d076b8480be181cf385d71203a3589'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/docs/implementation-artifacts/epic-1-context.md'
  - '{project-root}/docs/implementation-artifacts/spec-1-5-default-range.md'
  - '{project-root}/docs/planning-artifacts/architecture/architecture-CartWise-2026-10-26/ARCHITECTURE-SPINE.md'
  - '{project-root}/CLAUDE.md'
warnings: ['oversized']
deferred:
  - summary: >-
      בחירת נקודה על מפה (FR-7, EC-14) לא נבנתה. כרגע החלופה להרשאת מיקום היא הזנת כתובת בלבד.
    evidence: |-
      `react-native-maps` ב-Android דורש מפתח Google Maps, וספריית המפה עדיין מסומנת "לאמת" בארכיטקטורה (Q8). ה-mockup של SCR-ONB-2 ו-EXPERIENCE מציגים רק כתובת. כדי להכריע: להוסיף בחירה על מפה כשספריית המפה נקבעת, ב-Epic 5.
    severity: medium (unverified)
  - summary: >-
      Nominatim לא נבדק מול השירות האמיתי: תנאי השימוש ואיכות התוצאות לכתובות בעברית לא אומתו.
    evidence: |-
      בבדיקות הוא מוחלף ב-fake, בלי רשת. כדי להכריע: לבדוק את תנאי השימוש (Q8) וכתובות אמיתיות בעברית לפני ההשקה. אם נדרש, להחליף ספק מאחורי ה-port, בלי שינוי באפליקציה.
    severity: medium (unverified)
  - summary: >-
      מסך הפרטיות הוא סיכום קצר בלבד. המדיניות המלאה, הבדיקה המשפטית, והקישור בהגדרות לא נבנו.
    evidence: |-
      הם שייכים ל-Story ב-`epics.md:442` ול-NFR-14, שדורש בדיקה משפטית. כדי להכריע: להשלים ב-Epic 10, ולהחליף את הטקסט אחרי הבדיקה.
    location: >-
      docs/planning-artifacts/prds/prd-CartWise-2026-10-26/epics.md:442
    severity: medium (unverified)
  - summary: >-
      נקודת המוצא נשמרת במכשיר, אבל אין עדיין מי שקורא אותה.
    evidence: |-
      ההשוואה נבנית ב-Epic 5. כאן נחשפת `getSavedOrigin`. כדי להכריע: SHEET-RANGE ישתמש בה כ"כתובת אחרת", ויקבע מה גובר כשיש גם כתובת שמורה וגם הרשאת מיקום.
    severity: low (unverified)
  - summary: >-
      `GET /v1/geo/geocode` פתוח לכל device token בלי הגבלה לכל subject, וכל הלקוחות חולקים תקציב של בקשה אחת בשנייה.
    evidence: |-
      אין עדיין הגבלת קצב באף endpoint (Story 10.3). לקוח אחד בלולאה יכול לגרום ל-503 לכולם, ולהשתמש בשרת כפרוקסי ל-Nominatim. כדי להכריע: לכלול את ה-endpoint הזה ב-Story 10.3.
    location: >-
      backend/app/modules/geo/routes.py
    severity: medium
  - summary: >-
      `countrycodes=il` עלול להחריג יישובים ביהודה ושומרון, ואז המשתמש יקבל "לא מצאנו".
    evidence: |-
      לא נבדק מול השירות. כדי להכריע: לבדוק כתובות מיישובים כאלה בבדיקה מול Nominatim האמיתי, לפני ההשקה.
    location: >-
      backend/app/modules/geo/service.py
    severity: medium (unverified)
  - summary: >-
      תוצאה שגויה של Nominatim נשמרת בלי שהמשתמש רואה מה נמצא.
    evidence: |-
      נשמר הטקסט שהמשתמש הקליד, ו-`display_name` לא מוצג. לא ברור כמה זה קורה בכתובות אמיתיות. כדי להכריע: לבדוק מול השירות האמיתי, ולהחליט אם צריך שלב אישור.
    location: >-
      mobile/src/components/OriginStep.tsx
    severity: medium (unverified)
  - summary: >-
      AD-1 מונה כשירותים חיצוניים רק את Firebase, openrouteservice ו-Sentry, ו-`architecture.md` מזכיר את Nominatim לסניפים בלבד.
    evidence: |-
      השימוש ב-Nominatim לכתובות משתמש הוא החלטת המשתמשת מ-2026-11-02. כדי להכריע: לעדכן את מסמכי הארכיטקטורה.
    location: >-
      docs/planning-artifacts/architecture/architecture-CartWise-2026-10-26/ARCHITECTURE-SPINE.md
    severity: low
---

<intent-contract>

## Intent

**Problem:** משתמש חדש נכנס ישר לאפליקציה בלי להבין מה היא עושה, בלי הרשאת מיקום, ובלי טווח או מועדונים (FR-7).

**Approach:** בפתיחה הראשונה מוצג מסך `/onboarding` עם ארבעה שלבים (SCR-ONB-1..4), ובכל אחד יש "דלג". בשלב המיקום אפשר לאשר הרשאה או להזין כתובת, והכתובת נשמרת במכשיר בלבד כנקודת מוצא. שלבי הטווח והמועדונים משתמשים ברכיבים הקיימים.

## Boundaries & Constraints

**Always:**
- ה-Onboarding מוצג רק כל עוד לא הסתיים. "סיום" או דילוג על השלב האחרון שומרים דגל במכשיר. סגירת האפליקציה באמצע מתחילה אותו מחדש.
- שגיאה בקריאת הדגל לא חוסמת: האפליקציה נפתחת רגיל. שגיאה בכתיבתו לא מונעת את המעבר לבית.
- "דלג" מעביר לשלב הבא בלי לשנות דבר, ובשלב האחרון מסיים. מי שדילג מקבל את ברירות המחדל הקיימות (רכב ו-15 דקות, ובלי מועדונים).
- מיקום מההרשאה לא נקרא ולא נשמר כאן. רק ההרשאה מתבקשת (NFR-12).
- התוצאה (הטקסט והקואורדינטות) נשמרת ב-SecureStore בלבד. איתור הכתובת עובר דרך `GET /v1/geo/geocode` בשרת שלנו, אל Nominatim, בלי מפתח ובלי חשבון (החלטת המשתמשת, 2026-11-02: חינמי). הוא לא דורש הרשאת מיקום.
- השרת לא שומר את הכתובת, לא שומר אותה במטמון, ולא מכניס אותה ללוג או להודעת שגיאה. הקריאה ל-Nominatim עוברת דרך port עם fake בבדיקות, וה-URL מגיע מקונפיגורציה. נשלח User-Agent מזהה, ולכל היותר בקשה אחת בשנייה מהתהליך.
- מסך הזנת הכתובת מציג "© OpenStreetMap contributors". סיכום הפרטיות אומר שהכתובת עוברת דרך השרת ל-OpenStreetMap ולא נשמרת.
- הטקסט בשלב המיקום הוא זה של EXPERIENCE §10.1, בלי המשפט "אנחנו לא שומרים אותו", כי AD-10 שומר geohash במטמון של זמני הנסיעה.
- מחרוזות ב-`he.json`, וטוקנים מ-`tokens.ts`. כל פעולה נגישה. הדמות היא SVG בגודל 120, בלי אנימציה.

**Never:**
- אין הרשמה ב-Onboarding (FR-1).
- אין מפה ואין מפתח API. אין `geocodeAsync` של `expo-location`, כי הוא דורש הרשאת מיקום ב-Android.
- אין טקסט שטוען שהמדיניות נבדקה משפטית.
- אין שינוי בשרת מלבד ה-endpoint של geocoding, ואין טבלה חדשה.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| פתיחה ראשונה | אין דגל | עוברים ל-`/onboarding`, שלב 1, בלי להציג קודם את הטאבים | — |
| פתיחה חוזרת | יש דגל | הטאבים, בלי Onboarding | — |
| קריאת דגל נכשלה | שגיאה ב-SecureStore | הטאבים | בלי הודעה |
| התקדמות | "מתחילים", "המשך" | השלב הבא | — |
| דילוג | "דלג" בכל שלב | השלב הבא, בלי PUT ובלי בקשת הרשאה. בשלב 4 מסיים | — |
| חזרה | כפתור חזרה של Android | שלב קודם. בשלב 1, התנהגות רגילה של המערכת | — |
| סיום | "סיום" | נשמר דגל, ומעבר לבית (`replace`). חזרה לא מחזירה ל-Onboarding | כתיבה נכשלה: בכל זאת עוברים לבית |
| הרשאה אושרה | "אישור מיקום", ואישור | השלב הבא, ולא נשמר מיקום | — |
| הרשאה סורבה | "אישור מיקום", וסירוב | הסבר, "לפתיחת ההגדרות" ואפשרות להזין כתובת | — |
| הרשאה נכשלה | שגיאה בבקשה | כמו סירוב | — |
| כתובת נמצאה | הזנה ו-"שמירה" | נשמרים הטקסט והקואורדינטות במכשיר, ומעבר לשלב הבא | — |
| כתובת ריקה | רווחים בלבד | הכפתור מושבת | — |
| כתובת לא נמצאה | תוצאה ריקה | "לא מצאנו את הכתובת. נסו לכתוב אותה אחרת", ואין שמירה | — |
| geocoding נכשל | שגיאה | "לא הצלחנו לבדוק את הכתובת. נסו שוב או דלגו", ואין שמירה | — |
| שמירה נכשלה | SecureStore נכשל | אותה הודעה, בלי מעבר | — |
| טווח | בחירה בשלב 3 | נשמר דרך `useRange`. טעינה נכשלה: הודעה ו-"נסו שוב", ואפשר לדלג | — |
| מועדונים | שלב 4 | `ClubsList`. מצב ריק או טעינה נכשלה לא חוסמים את "סיום" | — |
| שרת: כתובת נמצאה | `GET /v1/geo/geocode?q=...` | 200 `{"lat", "lng"}` מהתוצאה הראשונה, מוגבל לישראל | — |
| שרת: לא נמצאה | אין תוצאות | 404 `address_not_found` | AD-13 |
| שרת: קלט לא תקין | פחות מ-2 תווים אחרי trim, מעל 200, או בלי `q` | 422, ואין קריאה ל-Nominatim | AD-13 |
| שרת: Nominatim נכשל | timeout, שגיאה, 429 או תשובה לא תקינה | 503 `geocoding_unavailable` | הכתובת לא בלוג ולא בהודעה |
| שרת: בלי token | `GET` | 401 `auth_required` | AD-13 |
| פרטיות | קישור בשלב 1 | נפתח `/privacy` עם כפתור חזרה, וחוזרים לאותו שלב | — |

</intent-contract>

## Code Map

- `mobile/app/(tabs)/_layout.tsx` -- כאן מפנים ל-`/onboarding` בעזרת `Redirect`, אחרי שהדגל נקרא.
- `mobile/app/_layout.tsx` -- Root `Stack`, ו-SplashScreen שמוסתר כשהפונטים מוכנים. אין להשאיר מסך ריק אם קריאת הדגל מתעכבת.
- `backend/app/core/firebase.py` -- דוגמה ל-port עם dependency שאפשר להחליף, ולקריאת רשת עם timeout. `backend/app/modules/geo/*` -- כרגע ריק. ל-router יש `prefix`: לבדוק שהנתיב יוצא `/v1/geo/geocode`.
- `docs/implementation-artifacts/spec-1-6-onboarding-attempt.patch` -- המימוש הקיים, שכבר הוחל על העץ. כאן משנים רק את מה שהמפרט שינה.
- `mobile/src/identity/device.ts` -- דוגמה לשימוש ב-`expo-secure-store` ולמפתחות `cartwise.*`.
- `mobile/src/components/RangePicker.tsx`, `mobile/src/profile/useRange.ts`, `mobile/app/range.tsx` -- שלב הטווח. לא מציגים את `RangePicker` לפני `status === 'ready'`.
- `mobile/src/components/ClubsList.tsx` -- שלב המועדונים.
- `mobile/app/clubs.tsx` -- דוגמה למסך עם חזרה.
- `mobile/app.config.ts` -- כאן מוסיפים את ה-plugin של `expo-location`, עם `ACCESS_COARSE_LOCATION` בלבד והסבר בעברית.
- `docs/planning-artifacts/ux-designs/ux-CartWise-2026-10-26/mockups/screens-1-onboarding-home.html:11` -- ה-symbol של הדמות. שורות 18-73 -- SCR-ONB-1..4, כולל הטקסטים. `EXPERIENCE.md:147` -- הרשאה חסרה, `EXPERIENCE.md:212` -- §10.1.
- `docs/planning-artifacts/prds/prd-CartWise-2026-10-26/prd.md:480` -- NFR-11 עד NFR-15, הבסיס לסיכום הפרטיות.

## Tasks & Acceptance

**Execution:**
- `mobile/package.json` -- `npx expo install expo-location`. בשגיאת תעודה עוצרים ומדווחים לפי CLAUDE.md.
- `mobile/app.config.ts` -- plugin ו-`android.permissions` של מיקום משוער בלבד. בדיקה ב-`app-config.test.ts`.
- `mobile/src/onboarding/state.ts` -- `isOnboardingDone` ו-`markOnboardingDone`. לא זורקות שגיאה.
- `backend/app/modules/geo/{service,schemas,routes}.py`, `backend/app/core/config.py` -- port בשם `Geocoder`, מימוש `NominatimGeocoder`, ו-`NOMINATIM_URL`, עם ערך ב-`.env.example`.
- `backend/tests/{unit,integration}/test_geocode.py` -- שורות השרת במטריצה עם fake, בלי רשת. בדיקה שהכתובת לא בלוג.
- `mobile/openapi.json`, `mobile/src/api/schema.ts` -- `npm run gen:api`.
- `mobile/src/onboarding/origin.ts` -- `resolveAddress(text)` דרך ה-API, `saveOrigin`, `getSavedOrigin`: `{label, lat, lng}`. 404 הוא "לא נמצאה", וכל כשל אחר הוא "לא הצלחנו לבדוק".
- `mobile/src/components/Mascot.tsx` -- הדמות מה-mockup, עם `size`.
- `mobile/app/onboarding.tsx` -- ארבעת השלבים, נקודות התקדמות, "דלג", וחזרה של Android.
- `mobile/src/components/OriginStep.tsx` -- הרשאה, סירוב, `Linking.openSettings`, והזנת כתובת.
- `mobile/app/privacy.tsx` -- סיכום קצר בעברית פשוטה, מ-NFR-11 עד NFR-13 ומ-FR-2: מה נשמר ומה לא. בלי התחייבות משפטית.
- `mobile/app/(tabs)/_layout.tsx` -- קריאת הדגל ו-`Redirect`.
- `mobile/src/i18n/he.json` -- כל המחרוזות.
- `mobile/__tests__/{onboarding-state,origin,origin-step,onboarding-screen,privacy-screen}.test.tsx`, ותוספת ל-`tabs-layout.test.tsx` -- כל שורות המטריצה, עם mock ל-`expo-location` ול-`expo-secure-store`.

**Acceptance Criteria:**
- Given פתיחה ראשונה, then מוצגים עד 4 מסכים: מה האפליקציה עושה, הרשאת מיקום, טווח ומועדונים, ובכל אחד "דלג".
- Given שסירבתי להרשאת מיקום, when אני מזין כתובת שנמצאה, then היא נשמרת במכשיר כנקודת מוצא, ו-`getSavedOrigin` מחזירה אותה.
- Given שסיימתי או דילגתי עד הסוף, when אני פותח שוב, then ה-Onboarding לא מוצג.
- Given כל הזרימה, then לא מוצג מסך הרשמה, מיקום מההרשאה לא נשלח לשרת, והכתובת לא נשמרת בשרת.
- Given שאין הרשאת מיקום, when מזינים כתובת, then היא מאותרת ונשמרת. זה נבדק בלי mock של הרשאה שמאשרת.

## Spec Change Log

### 2026-11-02 — geocoding דרך השרת
- **מה הפעיל את השינוי:** `geocodeAsync` ב-Android דורש הרשאת מיקום (`LocationModule.kt:774`), ולכן נכשל אצל מי שסירב.
- **מה שונה:** ה-intent-contract שונה בהחלטת המשתמשת ("תעשה חינמי"): Nominatim דרך השרת.
- **מצב רע שנמנע:** מי שסירב להרשאה לא יכול היה לשמור כתובת, והבדיקות עברו כי הספרייה הוחלפה ב-mock.
- **KEEP:** כל שאר המימוש מה-patch: השלבים, `RangeEditor`, `OnboardingFrame`, הדגל בזיכרון, ו-`blockedPermissions`.

## Review Triage Log

### 2026-11-02 — Review pass
- verdicts: 1 findings — high 1, medium 0, low 0, false 0, maybe-false 0
- findings:
  - Implementation:
    - `high` `intent_gap` `geocodeAsync` ב-Android זורק `LocationUnauthorizedException` כשאין הרשאת מיקום (`expo-location` 56.0.26, `LocationModule.kt:774`, וגם `Location.ts:192`), ולכן מי שסירב להרשאה לא יכול לשמור כתובת, בניגוד ל-AC2 — ה-intent-contract מחייב geocoding של המכשיר ואוסר על שירות משלנו, ולכן אין תיקון בלי החלטה. הניסיון נשמר ב-`spec-1-6-onboarding-attempt.patch`, והקוד הוחזר. ארבעת הסוקרים לא הורצו.

### 2026-11-03 — Review pass
- verdicts: 46 findings — high 0, medium 7, low 31, false 3, maybe-false 5
- findings:
  - Intent Alignment:
    - `maybe-false` `defer` בחירה על מפה לא נבנתה — תלוי בקריאה של "כתובת או מפה". כבר ב-deferred.
    - `maybe-false` `defer` לנקודת המוצא אין קורא — ההשוואה ב-Epic 5. כבר ב-deferred.
    - `low` `reject` קריאת דגל איטית מדלגת על ה-Onboarding בפתיחה הראשונה — נדיר, והוא יוצג בפתיחה הבאה.
    - `medium` `patch` הפנייה, סיום ודגל לא נבדקים יחד — `onboarding-flow.test.tsx`, עם state וראוטר אמיתיים.
    - `low` `reject` `locationWhenInUsePermission` משפיע רק על iOS — לא מזיק, ו-iOS מגיע בגרסה 1.1.
    - `medium` `patch` חזרה מההגדרות — `AppState` בודק את ההרשאה מחדש.
    - `maybe-false` `defer` Nominatim לא הופעל מול השירות האמיתי — כבר ב-deferred.
  - Edge Case Hunter:
    - `low` `patch` `OverflowError` ו-`RecursionError` נותנים 500 — נתפסים, ומחזירים 503.
    - `low` `reject` `lat: true` מתקבל — Nominatim מחזיר מחרוזות, והגנה נוספת היא יותר מתיקון ישיר.
    - `low` `reject` timeout לכל פעולת socket, ולא כולל — דורש שרת שמטפטף, והתיקון מוסיף executor.
    - `low` `patch` כתובת של תו אחד — הכפתור מושבת מתחת ל-2 תווים.
    - `medium` `patch` חזרה מההגדרות — אותו תיקון.
    - `low` `reject` לחיצה שנייה לפני ה-render ב-`OriginStep` — נדיר. נוספה בדיקה שהכפתור מושבת בזמן הבדיקה.
    - `low` `patch` לחיצה כפולה מדלגת על שלב — `next` מתעלם מקריאה תוך 400ms. סטייה מכוונת מההוראה: הלחיצה השנייה מגיעה אחרי ה-render של השלב הבא.
    - `low` `reject` כתובת שמורה נשארת אחרי אישור מיקום — אין עדיין קורא. ההחלטה רשומה ב-deferred ל-Epic 5.
    - `low` `reject` deep link בפתיחה ראשונה עוקף את ה-Onboarding — אין עדיין קישורים כאלה.
    - `low` `patch` כל 404 נחשב "לא נמצאה" — רק `address_not_found`.
    - `low` `reject` כשל שמירה אחרי יציאה מהשלב — כמו ב-Stories 1.3 עד 1.5.
    - `low` `reject` (claim) ערכים קשיחים בדמות ובסיכה — מתועדים בקוד, ואין להם טוקן ב-DESIGN.md.
  - Blind Hunter:
    - `medium` `patch` חזרה מההגדרות — אותו תיקון. `canAskAgain` לא נוסף: הגדרות וכתובת מספיקות.
    - `low` `patch` אורך מינימלי בלקוח — אותו תיקון.
    - `medium` `defer` אין הגבלת קצב לכל subject — חסר בכל ה-endpoints, ושייך ל-Story 10.3. רשום ב-deferred.
    - `low` `patch` הלוג לא מבחין בין 429 ל-500 — נוסף `http_status`. השהיה אחרי 429 לא נוספה.
    - `maybe-false` `defer` התאמה שגויה נשמרת בלי אישור — כדי להכריע: בדיקה מול השירות. רשום ב-deferred.
    - `maybe-false` `defer` `countrycodes=il` עלול להחריג יישובים — כדי להכריע: בדיקה מול השירות. רשום ב-deferred.
    - `medium` `patch` סיכום הפרטיות מכחיש את ה-geohash — נוסח מחדש, והפריט עבר ל"מה נשמר".
    - `false` `reject` `privacy.items.images` משמיט שמירה אצל ספק — החילוץ נעשה ב-OCR מקומי בשרת שלנו, ואין ספק חיצוני.
    - `low` `patch` נוסח ההסכמה טוען שקראו מדיניות שלא קיימת — "לפני שממשיכים, אפשר לקרוא את סיכום הפרטיות".
    - `low` `reject` מסך ריק עד 1.5 שניות בקריאת הדגל — קורה רק כשהקריאה איטית.
    - `low` `patch` אין חיווי בבדיקת כתובת — "בודקים...".
    - `low` `reject` אין יציאה ממצב הזנת הכתובת — כפתור החזרה ו"דלג" זמינים.
    - `low` `reject` כתובת שמורה בלי ניהול — אין עדיין קורא. רשום ב-deferred.
    - `low` `patch` `OverflowError` — אותו תיקון.
    - `low` `patch` `lru_cache` ו-`MAX_RESPONSE_BYTES` לא נבדקים — נוספו בדיקות.
    - `low` `reject` מקש שליחה ואיפוס שגיאה בטופס — נוחות, לא תקלה.
    - `low` `patch` הקרדיט ל-OSM בלי קישור — קישור ל-`openstreetmap.org/copyright`.
    - `false` `reject` קבצים מיוצרים לא ב-patch — במכוון. CI בודק אותם, ו-`gen:api` רץ באימות.
  - Verification Gap:
    - `low` `patch` אין בדיקה ש-`get_geocoder` מחזיר אותו מופע — `test_get_geocoder_keeps_one_instance_per_url`.
    - `low` `patch` ענף `HTTPException` לא נבדק — `IncompleteRead` ו-`BadStatusLine`.
    - `low` `patch` טווח `lon` לא נבדק — `"200"` ו-`"NaN"`.
    - `low` `patch` מגבלת גודל התשובה לא נבדקת — `test_http_get_reads_at_most_the_limit`.
    - `low` `patch` הכפתורים בזמן בדיקת כתובת — לחיצה שנייה לא שולחת בקשה.
    - `low` `patch` `maxLength` של הכתובת — נוספה בדיקה.
    - `medium` `patch` הסיבוב המלא של ה-Onboarding — `onboarding-flow.test.tsx`. בדיקת מוטציה: הסרת הדגל בזיכרון מכשילה אותה.
    - `low` `patch` (other) כתובת של תו אחד — אותו תיקון.
    - `false` `reject` (other) בדיקות אינטגרציה מדלגות בלי Docker — ב-CI וב-Verification מוגדר `CARTWISE_REQUIRE_DOCKER=1`.

## Design Notes

- **למה דרך השרת:** זה חינמי ובלי חשבון, והחיבור לספק נמצא במקום אחד, כך שאפשר להחליף אותו בלי לעדכן את האפליקציה. הארכיטקטורה כבר משתמשת ב-Nominatim לסניפים.
- **למה בלי מפה עכשיו:** ה-AC אומר "כתובת או נקודה על המפה", וה-UX מציג רק כתובת. מפה דורשת החלטה על ספרייה ומפתח, שעדיין פתוחה ב-Q8.

## Verification

**Commands:**
- `cd mobile && npm run lint && npm run typecheck && npm test -- --ci` -- expected: עובר
- `cd mobile && npx expo export --platform android --output-dir <tmp>` -- expected: נבנה. אחר כך מוחקים את התיקייה.
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app && CARTWISE_REQUIRE_DOCKER=1 uv run pytest -q` -- expected: הכול עובר
- `cd mobile && npm run gen:api` -- expected: עובר

## Auto Run Result

Status: done

**סיכום:** בפתיחה הראשונה מוצגים ארבעה שלבים: ברוכים הבאים, מיקום, טווח ומועדונים, ובכל אחד "דלג". מי שסירב להרשאת מיקום יכול להזין כתובת. היא מאותרת דרך השרת שלנו מול Nominatim, והתוצאה נשמרת במכשיר בלבד כנקודת מוצא.

**קבצים:**
- `backend/app/modules/geo/*`, `backend/app/core/config.py`, `.env.example` -- `GET /v1/geo/geocode`, ה-port `Geocoder`, `NominatimGeocoder` ו-`NOMINATIM_URL`.
- `backend/tests/{unit,integration}/test_geocode.py` -- השרת, בלי רשת.
- `mobile/app/onboarding.tsx`, `mobile/src/components/{OnboardingFrame,OriginStep,Mascot,RangeEditor}.tsx` -- השלבים והרכיבים.
- `mobile/src/onboarding/{state,origin}.ts` -- הדגל, ואיתור ושמירה של הכתובת.
- `mobile/app/privacy.tsx` -- סיכום הפרטיות.
- `mobile/app/(tabs)/_layout.tsx`, `mobile/app/range.tsx` -- הפנייה בפתיחה ראשונה, ומסך הטווח על `RangeEditor`.
- `mobile/app.config.ts`, `mobile/package.json`, `mobile/package-lock.json` -- `expo-location`, עם מיקום משוער בלבד.
- `mobile/src/i18n/he.json`, `mobile/openapi.json`, `mobile/src/api/schema.ts` -- מחרוזות ולקוח מיוצר.
- `mobile/__tests__/{onboarding-flow,onboarding-state,onboarding-screen,origin,origin-step,privacy-screen,tabs-layout,app-config}.test.*` -- המטריצה בצד האפליקציה.

**ממצאי הסקירה:** 46 ממצאים. התיקונים כיסו 24 שורות: 6 medium ו-18 low. ה-medium מתחלקים לשלוש קבוצות: חזרה מההגדרות (3 שורות), הסיבוב המלא של ה-Onboarding (2 שורות), וניסוח הפרטיות על המיקום (שורה אחת). 6 שורות נדחו ל-deferred, ואחת מהן medium מאומת (הגבלת קצב). 16 נדחו, והנימוק של כל אחת רשום ב-Review Triage Log.

**המלצה לסקירת המשך:** `true`. תוקנו שלוש קבוצות medium. הסיכון שלא אומת: החזרה מההגדרות דרך `AppState`, ובקשת ההרשאה כש-`ACCESS_FINE_LOCATION` חסום, לא הופעלו במכשיר.

**אימות:**
- backend: ruff, format ו-mypy עברו. `CARTWISE_REQUIRE_DOCKER=1 pytest`: 415 עברו.
- mobile: `gen:api`, lint ו-typecheck עברו, ו-360 בדיקות עברו בשתי ריצות.
- `expo export` ל-Android: עבר.
- gitleaks על הקבצים שהשתנו: `no leaks found`.

**סיכונים שנשארו:**
- Nominatim לא נקרא אף פעם. תנאי השימוש ואיכות התוצאות בעברית לא נבדקו.
- OpenStreetMap מקבל את הכתובת שהמשתמש הקליד. זה נושא לבדיקה המשפטית (NFR-14).
- הכתובת עוברת ב-query string. הלוגים שלנו לא רושמים אותה, אבל כשמוסיפים את Caddy צריך לוודא שגם הוא לא רושם.
- הזרימה לא נבדקה במכשיר או באמולטור: RTL, TalkBack, המקלדת במסך הכתובת.
- `npm audit` דיווח על 62 פגיעויות, 11 מהן high. לא נבדק אם הן קיימות מלפני ההתקנה.
- סף 400ms ללחיצה כפולה נבחר בלי מדידה במכשיר.
