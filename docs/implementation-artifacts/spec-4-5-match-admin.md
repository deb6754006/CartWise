---
title: 'Story 4.5: כלי ניהול התאמות'
type: 'feature'
created: '2026-11-10'
status: 'done'
baseline_revision: '09298e74be67626127a5ddda78ce38d602be0bf2'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/docs/implementation-artifacts/epic-4-context.md'
  - '{project-root}/docs/implementation-artifacts/spec-4-3-vote-finalization.md'
  - '{project-root}/docs/implementation-artifacts/spec-4-4-match-memory.md'
warnings: ['oversized']
deferred:
  - summary: >-
      זמן הריצה של כל חבילת הבדיקות לא יציב בסביבת הפיתוח: בין 3 דקות ל-2 שעות ו-13 דקות. היו גם שלוש ריצות שנראו "תקועות".
    evidence: |-
      בכל הפעמים הבסיס היה פנוי ולא היו נעילות. בריצה האחרונה, עם faulthandler_timeout=120, לא נוצר שום dump, וכל 1027 הבדיקות עברו אחרי 7977 שניות. כנראה זה עומס על המכונה, או על Docker Desktop, ולא קוד. כדי להכריע: למדוד ב-CI (GitHub Actions), ולבדוק את המשאבים של Docker Desktop מקומית.
    location: >-
      backend/pyproject.toml (pytest)
    severity: low
---

<intent-contract>

## Intent

**Problem:** FR-41 דורש כלי למפעיל. המפעיל צריך לראות שלושה דברים:
- התאמות במחלוקת.
- תור של התאמות לא ודאיות, מסודר לפי מספר ההופעות.
- מוצרים חדשים שממתינים לאישור.

הכלי צריך לאפשר למפעיל:
- לאשר התאמה. ההתאמה הופכת לסופית.
- לאשר מוצר חדש.
- למזג שני מוצרים כפולים, כך שכל ההתאמות והתצפיות יעברו למוצר שנשאר.

שום דבר מזה לא קיים היום. גם הזיהוי של מפעיל לא קיים.

**Approach:**
- **זיהוי מפעיל:** ‏endpoints תחת `/v1/admin/matches` ו-`/v1/admin/products`, עם הרשאת מפעיל. מפעיל הוא משתמש רשום שה-Firebase UID שלו מופיע ברשימה `OPERATOR_FIREBASE_UIDS` בהגדרות. כל ה-endpoints עוברים דרך שירותים במודולים הבעלים.
- **"UI מינימלי" ב-MVP:** סקריפט CLI ‏`scripts/matches.py` שקורא לאותם שירותים. אין עדיין מסך במובייל.

## Boundaries & Constraints

**Always:**
- **הרשאה:**
  - **`require_operator`:** ‏dependency חדש ב-`core/auth.py`.
    - מאמת Firebase ID token בעזרת ה-verifier הקיים. ‏device token לא מתקבל.
    - ה-UID חייב להופיע ב-`Settings.OPERATOR_FIREBASE_UIDS`: רשימה מופרדת בפסיקים, ברירת המחדל ריקה.
    - המשתמש חייב להיות קיים ולא מחוק.
    - מחזיר את `user_id`.
  - **שגיאות:**
    - בלי token: ‏401 `auth_required`.
    - token שאינו Firebase, או UID שלא ברשימה: ‏403 `forbidden`.
    - verifier לא מוגדר: ‏503 `auth_unavailable`, כמו ב-link.
  - **ריפו ציבורי:** בריפו אין UID אמיתי. ב-`deploy/README.md` כתוב איפה מגדירים את הרשימה.
- **מספר ההופעות:**
  - עמודה חדשה, `product_aliases.occurrences` (int, ברירת מחדל 0, מיגרציה `0014`).
  - `match()` מגדיל אותה ב-1 בכל קריאה שמחזירה כינוי קיים או כותבת כינוי, דרך `catalog_service.bump_alias_occurrences`.
  - `match_file_items` מגדיל ב-1, ב-bulk, את כל הכינויים שהשתמש בהם או שכתב.
  - כינויים קיימים מתחילים מ-0.
