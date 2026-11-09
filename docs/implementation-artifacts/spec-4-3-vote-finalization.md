---
title: 'Story 4.3: התאמה סופית לפי אישורים'
type: 'feature'
created: '2026-11-09'
status: 'done'
baseline_revision: 'e6b4ba42150d6384a4dd3408d51bf18207cc5bb8'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/docs/implementation-artifacts/epic-4-context.md'
  - '{project-root}/docs/implementation-artifacts/spec-4-2-text-matching.md'
warnings: ['oversized']
deferred:
  - summary: >-
      המסלול ה-bulk של ברקוד (match_barcodes / ensure_certain_aliases) עדיין יכול להעביר למוצר אחר כינוי שיש עליו הצבעות.
    evidence: |-
      ‏match() כבר לא נוגע בכינוי עם הצבעות. במסלול ה-bulk זה כמעט לא יקרה: כינוי עם ברקוד הוא certain, ולא מגיע להצבעה. כדי להכריע: כשההצבעות יגיעו מחשבוניות (Epic 6), לבדוק אם יש כינויים כאלה, ולהחריג אותם גם ב-bulk.
    location: >-
      backend/app/modules/catalog/repository.py (upsert_certain_aliases)
    severity: low
---

<intent-contract>

## Intent

**Problem:** התאמה `uncertain` נשארת כזו לתמיד. אין דרך שבה הצבעות של משתמשים או אישור של מפעיל יהפכו אותה ל-`final`, ואין דרך שבה רוב לטובת מוצר אחר יעביר אותה. FR-39 דורש:
- 3 אישורים ממשתמשים שונים הופכים התאמה ל-`final`.
- רוב לטובת מוצר אחר מעביר את הכינוי למוצר הזה.
- אישור של מפעיל הופך התאמה ל-`final` מיד.
- כל עוד ההתאמה לא סופית, רמת האמינות שלה היא צהובה לכל היותר.

**Approach:** במודול matching נבנים שלושה דברים:
- הטבלה `match_votes`.
- `record_vote`: רושם הצבעה ומעריך מחדש את הכינוי באותה טרנזקציה.
- `approve_match`: אישור מפעיל.

ההחלטה לגבי משתמש "אמין" עוברת דרך `TrustGate`, ממשק שאפשר להחליף. עד Story 7.4 כל משתמש נחשב אמין. לקריאה של רמת האמינות (7.3) נחשפת `alias_state_for_product`.

## Boundaries & Constraints

**Always:**
- **`match_votes` (שייכת ל-matching):**
  - העמודות: id (UUIDv7), ‏alias_id FK `product_aliases` עם `ON DELETE CASCADE`, ‏user_id FK `users` עם `ON DELETE CASCADE`, ‏product_id FK `products` null עם `ON DELETE CASCADE`, ‏vote (`confirm`, ‏`other`, ‏`unknown`), ‏role (`user`, ‏`operator`), ‏created_at, ‏updated_at.
  - unique על `(alias_id, user_id)`: הצבעה חוזרת של אותו משתמש מחליפה את הקודמת. אינדקס על `user_id`.
  - CHECK: ‏`vote='other'` מחייב product_id. ב-`confirm` וב-`unknown`, ‏product_id הוא NULL.
- **`record_vote(session, alias_id, user_id, vote, product_id=None, now=None) -> VoteOutcome`:**
  - **שגיאות:**
    - כינוי לא קיים: `AppError` 404 `alias_not_found`.
    - ‏`other` בלי מוצר, או עם מוצר לא קיים או `merged_into`: ‏`AppError` 422 `invalid_vote`.
    - הצבעה `other` על המוצר הנוכחי של הכינוי נשמרת כ-`confirm`.
  - שומרת את ההצבעה (upsert) עם role=`user`, ואחר כך קוראת ל-`evaluate_alias`.
  - `VoteOutcome(alias_id, state, product_id, changed: bool)`.
