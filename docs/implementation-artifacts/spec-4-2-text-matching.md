---
title: 'Story 4.2: התאמה בלי ברקוד, עם ציון ביטחון'
type: 'feature'
created: '2026-11-09'
status: 'done'
baseline_revision: '5662f2cedddc0504b19faba179405c7be88958d8'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/docs/implementation-artifacts/epic-4-context.md'
  - '{project-root}/docs/implementation-artifacts/spec-4-1-barcode-matching.md'
warnings: ['oversized']
deferred:
  - summary: >-
      שתי התאמות במקביל לאותו טקסט חדש יכולות ליצור שתי הצעות מוצר, ואחת מהן נשארת בלי כינוי.
    evidence: |-
      ‏propose_product רץ לפני upsert_alias, בלי נעילה על המפתח. כדי להכריע: ב-4.5 (כלי ניהול) לנקות מוצרים proposed שאין עליהם כינויים, או לנעול לפי (chain_id, alias_norm).
    location: >-
      backend/app/modules/matching/service.py (_match_text)
    severity: low
---

<intent-contract>

## Intent

**Problem:** היום `matching.service.match` מחזיר `unmatched` לכל כינוי בלי ברקוד מוכר. פריטים בלי ברקוד מהקבצים (3.6), ושורות חשבונית (Epic 6), צריכים התאמה לפי השם, עם ציון ביטחון. כשאין מועמד מתאים, צריכה להיווצר הצעה למוצר חדש. בנוסף, צריך דרך למדוד את הדיוק (SM-1).

**Approach:**
- כשמסלול הברקוד של 4.1 לא מוצא התאמה, `match` עובר למסלול טקסט:
  1. מועמדים לפי דמיון trigram ‏(pg_trgm) ל-`products.name_norm`.
  2. לכל מועמד מחושב ציון משוקלל: דמיון טקסט, גודל, יחידה, ושפיות המחיר.
  3. לפי ספים, ההתאמה היא `certain`, ‏`uncertain`, או הצעה למוצר חדש (`products.status=proposed`).
- הכינוי נשמר עם המצב. בהתאמה `uncertain` נשמרים גם 3 המועמדים המובילים.
- סקריפט eval מודד precision של ההתאמות ה-`certain`, על כינויים שיש להם ברקוד, ולכן התשובה הנכונה ידועה.

## Boundaries & Constraints

**Always:**
- **סדר המסלולים ב-`match`:**
  1. ברקוד (4.1). אם הוא מצא מוצר, זו התוצאה.
  2. אחרת, אם יש כינוי קיים לאותו `(chain_id, alias_norm, barcode)` במצב `final` או `disputed`, מחזירים אותו כמו שהוא, כמו ב-4.1.
  3. אחרת, מסלול הטקסט.
  
  הכינוי נשמר עם `barcode` של הקלט: ברקוד תקין שאין לו מוצר נשמר. ברקוד לא תקין נשמר כ-NULL.
- **מועמדים:** עד 20 מוצרים, לפי `similarity(products.name_norm, alias_norm)`, עם סף trigram נמוך (`SET LOCAL pg_trgm.similarity_threshold = 0.2`, ושימוש באופרטור `%` כדי שהאינדקס ישמש). כל הסטטוסים חוץ מ-`merged_into`. גם מוצר `proposed` הוא מועמד, כדי שאותו פריט חדש לא ייצור הצעה שנייה.
- **חילוץ גודל ויחידה מהטקסט:** `parse_pack(text) -> (size: Decimal | None, unit: PackUnit | None)`. ביטוי רגולרי שמזהה את הדפוסים האלה:
  - `1ל`, ‏`1 ליטר`, ‏`1.5ל`
  - `750 מ"ל`, ‏`750מל`
  - `80ג`, ‏`80 גרם`, ‏`80 גר`
  - `1 ק"ג`, ‏`1קג`
  - `6 יח'`
  
  הפונקציה רצה על הטקסט אחרי `normalize_he`, כך שגרשיים כבר הוסרו. היא נמצאת במודול matching, ו-**לא** משנה את `normalize_he` (ראו ה-deferred של 4.1).