- **רשימות (GET):** כל הרשימות עם `limit` (ברירת מחדל 50, עד 200), ‏`offset`, ו-`total` בתשובה.
  - **`/v1/admin/matches/disputed`:** כינויי `disputed`. לכל כינוי: הרשת, הטקסט, המוצר הנוכחי, וספירת הקולות לכל מוצר, דרך `matching.service`.
  - **`/v1/admin/matches/uncertain`:** כינויי `uncertain`. מסודרים לפי `occurrences desc`, ואחר כך לפי `updated_at`. לכל כינוי: הרשת, הטקסט, המוצר, ה-confidence, ועד 3 מועמדים עם ציון.
  - **`/v1/admin/products/proposed`:** מוצרים `proposed`. לכל מוצר: השם, הברקוד, ומספר הכינויים שמצביעים עליו.
- **פעולות (POST):** כל הפעולות מחזירות את המצב החדש.
  - **`/v1/admin/matches/{alias_id}/approve`** עם `{product_id?}`:
    - קורא ל-`matching.service.approve_match` (4.3) עם ה-`user_id` של המפעיל.
    - **בנוסף (ה-deferred של 4.4):** כל שאר כינויי ה-`final` באותה רשת, עם אותו `alias_norm`, עוברים לאותו מוצר. ‏confidence=1.
    - כינוי לא קיים: ‏404. מוצר לא תקין: ‏422.
  - **`/v1/admin/products/{product_id}/approve`:**
    - ‏`proposed` הופך ל-`active`.
    - מוצר שכבר `active`: ‏200 בלי שינוי.
    - מוצר שהוא `merged_into`: ‏409 `product_merged`.
  - **`/v1/admin/products/merge`** עם `{keep_id, remove_id}`:
    - **שגיאות:**
      - שני ה-id זהים: ‏422.
      - אחד מהם לא קיים או `merged_into`: ‏404 או 409.
    - **בטרנזקציה אחת, כל מודול דרך השירות שלו:**
      1. **catalog:** כינויים של `remove` עוברים ל-`keep`. אם נוצרת התנגשות על ה-unique ‏`(chain, alias_norm, barcode)`, הכינוי של `remove` נמחק, וה-`occurrences` שלו מתווספים לכינוי שנשאר.
      2. **catalog:** ברקוד של `remove`: אם ל-`keep` אין ברקוד, הברקוד עובר אליו. אחרת הוא נשאר על `remove`.
      3. **catalog:** ‏`remove.status = 'merged_into'`, ו-`remove.merged_into_id = keep`. זו עמודה חדשה, nullable, עם FK.
      4. **pricing:** ‏`price_observations.product_id` עובר ל-`keep`. זה שינוי שיוך, לא שינוי מחיר, ולכן AD-3 לא נפגע: המחיר לא משתנה. ‏`promotion_products` עוברים, ואם יש כפילות, היא נמחקת.
      5. **matching:** ‏`match_candidates` של `remove` נמחקים. ‏`match_votes` עם product_id של `remove` עוברים ל-`keep`. אם נוצרת כפילות, הם נמחקים.
      6. בסוף: `pricing.service.refresh_current_prices`.
    - **מוצר `remove` עם ברקוד שנשאר עליו:** בקליטה הבאה הוא כבר `merged_into`. ‏`ensure_products_by_barcode` צריך להחזיר את `merged_into_id` במקום המוצר הממוזג, כדי שתצפיות חדשות ייכתבו על `keep`.
- **לוג:** ‏`admin_action` עם הפעולה, ה-ids, וה-`user_id` של המפעיל. זה לוג ביקורת, ומותר בו מזהה משתמש פנימי. בלי טקסט כינוי.
- **CLI ‏`scripts/matches.py`:**
  - פקודות: `disputed`, ‏`uncertain`, ‏`proposed`, ‏`approve <alias_id> [<product_id>] --operator <firebase_uid>`, ‏`approve-product <id> --operator ...` ו-`merge <keep> <remove> --operator ...`.
  - ה-UID חייב להופיע ב-`OPERATOR_FIREBASE_UIDS`.
  - הסקריפט מסרב לרוץ בלי DB.
- **OpenAPI:** ה-endpoints מתועדים. הלקוח במובייל מתעדכן (`npm run gen:api`) רק אם CI דורש זאת. לא בונים מסך.
- **מיגרציה:** `0014`. ‏`occurrences` ו-`merged_into_id`.