- **`evaluate_alias(session, alias_id, trust: TrustGate, now) -> VoteOutcome`:**
  - נועלת את שורת הכינוי (`FOR UPDATE`). כינוי `final` לא משתנה, ומוחזר כמו שהוא.
  - **מה נספר:** הצבעות של role=`user`, ורק של משתמשים ש-`trust.counts(user_id)` מחזיר עבורם True, ושהם לא מחוקים (`users.deleted_at IS NULL`). ‏`unknown` לא נספר.
  - **ניקוד:** ‏`confirm` הוא קול למוצר הנוכחי של הכינוי. ‏`other` הוא קול ל-product_id של ההצבעה.
  - **מעבר למוצר אחר:** אם יש מוצר P, שונה מהמוצר הנוכחי, עם יותר קולות מהמוצר הנוכחי, וגם יותר ממחצית הקולות שנספרו, הכינוי עובר ל-P. ה-state הוא `disputed`, ‏confidence=NULL. ההצבעות `confirm` הקיימות לא עוברות ל-P, כי הן אישרו את המוצר הקודם.
  - **הפיכה לסופי:** אחרי המעבר, אם למוצר הנוכחי יש לפחות `MATCH_FINAL_VOTES` (ברירת מחדל 3) קולות משתמשים שונים, הכינוי הופך ל-`final`, עם confidence=1.
  - שינוי במוצר או ב-state מעדכן את `updated_at`, ונרשם לוג `matching_vote_evaluated`: ‏alias_id, ‏state, ומספר הקולות. בלי זיהוי משתמש.
- **`approve_match(session, alias_id, operator_user_id, product_id=None, now=None) -> VoteOutcome`:**
  - רושמת הצבעה עם role=`operator`, ‏vote=`confirm` או `other`.
  - הכינוי הופך ל-`final` מיד, עם product_id (הקיים, או החדש) ו-confidence=1. זה עובד גם על `disputed`, וגם על `final` למוצר אחר: אישור מפעיל גובר.
  - הבדיקה שהמשתמש הוא מפעיל שייכת ל-endpoint של 4.5, ולא לכאן. הפונקציה מניחה שהקורא בדק.
- **`TrustGate` (Protocol):**
  - `counts(session, user_id) -> bool`. ברירת המחדל היא `AllUsersCount`.
  - נקודה אחת להחלפה ב-7.4: ‏`matching.service.default_trust_gate()`.
- **`alias_state_for_product(session, chain_id, product_id) -> AliasState | None`:**
  - המצב ה"חלש" ביותר מבין הכינויים של הרשת שמצביעים על המוצר. הסדר מהחלש לחזק: `uncertain`, ‏`disputed`, ‏`certain`, ‏`final`.
  - None כשאין כינוי, כלומר מוצר עם ברקוד שאין לו כינוי. במקרה כזה הקורא מתייחס אליו כ-`certain`.
  - זה הקלט שיאפשר ל-Epic 7 (`trust.reliability_level`) להגביל לצהוב. החישוב של הצבע עצמו לא כאן.
- **מחיקת חשבון:** ‏`register_deletion_hook` מוחק את ההצבעות של המשתמש. מצב הכינויים לא מחושב מחדש: `final` שכבר נקבע נשאר.
- **`Settings`:** ‏`MATCH_FINAL_VOTES=3`, ‏`ge=1`, ‏`le=20`.
- **מיגרציה:** `0013`.
- **התאמה מול 4.1 ו-4.2:** ‏`disputed` ו-`final` הם מצבים "מיושבים". ‏`match` כבר לא משנה אותם (4.1 ו-4.2).