- **ציון:**
  - **הנוסחה:** `score = Σ wᵢ·fᵢ / Σ wᵢ` על התכונות הזמינות בלבד:
    - `text` (0.45): ‏`similarity`, מ-0 עד 1.
    - `size` (0.20): 1 אם שני הגדלים קיימים ושווים בטווח ±2% אחרי המרה לגרם או למ"ל (ק"ג ← גרם, ליטר ← מ"ל). אחרת 0.
    - `unit` (0.10): 1 אם לשתי היחידות אותו מימד (משקל, נפח או יחידות). אחרת 0.
    - `price` (0.05): 1 אם `context.unit_price_agorot` נמצא בטווח ±50% מהחציון של `current_prices` (regular) של המוצר. אחרת 0.
  - **תכונה חסרה,** בכל אחד מהצדדים, לא נכנסת לא למונה ולא למכנה. כך `text` לבדו נותן score = similarity.
  - **מותג (0.20):** לא בשימוש עד שיהיו מותגים במוצרים. כרגע `brand_id` תמיד ריק.
  - הציון מעוגל ל-3 ספרות רק לשמירה, ולא לפני ההשוואה לספים.
- **ספים, ב-`Settings` עם env:**
  - `MATCH_CERTAIN_THRESHOLD=0.85`: נקבע זמנית, יכויל עם ה-eval.
  - `MATCH_MIN_GAP=0.10`
  - `MATCH_NEW_PRODUCT_BELOW=0.30`
  - בין 0 ל-1. validator מוודא ש-`NEW_PRODUCT_BELOW < CERTAIN_THRESHOLD`.
- **ההחלטה:**
  - **`certain`:** המועמד הראשון עם `score >= CERTAIN_THRESHOLD`, וגם `score - score_2nd >= MIN_GAP` (כשאין מועמד שני, ‏score_2nd=0). הכינוי `certain` מצביע על המוצר, עם confidence=score.
  - **`new_product_proposal`:** אין מועמד עם `score >= NEW_PRODUCT_BELOW`.
    - catalog יוצר מוצר: `catalog.service.propose_product(name, pack_size, pack_unit)`, עם status=`proposed`, ‏barcode=NULL, והשם הוא טקסט הכינוי אחרי ניקוי.
    - הכינוי `uncertain` מצביע עליו, עם confidence=NULL.
  - **`uncertain`:** כל השאר. הכינוי `uncertain` מצביע על המועמד הראשון, עם confidence=score. ‏3 המועמדים המובילים נשמרים ב-`match_candidates`.
- **`match_candidates` (שייכת ל-matching):**
  - העמודות: alias_id FK (`ON DELETE CASCADE`), ‏product_id FK, ‏rank (1 עד 3), ‏score numeric(4,3), ‏created_at. ‏PK על `(alias_id, rank)`.
  - בכל התאמה מחדש של כינוי, המועמדים שלו מוחלפים. בהתאמה `certain` או הצעה למוצר חדש, המועמדים נמחקים.
- **כתיבת הכינוי:** רק דרך `catalog.service`, עם upsert כללי, `upsert_alias(state, product_id, confidence)`.
  - הפונקציה לא משנה כינוי `final` או `disputed`.
  - כינוי `certain` לא יורד ל-`uncertain` בהתאמה חוזרת לפי טקסט, אם הוא מצביע על אותו מוצר. אם הוא מצביע על מוצר אחר, המצב החדש קובע.
- **`MatchResult.candidates`:** tuple של `Candidate(product_id, score)`, מסודר מהגבוה לנמוך, עד 3. בהתאמה `certain` רק הראשון. בהצעה למוצר חדש ריק.
- **SM-1:**
  - `backend/scripts/eval_matching.py`:
    1. דוגם עד N (ברירת מחדל 500) כינויים `certain` שיש להם ברקוד (מ-4.1), עם seed קבוע.
    2. מריץ על כל אחד ניקוד טקסט **בלבד**, דרך פונקציה טהורה של הניקוד, בלי כתיבה, ובלי הברקוד.
    3. מדווח: מספר הדגימות, כמה יצאו `certain`, ‏precision של `certain` (המוצר שנבחר = המוצר של הברקוד), כמה `uncertain`, כמה הצעות, ‏recall@3.
  - פלט JSON ל-stdout. הסקריפט מסרב לרוץ ב-prod בלי `--allow-prod`, ולא כותב.
- **לוג:** `matching_match` (כבר קיים) מקבל גם `path` (`barcode`, ‏`text` או `memory`), ‏`score` ו-`gap`. בלי טקסט הכינוי.
- **מיגרציה:** `0012`.