**Never:**
- לא להוסיף Firebase Admin SDK ולא custom claims. בלי מפתח service account (ראו Design Notes).
- לא לבנות מסך מובייל. לא לבנות חסימת משתמשים (FR-46, Epic 7).
- לא לשנות ערך מחיר של תצפית. לא למחוק תצפיות.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| לא מפעיל | token של משתמש שלא ברשימה | — | ‏403 `forbidden` |
| ‏device token | token של אורח | — | ‏403 |
| בלי token | — | — | ‏401 |
| תור לא ודאיות | 3 כינויי `uncertain`, עם occurrences 5, ‏1 ו-9 | הסדר: 9, ‏5, ‏1. ‏total 3. עד 3 מועמדים לכל אחד | — |
| מחלוקות | כינוי `disputed` עם קולות A:1 ו-B:2 | הכינוי מופיע עם ספירת הקולות | — |
| מוצרים ממתינים | מוצר `proposed` עם 2 כינויים | מופיע, עם alias_count 2 | — |
| אישור התאמה | ‏approve לכינוי `uncertain` | ‏`final`. יש הצבעה עם role `operator` | — |
| אישור מתקן העתקים | שני כינויי `final` לאותו norm ברשת, למוצר A. ‏approve לאחד מהם עם product_id=B | שני הכינויים `final` ל-B | — |
| אישור מוצר | מוצר `proposed` | ‏`active` | ‏merged: ‏409 |
| מיזוג | ‏keep K, ‏remove R. ל-R יש כינוי, 2 תצפיות, מבצע וברקוד, ול-K אין ברקוד | הכינוי, התצפיות והמבצע עוברים ל-K. הברקוד עובר ל-K. ‏R הוא `merged_into` עם merged_into_id=K. ‏current_prices מכיל את K | — |
| מיזוג, התנגשות כינויים | ל-K ול-R יש כינוי עם אותו `(chain, norm, barcode)` | נשאר כינוי אחד, של K, עם סכום ה-occurrences | — |
| מיזוג לא תקין | ‏keep שווה ל-remove, או מוצר שכבר מוזג | — | ‏422 או 409 |
| קליטה אחרי מיזוג | ‏PriceFull עם הברקוד של R (כשהוא נשאר על R) | התצפית נכתבת על K | — |
| הופעות | ‏match() פעמיים לאותו טקסט | ‏occurrences 2 | — |
| ‏CLI | ‏`uncertain` עם UID של מפעיל | הרשימה מודפסת. UID שלא ברשימה: יציאה עם שגיאה | — |

</intent-contract>

## Code Map

- `backend/app/core/auth.py:108-130` -- `require_subject`, ‏`require_firebase_uid` (verifier, ‏`auth_unavailable`, ‏`invalid_token`). כאן נוסף `require_operator`. בשביל המשתמש: `identity_service.user_for_firebase_uid`.
- `backend/app/core/config.py` -- `OPERATOR_FIREBASE_UIDS`.
- `backend/app/modules/matching/{service,repository,routes}.py` -- `approve_match`, ‏`match`, ‏`match_file_items` ו-`_tally` (4.3, 4.4). ה-routes היום ריקים, חוץ מה-import בשביל ה-hook.
- `backend/app/modules/catalog/{models,repository,service}.py` -- `Product` (status, ‏`merged_into`), ‏`ProductAlias`, ‏`ensure_products_by_barcode` ו-`final_products_by_norm`.
- `backend/app/modules/pricing/{repository,service}.py` -- `record_official_prices`, ‏`refresh_current_prices` ו-`promotion_products`.
- `backend/app/modules/registry.py` -- מוסיפים router בשם `admin`: מודול `admin` דק (routes ו-schemas בלבד) שקורא לשירותים. או routes בתוך matching ו-catalog. עדיף מודול `admin`.
- `backend/scripts/store_locations.py` -- הדפוס ל-CLI.
- `backend/migrations/versions/0013_match_votes.py` -- המיגרציה האחרונה. החדשה היא `0014`.
- `mobile/openapi.json`, ‏`mobile/src/api/schema.ts` -- מיוצרים מה-OpenAPI. ה-CI בודק שהם מעודכנים.

## Tasks & Acceptance

**Execution:**
- `backend/app/core/{config,auth}.py` -- הרשימה ו-`require_operator`.
- `backend/app/modules/catalog/*` + `backend/migrations/versions/0014_match_admin.py` -- `occurrences`, ‏`merged_into_id`, הרשימות, ‏`approve_product`, מיזוג הכינויים והברקוד, ‏`bump_alias_occurrences`, וההפניה של `ensure_products_by_barcode`.
- `backend/app/modules/pricing/*` -- `reassign_product(remove, keep)`.
- `backend/app/modules/matching/*` -- רשימות המחלוקות ותור הלא-ודאיות, ‏`occurrences` ב-match, ההפצה של approve, ו-`reassign_product` בהצבעות ובמועמדים.
- `backend/app/modules/admin/{__init__,routes,schemas}.py` + `registry.py` -- ה-endpoints.
- `backend/scripts/matches.py` -- ה-CLI.
- `mobile/openapi.json`, `mobile/src/api/schema.ts` -- ייצור מחדש, אם CI דורש.
- `backend/tests/integration/test_admin_matches.py` -- כל שורות המטריצה, דרך ה-API (TestClient) ודרך השירותים.
- `deploy/README.md` -- הגדרת מפעיל, ופקודות ה-CLI.