**Never:**
- לא לבנות endpoint, מסך, או בדיקת הרשאת operator (4.5 ו-Epic 6).
- לא לבנות תור `jobs` או job של `finalize_matches`: ההערכה רצה באותה טרנזקציה של ההצבעה (ראו Design Notes).
- לא לחשב רמת אמינות או צבע (Epic 7). לא לבנות trust score (7.4).
- לא לשמור פרטים מזהים בלוג.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| שלושה אישורים | כינוי `uncertain` למוצר A, ‏3 משתמשים שונים מצביעים `confirm` | אחרי השלישי: ‏`final`, ‏confidence 1, ‏changed True | — |
| שניים בלבד | 2 אישורים | נשאר `uncertain` | — |
| אותו משתמש פעמיים | משתמש אחד מצביע `confirm` 3 פעמים | קול אחד. לא `final` | — |
| רוב למוצר אחר | ‏A עם אישור אחד, ‏B עם 2 הצבעות `other` | הכינוי עובר ל-B, במצב `disputed` | — |
| מחלוקת, ואז סופי | אחרי המעבר ל-B, עוד הצבעה `other` ל-B | ל-B יש 3 קולות, והכינוי `final` ל-B | — |
| תיקו | ‏A עם קול אחד, ‏B עם קול אחד | אין שינוי | — |
| ‏unknown | 3 הצבעות `unknown` | אין שינוי | — |
| משתמש לא אמין | ‏TrustGate מחזיר False למשתמש אחד מתוך 3 | לא `final` | — |
| משתמש מחוק | משתמש עם `deleted_at` | הקול שלו לא נספר | — |
| אישור מפעיל | כינוי `uncertain` | ‏`final` מיד. נשמרה הצבעה role `operator` | — |
| מפעיל בוחר מוצר אחר | ‏approve_match עם product_id=B | ‏`final` ל-B | — |
| ‏final לא משתנה מהצבעות | כינוי `final` ל-A, ו-3 הצבעות `other` ל-B | נשאר `final` ל-A. ההצבעות נשמרות | — |
| ‏other בלי מוצר | ‏vote `other`, ‏product_id None | — | ‏422 `invalid_vote` |
| כינוי לא קיים | ‏alias_id אקראי | — | ‏404 `alias_not_found` |
| מחיקת חשבון | למשתמש יש הצבעות | ההצבעות נמחקות, ומצב הכינוי לא משתנה | — |
| מצב לאמינות | שני כינויים למוצר X ברשת, ‏`final` ו-`uncertain` | ‏`alias_state_for_product` מחזיר `uncertain` | — |

</intent-contract>

## Code Map

- `backend/app/modules/matching/{models,repository,service}.py` -- `MatchCandidate` (4.2), ‏`match`, ‏`_SETTLED`, ‏`MatchState`. כאן נוספים `MatchVote`, ‏`record_vote`, ‏`evaluate_alias`, ‏`approve_match`, ‏`TrustGate` ו-`alias_state_for_product`.
- `backend/app/modules/catalog/{repository,service}.py` -- `ProductAlias` שייך ל-catalog. השינוי של state ו-product_id עובר כאן: מוסיפים `lock_alias(alias_id)` ו-`set_alias_resolution(alias_id, product_id, state, confidence, now)`. גם `alias_states_for_product`.
- `backend/app/modules/identity/service.py:97` -- `register_deletion_hook(fn(session, user_id))`. הדפוס הוא דקורטור ב-matching.
- `backend/app/modules/identity/models.py:27` -- `User`, עם `deleted_at`. הקריאה דרך `identity.service`, למשל `active_user_ids(session, ids)`, ולא ישירות.
- `backend/app/core/errors.py` -- `AppError(code, message_he, status)`.
- `backend/app/core/config.py` -- הדפוס של ספי ההתאמה (4.2).
- `backend/migrations/versions/0012_match_candidates.py` -- המיגרציה האחרונה. החדשה היא `0013`.
- `backend/tests/integration/test_delete_account.py` -- הדפוס לבדיקה של deletion hook.

## Tasks & Acceptance