**Never:**
- לא להוסיף embeddings, ‏pgvector, או שירות חיצוני בתשלום.
- לא לשנות את `normalize_he`. לא לבנות הצבעות, סופיות (4.3), זיכרון לפי `final` (4.4), או כלי ניהול (4.5). המסלול "memory" כאן הוא רק החזרה של `final` ו-`disputed` קיימים.
- לא לחבר עדיין את הקליטה. פריטים בלי ברקוד מהקבצים מגיעים ב-3.6.
- לא לבצע HTTP. לא לשמור טקסט כינוי בלוג.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| התאמה ודאית | מוצר "עגבניות שרי 250 גרם", כינוי "עגבניות שרי 250ג", בלי מוצר דומה אחר | ‏`certain` למוצר. ‏confidence ≥ 0.85. כינוי `certain`. אין שורות ב-`match_candidates` | — |
| שני מועמדים קרובים | שני מוצרים דומים, והפער בין הציונים פחות מ-0.1 | ‏`uncertain`, עם 2 מועמדים. כינוי `uncertain` למועמד הראשון. 2 שורות ב-`match_candidates` | — |
| ציון בינוני | ציון 0.6 | ‏`uncertain` | — |
| אין מועמד | טקסט שלא דומה לשום מוצר | ‏`new_product_proposal`. נוצר מוצר `proposed` בשם הכינוי. כינוי `uncertain` מצביע עליו, עם confidence NULL | — |
| אותו טקסט שוב, רשת אחרת | אחרי הצעה למוצר חדש | המוצר ה-`proposed` הוא מועמד חזק, ולא נוצרת הצעה שנייה | — |
| גודל שונה | כינוי "חלב 1ל", מוצרים "חלב 1 ליטר" ו"חלב 2 ליטר" | ‏"1 ליטר" מקבל ציון גבוה יותר | — |
| מחיר לא סביר | ‏`unit_price_agorot` פי 3 מהחציון | ‏price=0, והציון נמוך יותר מאשר במחיר סביר | — |
| בלי context | ‏context=None | רק text, ‏size ו-unit נכנסים לחישוב | — |
| ברקוד לא מוכר | ברקוד תקין שאין לו מוצר, וטקסט מוכר | מסלול טקסט. הכינוי נשמר עם הברקוד | — |
| final קיים | כינוי `final` לאותו מפתח | מוחזר כמו שהוא, ‏path=`memory` | — |
| certain לא יורד | כינוי `certain` למוצר A, והניקוד החדש לא ודאי, אבל מוביל עדיין A | נשאר `certain` | — |
| טקסט ריק | ‏"   " | ‏`unmatched`, בלי כתיבה | — |
| ‏eval | 3 כינויים `certain` עם ברקוד, בשמות מובחנים | ‏JSON עם samples 3 ו-precision. ה-DB לא השתנה | — |
| ‏parse_pack | ‏`"1.5ל"`, ‏`"750 מל"`, ‏`"80ג"`, ‏`"1 קג"`, ‏`"6 יח"`, ‏`"שוקולד"` | ‏(1.5, l), ‏(750, ml), ‏(80, g), ‏(1, kg), ‏(6, unit), ‏(None, None) | — |

</intent-contract>

## Code Map

- `backend/app/modules/matching/service.py` -- `match` (4.1: מסלול ברקוד, ‏`unmatched`), ‏`MatchResult`, ‏`MatchContext`, ‏`_log`. כאן נוספים מסלול הטקסט, ‏`Candidate`, ‏`parse_pack` ו-`score_candidates` (טהורה, לשימוש ה-eval).
- `backend/app/modules/matching/{models,repository}.py` -- היום ריקים. כאן נכנסים `MatchCandidate` והכתיבה/מחיקה.
- `backend/app/modules/catalog/{repository,service}.py` -- `upsert_certain_alias`, ‏`_certain_on_conflict`, ‏`clean_alias_text` ו-`valid_barcode` (4.1). מוסיפים כאן `upsert_alias` כללי, ‏`propose_product`, ‏`product_candidates(alias_norm, limit)` (trigram) ו-`alias_by_key`.
- `backend/app/modules/catalog/models.py:139` -- `Product`: ‏`pack_size`, ‏`pack_unit`, ‏`status` (`PRODUCT_STATUSES`) ואינדקס gin_trgm על `name_norm`.
- `backend/app/modules/pricing/service.py:194` -- `current_prices`. מוסיפים `median_prices(session, product_ids) -> dict[UUID, int]` מתוך ה-MV.
- `backend/app/core/config.py` -- הספים, עם `model_validator`.
- `backend/scripts/store_locations.py` -- הדפוס לסקריפט CLI שמסרב לרוץ בלי DB או ב-prod.
- `backend/migrations/versions/0011_product_aliases.py` -- המיגרציה האחרונה. החדשה היא `0012`.