**Acceptance Criteria:**
- Given מפעיל, when הוא מבקש את הרשימות, then הוא מקבל את ההתאמות במחלוקת, תור של התאמות לא ודאיות לפי מספר ההופעות, ואת המוצרים החדשים שממתינים.
- Given מפעיל שמאשר התאמה, when הבקשה מסתיימת, then ההתאמה סופית (FR-39).
- Given מפעיל שממזג שני מוצרים, when המיזוג מסתיים, then כל ההתאמות והתצפיות עוברות למוצר שנשאר, והמוצר השני מסומן `merged_into`.

## Spec Change Log

## Review Triage Log

### 2026-11-10 — Review pass
- verdicts: 32 findings — high 0, medium 2, low 25, false 5, maybe-false 0
- findings:
  - Intent Alignment:
    - `low` `reject` ‏"מסך" לעומת CLI — ‏FR-41 מסומן `[הנחה: כלי פנימי בסיסי]`, ‏EXPERIENCE.md מוציא את הכלי מהיקף ה-UX, וה-spec קבע CLI. אפשר לבנות מסך על ה-endpoints בלי לשנות אותם.
    - `low` `reject` אין בדיקה לאישור של `disputed` דרך admin — ‏`approve_match` כבר נבדק על disputed ב-4.3.
    - `false` `reject` התנגשות כינויים במיזוג לא מומשה — היא לא יכולה לקרות: product_id לא חלק מהמפתח `(chain, alias_norm, barcode)`. שורת המטריצה הזו שגויה, ומה שנבדק במקומה הוא ש-occurrences נשמרים.
    - `false` `reject` "מוצרים ממתינים" כ-`proposed` — זה המצב שהוגדר ב-4.2.
    - `low` `reject` ‏occurrences מתחילים מ-0 — אין ספירה היסטורית לשחזר.
    - `false` `reject` היקף נוסף (realign, ‏audit, ‏redirect) — ה-realign הוא ה-deferred של 4.4. השאר נדרש כדי שהמיזוג יהיה נכון.
    - `low` `reject` רשימת UID ולא custom claim — החלטה מתועדת, חינמית ובלי סוד.
  - Blind Hunter:
    - `low` `patch` הצבעות `other` שמצביעות על המוצר של הכינוי עצמו — הופכות ל-`confirm` אחרי מיזוג.
    - `medium` `patch` אחרי מיזוג לא מעריכים מחדש — ‏`evaluate_alias` על כל כינוי שהשתנה.
    - `low` `patch` חורים ב-rank, ‏keep לא נכנס — remove מוחלף ב-keep, ‏rank רציף.
    - `low` `patch` ‏keep נשאר `proposed` — הופך ל-`active` כש-remove היה פעיל.
    - `low` `patch` ה-fallback של `insert_product` בלי coalesce — תוקן.
    - `low` `patch` ‏N+1 ב-disputed — שאילתה מקובצת אחת.
    - `low` `reject` ‏UPDATE של occurrences בכל match — עלות סבירה. ב-file items העדכון ממוין ופעם אחת.
    - `low` `reject` אינדקס שלא משרת את disputed — רשימה קטנה.
    - `low` `reject` אין תיעוד ואין ביטול למיזוג — יש לוג `admin_action`. ביטול מחוץ להיקף.
    - `low` `patch` שגיאת DB ב-CLI — הודעה מסודרת, ‏exit 1.
    - `low` `patch` פערי בדיקות — נוספו (token מזויף, סדר, CLI, מוצר ממוזג).
    - `false` `reject` קבצים חסרים ב-diff — ה-spec והקבצים המיוצרים הוצאו בכוונה.
  - Verification Gap:
    - `low` `patch` token לא תקין מול כל ה-endpoints — 401 `invalid_token`, ושום דבר לא משתנה.
    - `low` `patch` סדר הרשימות של disputed ו-proposed — הישן קודם, ונבדקה גם עימוד.
    - `low` `patch` ‏CLI ‏disputed ו-proposed — נבדקו.
    - `false` `reject` (Other) התנגשות במיזוג — אותו נימוק.
    - `low` `patch` (Other) ה-fallback של insert — אותו תיקון.
  - Edge Case Hunter:
    - `medium` `patch` ‏disputed לא מוערך מחדש אחרי מיזוג — אותו תיקון.
    - `low` `patch` ‏keep ‏proposed — אותו תיקון.
    - `low` `patch` מרוץ בין approve למיזוג — נעילה של המוצר היעד, ובדיקה חוזרת.
    - `low` `patch` סדר הנעילות של occurrences — הכל נאסף, ומעודכן פעם אחת וממוין.
    - `low` `patch` ספירה כפולה באותה קריאה — אותו תיקון.
    - `low` `patch` ‏coalesce ב-fallback — אותו תיקון.
    - `low` `patch` ‏token פגום מחזיר 403 — עכשיו 401.
    - `low` `patch` שגיאת DB ב-CLI — אותו תיקון.