**Execution:**
- `backend/app/core/config.py` -- `MATCH_FINAL_VOTES`.
- `backend/app/modules/matching/models.py` + `backend/migrations/versions/0013_match_votes.py` -- הטבלה.
- `backend/app/modules/catalog/{repository,service}.py` -- הנעילה והעדכון של הכינוי, ו-`alias_states_for_product`.
- `backend/app/modules/identity/service.py` -- `active_user_ids`, אם עוד אין כזו.
- `backend/app/modules/matching/{repository,service}.py` -- ההצבעות, ההערכה, האישור, ה-gate, וה-deletion hook.
- `backend/tests/integration/test_match_votes.py` -- כל שורות המטריצה.
- `backend/tests/integration/*.py` -- הוספת `match_votes` ל-TRUNCATE בכל מקום שמנקים בו `product_aliases` או `users`.

**Acceptance Criteria:**
- Given התאמה לא ודאית, when 3 משתמשים שונים אישרו אותה, then היא הופכת לסופית.
- Given שרוב ההצבעות על כינוי מצביעות על מוצר אחר, when ההצבעה נרשמת, then הכינוי מתעדכן למוצר הזה.
- Given אישור מפעיל, when `approve_match` רץ, then ההתאמה סופית מיד.
- Given התאמה שעוד לא סופית, when Epic 7 שואל את `alias_state_for_product`, then הוא מקבל מצב שאינו `final`, וזה מה שיגביל את הרמה לצהוב.

## Spec Change Log

## Review Triage Log

### 2026-11-09 — Review pass
- verdicts: 27 findings — high 0, medium 4, low 16, false 7, maybe-false 0
- findings:
  - Edge Case Hunter:
    - `medium` `patch` הצבעת `other` אחת מעבירה כינוי בלי אישורים — `MIN_MOVE_VOTES = 2`.
    - `low` `patch` קולות למוצר `merged_into` — `_tally` מדלג עליהם.
    - `medium` `patch` אישור שמור בלי מוצר "זז" כשההתאמה האוטומטית מחליפה מוצר — `match()` מחזיר כינוי עם הצבעות כמו שהוא (memory).
    - `low` `patch` הצבעת משתמש דורסת אישור מפעיל — `ON CONFLICT … WHERE role <> 'operator'`.
    - `low` `patch` ערך הצבעה לא חוקי מחזיר 500 — עכשיו 422.
  - Intent Alignment:
    - `false` `reject` ‏AC1 נבדק רק ברמת השירות — אין עדיין דרך להצביע: אין מסך, וזה שייך ל-Epic 6.
    - `low` `reject` ‏AC2 עם מצב `disputed` נוסף — מתועד ב-Design Notes.
    - `false` `reject` ‏AC3 (צהוב) לא מיושם — לפי ה-spec, ‏7.3 תחיל אותו. ‏`alias_state_for_product` הוא הקלט.
    - `false` `reject` ‏AC4 בלי כלי ניהול — 4.5. ‏`approve_match` מוכן.
    - `false` `reject` תיקון של משתמש לא מגיע מאף מקום — מסך אישור החשבונית, Epic 6.
    - `false` `reject` אין job ‏`finalize_matches` — מתועד ב-Design Notes. ההערכה רצה באותה טרנזקציה.
  - Blind Hunter:
    - `medium` `patch` אישורים עוברים למוצר אחר בגלל `upsert_alias` — אותו תיקון (memory).
    - `low` `patch` מוצר ממוזג בספירה — אותו תיקון.
    - `low` `patch` ‏`confirm` על כינוי בלי מוצר — 422.
    - `low` `patch` משתמש מחוק או לא קיים — 404 `user_not_found`.
    - `low` `patch` מפעיל ומשתמש על אותו מפתח — אותו תיקון.
    - `medium` `patch` ‏final מתעלם מקולות נגד — דורש גם יותר ממחצית הקולות.
    - `false` `reject` מעבר ישיר מ-`uncertain` ל-`final` — כך ה-spec קובע: "אחרי המעבר, ≥3 ← final".
    - `low` `patch` בדיקות `updated_at` לא בודקות כלום — מצביעים ב-`LATER`.
    - `low` `patch` ה-hook נרשם דרך import — נוספה בדיקת subprocess. ‏registry טוען את ה-routes גם ב-API וגם ב-worker.
    - `low` `patch` ‏N+1 ב-`TrustGate` — `counting(session, user_ids)`.
    - `low` `patch` אין אינדקס על `product_id` — נוסף.
    - `low` `patch` בדיקות חסרות — מקביליות, מעבר B ל-C, ומפעיל ואז משתמש.
    - `false` `reject` ה-spec לא בתוך ה-diff — הוצא בכוונה.
  - Verification Gap:
    - `low` `patch` רוב יחסי בלי רוב מוחלט — נוספה בדיקה.
    - `low` `patch` הנעילה לא נבדקת — שני threads, והתוצאה `final`.
    - `low` `patch` רישום ה-hook באפליקציה — בדיקת subprocess.