## Tasks & Acceptance

**Execution:**
- `backend/app/core/config.py` -- ספי ההתאמה.
- `backend/app/modules/catalog/{repository,service}.py` -- `product_candidates`, ‏`propose_product`, ‏`upsert_alias` ו-`alias_by_key`.
- `backend/app/modules/pricing/service.py` -- `median_prices`.
- `backend/app/modules/matching/{models,repository,service}.py` + `backend/migrations/versions/0012_match_candidates.py` -- המסלול, הניקוד והמועמדים.
- `backend/scripts/eval_matching.py` -- SM-1.
- `backend/tests/unit/test_matching_text.py` -- ‏`parse_pack`, הניקוד עם תכונות חסרות, וההחלטה לפי ספים.
- `backend/tests/integration/test_matching_text.py` -- כל שורות המטריצה מול Postgres.
- `backend/tests/integration/*.py` -- הוספת `match_candidates` לכל TRUNCATE של `product_aliases`.

**Acceptance Criteria:**
- Given כינוי בלי ברקוד, when קוראים ל-`match`, then מוחזרים מועמדים מדורגים לפי ציון, וההתאמה `certain` מעל הסף, `uncertain` מתחתיו, או הצעה למוצר חדש כשאין מועמד.
- Given מאגר עם כינויים `certain` שיש להם ברקוד, when מריצים את `eval_matching`, then מתקבל precision של ההתאמות ה-`certain` לפי טקסט בלבד, כלומר SM-1 ניתן למדידה.

## Spec Change Log

## Review Triage Log

### 2026-11-09 — Review pass
- verdicts: 32 findings — high 0, medium 6, low 22, false 4, maybe-false 0
- findings:
  - Intent Alignment:
    - `false` `reject` ‏(1) הקליטה לא משתמשת במסלול הטקסט — זה בדיוק Story 3.6, שמגיעה עכשיו (sprint-status).
    - `false` `reject` ‏(2) המועמדים וההצעות לא חשופים לאף אחד — כלי הניהול הוא 4.5, ומסך האישור הוא Epic 6.
    - `medium` `patch` ‏(3) מדידת SM-1 מנופחת, כי הדגימה דולפת את התשובה — דגימה עם שם זהה לשם המוצר מדולגת, ונוספה טבלת ספים.
    - `low` `reject` ‏(4) אין מותג ואין סינון קטגוריה, והמשקלים מנורמלים — אין מותגים במוצרים. ‏Design Notes מסבירים את הנרמול.
    - `false` `reject` ‏(5) הפער מהמועמד השני מעבר ל-PRD — לפי הארכיטקטורה, שלב 3.
    - `low` `reject` ‏(6) נוסף `merged_into` — הכנה לא מזיקה ל-4.5.
  - Blind Hunter:
    - `medium` `patch` מוצר `proposed` הופך ל-certain — עכשיו לכל היותר `uncertain`.
    - `medium` `patch` ברקוד תקין הולך לאיבוד בהצעה — `propose_product(barcode)`, ובהתנגשות מוחזר המוצר הקיים.
    - `low` `defer` מוצר מוצע יתום בגלל מרוץ — נרשם ב-deferred.
    - `low` `reject` המצב `new_product_proposal` לא נשמר כמצב נפרד — אפשר לגזור אותו מ-`products.status=proposed`.
    - `medium` `patch` גודל רק בצד אחד מעדיף מוצר כללי — כשלכינוי יש גודל ולמוצר אין, size ו-unit נכנסים כ-0.
    - `low` `patch` פסיק אלפים — "1,000" הוא 1000.
    - `medium` `patch` ה-eval דולף — אותו תיקון.
    - `low` `patch` אין סריקת ספים — טבלה מ-0.50 עד 0.95.
    - `low` `patch` ה-downgrade נכשל כשיש נתונים — `RuntimeError` ברור.
    - `low` `patch` ‏FK בלי ondelete — `CASCADE`.
    - `low` `reject` ‏CHECK כתוב פעמיים — כמקובל במיגרציות.
    - `low` `patch` ‏set_config דולף לשאר הטרנזקציה — הערך הקודם מוחזר.
    - `low` `patch` חציון שמערבב מחיר ליחידה ולק"ג — רק `per='unit'`.
    - `false` `reject` ה-spec לא בתוך ה-diff — הוצא בכוונה.
  - Verification Gap:
    - `low` `patch` ה-guards של כינוי סופי לא נבדקים — נוספו שתי בדיקות.
    - `low` `patch` חציון עם סניף אחד — 3 סניפים, ו-promo ו-club לא נספרים.
    - `medium` `patch` (Other) מוצר `proposed` הופך ל-certain — אותו תיקון.
    - `low` `defer` (Other) מוצר מוצע יתום — אותו entry.
    - `low` `patch` (Other) ה-downgrade — אותו תיקון.
  - Edge Case Hunter:
    - `low` `patch` טקסט בלי trigrams יוצר הצעה בכל פעם — מוחזר `unmatched`. ‏`_proposed_before` משתמש שוב במוצר המוצע.
    - `low` `defer` שתי הצעות במקביל — אותו entry.
    - `low` `patch` ‏per בחציון — אותו תיקון.
    - `low` `patch` ‏set_config — אותו תיקון.
    - `low` `patch` פסיק אלפים — אותו תיקון.
    - `low` `patch` ה-downgrade — אותו תיקון.
    - `low` `patch` ‏path בלוג לכינוי final במסלול הברקוד — `memory`.