## Design Notes

**מפעיל לפי רשימת UID, ולא לפי custom claim:** הארכיטקטורה מציעה custom claim. אבל כדי להגדיר claim צריך Firebase Admin SDK ומפתח service account, וזה סוד שצריך לנהל. רשימה ב-env היא חינמית, בלי סוד ובלי תלות חדשה, והיא מספיקה למפעיל אחד או שניים ב-MVP. אם יידרש, אפשר לעבור ל-claims בלי לשנות את ה-endpoints.

**שינוי שיוך של תצפיות במיזוג:** AD-3 אוסר UPDATE למחיר. כאן משתנה רק `product_id`, כלומר לאיזה מוצר שייכת התצפית, וזה מה ש-FR-41 מגדיר ("כל ההתאמות והתצפיות עוברות"). המחיר, הזמן והמקור לא משתנים.

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy` -- expected: נקי.
- `cd backend && CARTWISE_REQUIRE_DOCKER=1 uv run pytest` -- expected: הכל עובר.
- `cd mobile && npm run gen:api && npm run typecheck && npm test` -- expected: נקי, אם ה-OpenAPI השתנה. שגיאת תעודה: עוצרים ומדווחים.

## Auto Run Result

Status: done

**סיכום:** כלי ניהול התאמות.
- **`require_operator`:** ‏Firebase UID מתוך `OPERATOR_FIREBASE_UIDS`.
- **שישה endpoints תחת `/v1/admin`:** מחלוקות עם ספירת קולות, תור לא ודאיות לפי `occurrences`, מוצרים מוצעים, אישור התאמה (כולל יישור העתקי final), אישור מוצר, ומיזוג.
- **המיזוג:** מעביר כינויים, תצפיות (רק השיוך), מבצעים, הצבעות והמועמדים, מעביר את הברקוד, מעריך כינויים מחדש, ומרענן את `current_prices`.
- **קליטה אחרי מיזוג:** מפנה לברקוד של keep.
- **CLI:** ‏`scripts/matches.py` עם אותן פעולות.

**קבצים:**
- `backend/app/core/{auth,config}.py`.
- `backend/app/modules/admin/*` (חדש).
- `backend/app/modules/{catalog,matching,pricing}/*`.
- `backend/migrations/versions/0014_match_admin.py`.
- `backend/scripts/matches.py`.
- `backend/pyproject.toml` (faulthandler).
- `deploy/{docker-compose.yml,README.md}`.
- `mobile/{openapi.json,src/api/schema.ts}` (מיוצרים).
- הבדיקות.

**ממצאי הסקירה:** 32 ממצאים:
- **תוקנו:** entry אחד ברמת medium (הערכה מחדש אחרי מיזוג), ו-18 ברמת low.
- **נדחו לגמרי:** השאר. שורת המטריצה על התנגשות כינויים לא יכולה לקרות, ולכן לא נבדקה כפי שכתובה.

**המלצה לסקירת המשך:** `true`. מיזוג הוא פעולה בלתי הפיכה, שנוגעת בארבעה מודולים. הסיכון שלא אומת: מיזוג במקביל לקליטה בנפח אמיתי.

**אימות:**
- ruff, format ו-mypy נקיים.
- `CARTWISE_REQUIRE_DOCKER=1 pytest -v`: ‏1027 עברו. הריצה ארכה 7977 שניות, וזמן הריצה רשום ב-deferred.
- mobile: ‏gen:api, ‏typecheck ו-test.
- `docker compose config` תקין.
- gitleaks על כל מה שלא נדחף (44 קבצים): `no leaks found`.