## Design Notes

**בלי תור jobs:** הארכיטקטורה מציעה job בשם `finalize_matches`. אבל ההערכה נוגעת בכינוי אחד, היא דטרמיניסטית, ורצה באותה טרנזקציה של ההצבעה. כך אין תור לבנות, ואין חלון שבו ההצבעה כבר קיימת וההחלטה עוד לא. אם בעתיד ההערכה תהיה כבדה, אפשר להעביר אותה לתור, בלי לשנות את ה-API.

**למה `disputed` קודם, ורק אחר כך `final`:** מעבר למוצר אחר, בלי 3 קולות למוצר החדש, הוא עדיין לא ודאי. `disputed` מסמן שבני אדם התערבו, ולכן ההתאמה האוטומטית (4.1, 4.2) לא דורסת אותו. כשמגיעים 3 קולות, הוא הופך ל-`final`.

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy` -- expected: נקי.
- `cd backend && CARTWISE_REQUIRE_DOCKER=1 uv run pytest` -- expected: הכל עובר.

## Auto Run Result

Status: done

**סיכום:** נוספה הטבלה `match_votes`. ‏`record_vote` מעריך את הכינוי באותה טרנזקציה, עם נעילה:
- **מעבר למוצר אחר:** לפחות 2 קולות, יותר מהמוצר הנוכחי, ויותר ממחצית הקולות. המצב אחרי מעבר הוא `disputed`.
- **הפיכה לסופי:** לפחות `MATCH_FINAL_VOTES` (3) קולות, וגם יותר ממחצית.
- **`approve_match`:** אישור מפעיל הופך לסופי מיד.
- **`TrustGate`:** בינתיים כל משתמש נספר. יוחלף ב-7.4.
- **הקלט לרמת האמינות:** `alias_state_for_product`, לשימוש ב-7.3.
- **מחיקת חשבון:** מוחקת את ההצבעות.
- **`match()`:** לא משנה כינוי שיש עליו הצבעות.

**קבצים:**
- `backend/app/modules/matching/{models,repository,service,routes}.py`, `backend/migrations/versions/0013_match_votes.py`.
- `backend/app/modules/catalog/{repository,service}.py` (נעילה, עדכון מצב).
- `backend/app/modules/identity/{repository,service}.py` (`active_user_ids`).
- `backend/app/core/config.py`.
- הבדיקות.

**ממצאי הסקירה:** 27 ממצאים:
- **תוקנו:** 3 entries ברמת medium (אישורים שזזים, מעבר בקול אחד, סופי בלי רוב), ו-11 ברמת low.
- **נדחה ל-deferred:** אחד (ה-bulk של הברקוד).
- **נדחו לגמרי:** השאר.

**המלצה לסקירת המשך:** `true`. תוקנו 3 entries ברמת medium בכללי ההחלטה. הסיכון שלא אומת: ההצבעות עוד לא מגיעות מזרימה אמיתית (Epic 6).

**אימות:**
- ruff, format ו-mypy נקיים.
- `CARTWISE_REQUIRE_DOCKER=1 pytest`: 951 עברו.
- gitleaks על הקבצים שהשתנו: `no leaks found`.