## Design Notes

**נרמול משקלים לפי מה שזמין:** במוצרים מ-3.4 אין מותג, ולפעמים אין גודל. בלי נרמול, הציון של כל מוצר היה נמוך באופן מלאכותי, וכמעט שום דבר לא היה `certain`. הנרמול שומר על משמעות הסף.

**הכיול:** אחרי שהקליטה האמיתית תרוץ, מריצים את `eval_matching`, ומעדכנים את `MATCH_CERTAIN_THRESHOLD` לערך הנמוך ביותר שנותן precision ≥ 0.9.

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy` -- expected: נקי.
- `cd backend && CARTWISE_REQUIRE_DOCKER=1 uv run pytest` -- expected: הכל עובר.

## Auto Run Result

Status: done

**סיכום:**
- **סדר המסלולים ב-`match`:** ברקוד, אחריו memory (כינוי `final` או `disputed`), ואחריו טקסט.
- **מסלול הטקסט:**
  - מועמדים לפי pg_trgm.
  - הציון: text, ‏size, ‏unit ו-price, עם משקלים מנורמלים לפי מה שזמין. גודל שמופיע רק בכינוי נכנס כ-0.
  - ההחלטה: `certain` (ספים ופער), ‏`uncertain` (שלושה מועמדים נשמרים ב-`match_candidates`), או הצעה למוצר `proposed`.
  - הצעה שומרת את הברקוד אם הוא תקין, ומשתמשת שוב בהצעה קודמת.
  - מוצר `proposed` לא יכול להיות `certain` לפי טקסט.
- **SM-1:** ‏`scripts/eval_matching.py` מודד precision ו-recall@3. דגימה שהטקסט שלה זהה לשם המוצר מדולגת, ויש טבלת ספים לכיול.

**קבצים:**
- `backend/app/modules/matching/{models,repository,service}.py`, `backend/migrations/versions/0012_match_candidates.py`.
- `backend/app/modules/catalog/{models,repository,service}.py`.
- `backend/app/modules/pricing/{repository,service}.py`.
- `backend/app/core/config.py`.
- `backend/scripts/eval_matching.py`.
- הבדיקות. בדיקות 4.1 עודכנו: ברקוד לא מוכר עובר עכשיו למסלול הטקסט.

**ממצאי הסקירה:** 32 ממצאים:
- **תוקנו:** 4 entries ברמת medium (proposed לא certain, ברקוד בהצעה, גודל בצד אחד, ה-eval), ו-12 ברמת low.
- **נדחה ל-deferred:** אחד.
- **נדחו לגמרי:** השאר.

**המלצה לסקירת המשך:** `true`. תוקנו 4 entries ברמת medium. הסיכון שלא אומת: הסף `MATCH_CERTAIN_THRESHOLD=0.85` לא כויל על נתונים אמיתיים.

**אימות:**
- ruff, format ו-mypy נקיים.
- `CARTWISE_REQUIRE_DOCKER=1 pytest`: 895 עברו.
- gitleaks על הקבצים שהשתנו: `no leaks found`.
