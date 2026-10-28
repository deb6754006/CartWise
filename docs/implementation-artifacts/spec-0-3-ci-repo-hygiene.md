---
title: 'Story 0.3: CI והיגיינת ריפו'
type: 'chore'
created: '2026-10-28'
status: 'done'
baseline_revision: '9b36bdf839f4f17bca2aa855366e571e785f7a88'
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/docs/implementation-artifacts/epic-0-context.md'
  - '{project-root}/CLAUDE.md'
warnings: []
deferred:
  - summary: >-
      ה-validator של prod דוחה רק את ה-URL המדויק של localhost בסביבת dev, ולא כל URL עם פרטי הכניסה cartwise:cartwise.
    evidence: |-
      maybe-false. כדי להכריע: להחליט אם להקשיח את ה-validator ב-config.py, כך שידחה כל URL עם cartwise:cartwise@ כש-ENV=prod. זה שינוי ב-backend, מחוץ להיקף של Story 0.3.
    location: >-
      backend/app/core/config.py
    severity: low (unverified)
---

<intent-contract>

## Intent

**Problem:** אין בדיקות אוטומטיות על שינויים. הריפו ציבורי, ואין שום מנגנון שעוצר סוד לפני שהוא נכנס. גם אין קבצי repo-level שמגדירים מה לא נכנס ל-git ובאיזה פורמט שורות.

**Approach:** workflow של GitHub Actions עם ארבעה jobs: backend, mobile, בדיקה שה-schema של ה-API מעודכן, ו-gitleaks. בנוסף, קבצי היגיינה ברמת הריפו: `.gitignore`, `.gitattributes`, `.env.example` ו-`README.md`.

## Boundaries & Constraints

**Always:**
- ה-CI רץ על כל `push` ועל כל `pull_request`, לכל הענפים. כל job נכשל כשאחת הבדיקות שלו נכשלת.
- הבדיקות ב-CI הן בדיוק הפקודות שכבר מוגדרות: backend מ-Story 0.1, mobile מ-Story 0.2.
- בדיקות ה-integration ב-CI רצות עם `CARTWISE_REQUIRE_DOCKER=1`, ולכן לא מדלגות.
- כל action מוצמד לגרסה עם תגית (למשל `@v4`). לא `@main`.
- gitleaks סורק את כל ההיסטוריה (`fetch-depth: 0`), ומכשיל את הריצה כשנמצא ממצא.
- סוף שורה LF לכל קובצי הטקסט (`.gitattributes`). קבצים בינאריים מסומנים כ-binary.

**Never:**
- אין secrets ב-workflow, חוץ מ-`GITHUB_TOKEN` המובנה. אין פריסה, אין בניית images ואין push ל-registry. כל אלה בפריסה, מאוחר יותר.
- לא מבטלים ולא עוקפים בדיקות TLS, לא ב-CI ולא מקומית (CLAUDE.md).
- לא מכניסים `.env`, תעודות, מפתחות או קבלות אמיתיות. `.env.example` מכיל רק שמות וערכי placeholder.
- לא משנים קוד של backend או mobile, חוץ מהתאמות שורה ש-renormalize מייצר.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| ריפו נקי | הרצת gitleaks על הריפו הנוכחי | 0 ממצאים | — |
| סוד שנכנס | קובץ בדיקה עם מפתח שנראה אמיתי (למשל `AKIA…` מלא) | gitleaks מדווח ממצא, ויוצא בקוד שונה מ-0 | ה-CI נכשל |
| ערכי dev מותרים | `cartwise:cartwise` ב-compose, וה-URL של dev ב-config | לא מדווחים, או מוחרגים במפורש ב-`.gitleaks.toml` עם הערה | — |
| schema לא מעודכן | שינוי ב-backend בלי `gen:api` | ה-job `api-schema` נכשל, ומציג את ה-diff | — |
| `.env` מקומי | `deploy/.env`, `backend/.env`, `mobile/.env`, `.env` בשורש | כולם מוחרגים (`git check-ignore` מצליח). `.env.example` לא מוחרג | — |
| קבלות אמיתיות | קובץ ב-`data/receipts-real/` | מוחרג | — |

</intent-contract>

## Code Map

- `backend/pyproject.toml` -- בדיקות backend: `uv sync`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy app` ו-`uv run pytest -q`. ב-integration יש `CARTWISE_REQUIRE_DOCKER` (Story 0.1). Python 3.13.
- `mobile/package.json` -- scripts: `lint`, `typecheck`, `test` ו-`gen:api`. ה-lock: `mobile/package-lock.json`. Node 24 מקומית.
- `mobile/scripts/gen-api.mjs` -- מייצר את `mobile/openapi.json` ואת `mobile/src/api/schema.ts`. דורש uv ו-backend. ה-output ב-LF.
- `backend/.gitignore`, `mobile/.gitignore`, `deploy/.gitignore` -- כבר קיימים. ה-root משלים אותם, ולא מחליף אותם.
- `deploy/docker-compose.yml` -- סיסמת dev `cartwise`. `backend/app/core/config.py` -- ה-URL של dev. שניהם ערכים לא סודיים, שעלולים להיתפס ב-gitleaks.
- `docs/implementation-artifacts/spec-0-1-backend-skeleton.md`, `spec-0-2-mobile-skeleton.md` -- deferred: בדיקה שה-schema מעודכן. אזהרות CRLF ב-git.
- `CLAUDE.md` -- כלל NetFree.

## Tasks & Acceptance

**Execution:**
- `.github/workflows/ci.yml` -- workflow בשם `ci`. `on: [push, pull_request]`. `permissions: contents: read`. `concurrency` לפי ref, עם ביטול ריצות קודמות. 4 jobs על `ubuntu-latest`:
  - `backend`: checkout, `astral-sh/setup-uv`, `uv python install 3.13` (או התקנה דרך setup-uv), ואחר כך ב-`backend/`: sync, ruff check, ruff format --check, mypy app, ו-pytest -q עם `CARTWISE_REQUIRE_DOCKER=1`. ל-Docker יש גישה ב-runner.
  - `mobile`: checkout, `actions/setup-node` (Node 24, cache npm לפי `mobile/package-lock.json`), ואחר כך ב-`mobile/`: `npm ci`, lint, typecheck, `npm test -- --ci`.
  - `api-schema`: setup-uv ו-setup-node, `uv sync` ב-backend, `npm ci` ב-mobile, `npm run gen:api`, ואז `git diff --exit-code -- mobile/openapi.json mobile/src/api/schema.ts`. אם יש diff, מודפסת הודעה ברורה.
  - `secrets`: checkout עם `fetch-depth: 0`, ו-gitleaks (`gitleaks/gitleaks-action@v2`, עם `GITHUB_TOKEN`).
- `.gitleaks.toml` -- `[extend] useDefault = true`, ו-allowlist מצומצם, עם הערה לכל פריט: ערכי ה-dev הלא סודיים (compose, ה-URL ב-`config.py`, והבדיקות של ה-validator), ו-`uv.lock` ו-`package-lock.json` (hashes של חבילות).
- `.gitignore` (שורש) -- `.env`, `.env.*`, `!.env.example`, `data/receipts-real/`, `*.pem`, `*.key`, `*.crt` (עם `!deploy/no-extra-ca.crt`), `.DS_Store`, `Thumbs.db`, `.idea/`, `.vscode/` (חוץ מ-extensions מומלצים, אם יש), ו-`_bmad/render/`.
- `.gitattributes` -- `* text=auto eol=lf`, ו-binary ל-`*.png`, `*.jpg`, `*.jpeg`, `*.gif`, `*.ico`, `*.ttf`, `*.otf`, `*.woff`, `*.woff2`, `*.jar` ו-`*.keystore`. אחר כך `git add --renormalize .`, והקבצים שהשתנו נכנסים ל-commit.
- `.env.example` (שורש) -- עם הערות בעברית: `DATABASE_URL`, `ENV`, `LOG_LEVEL` (backend), `EXPO_PUBLIC_API_URL` (mobile) ו-`CARTWISE_EXTRA_CA` (build מקומי בלבד, ריק כברירת מחדל). רק ערכי placeholder ו-dev.
- `README.md` (שורש) -- בעברית: מה הפרויקט, מבנה התיקיות, דרישות (Docker, uv, Node 24), הקמה מהירה (`deploy` ← backend ← mobile), הרצת בדיקות, ה-CI, כלל הריפו הציבורי, ורשת מסוננת (הפניה ל-`deploy/README.md` ול-CLAUDE.md). קישורים ל-`docs/`.

**Acceptance Criteria:**
- Given ה-workflow, when בודקים את ה-YAML שלו (פרסור, ואם זמין, actionlint), then הוא תקין, ומכיל את 4 ה-jobs עם הפקודות שהוגדרו.
- Given הריפו הנוכחי, when מריצים gitleaks מקומית על כל ההיסטוריה, then אין ממצאים. Given קובץ זמני עם סוד מזויף, then gitleaks נכשל. הקובץ נמחק לפני ה-commit.
- Given קבצי `.env` בכל מיקום, then `git check-ignore` מחריג את כולם, ו-`.env.example` לא מוחרג.
- Given `npm run gen:api` מקומית על הקוד הנוכחי, then `git diff --exit-code` על שני קובצי ה-schema עובר.

## Spec Change Log

## Review Triage Log

## Design Notes

- **הרצת gitleaks מקומית:** אם gitleaks לא מותקן, מריצים אותו דרך Docker (`zricethezav/gitleaks`, עם תגית גרסה), כ-mount של הריפו. בשגיאת תעודה ב-pull: עוצרים לפי CLAUDE.md.
- **CI על GitHub:** ה-CI עצמו לא ירוץ עד שהמשתמשת תעשה push. האימות מקומי: YAML תקין, והפקודות של כל job רצות מקומית בהצלחה.

## Verification

**Commands:**
- `python -c "import yaml;d=yaml.safe_load(open('.github/workflows/ci.yml'));assert set(d['jobs'])=={'backend','mobile','api-schema','secrets'}"` -- expected: עובר
- `docker run --rm -v "$PWD:/repo" zricethezav/gitleaks:<pinned> git /repo --config /repo/.gitleaks.toml -v` (או `detect --source /repo`) -- expected: `no leaks found`
- `for f in .env deploy/.env backend/.env mobile/.env; do git check-ignore -q $f || echo MISSING $f; done; git check-ignore -q .env.example && echo BAD` -- expected: אין output
- `cd mobile && npm run gen:api && cd .. && git diff --exit-code -- mobile/openapi.json mobile/src/api/schema.ts` -- expected: exit 0
- `cd backend && CARTWISE_REQUIRE_DOCKER=1 uv run pytest -q` ו-`cd mobile && npm run lint && npm run typecheck && npm test -- --ci` -- expected: עוברים, כמו ב-CI

### 2026-10-28 — Review pass
- verdicts: 31 findings — high 0, medium 8, low 15, false 5, maybe-false 3
- findings:
  - Verification Gap:
    - `false` `reject` אין פערי אימות. קובצי קונפיגורציה ותיעוד שאין להם בדיקה דטרמיניסטית — מאושר: אומתו מקומית (YAML, actionlint, gitleaks ו-check-ignore).
    - `medium` `patch` (other) ה-README טוען שה-CI סורק את כל ההיסטוריה, אבל gitleaks-action סורק רק את טווח ה-push — נוסף scan שבועי ו-workflow_dispatch, וה-README תוקן.
  - Intent Alignment:
    - `false` `reject` ה-CI לא הורץ ב-GitHub — אי אפשר בלי push, וזה מחוץ לשליטה של ה-Story. האימות נעשה מקומית לפי ה-spec.
    - `low` `patch` "build files" לא מכוסים ב-.gitignore של השורש — נוספו `build/`, `dist/` ו-`*.egg-info/`.
    - `false` `reject` ה-README לא נבדק מ-clone נקי — הפקודות זהות לאלה שאומתו ב-0.1 וב-0.2. ה-patch מתקן את שגיאות הרצף.
    - `false` `reject` עבודה מעבר ל-AC (api-schema, gitattributes) — הגיעה מה-deferred של 0.1 ו-0.2, וכתובה במפורש ב-spec.
    - `false` `reject` renormalize לא שינה אף קובץ — אומת: ה-index כבר היה LF.
    - `medium` `patch` ה-allowlist רחב מדי (קובצי lock שלמים) — קבוצת `.gitleaks.toml`.
  - Blind Hunter:
    - `medium` `patch` התנגשות פורטים ב-quick start — שתי חלופות (A ו-B).
    - `low` `patch` `cd` שבור בבלוקים של הבדיקות — כל בלוק מתחיל מהשורש.
    - `medium` `patch` `.env.example` רומז ש-`.env` בשורש נקרא — נוספו הערות שמפרטות איפה כל משתנה מוגדר.
    - `medium` `patch` חסרות הרשאות PR ל-secrets job — `pull-requests: write`.
    - `low` `patch` ריצה כפולה על ענפי PR — push רק ל-main ול-dev, ו-concurrency לפי head_ref.
    - `low` `patch` אין timeout-minutes — נוסף לכל job.
    - `low` `patch` בדיקת api-schema מפספסת קבצים לא במעקב — `git status --porcelain`.
    - `low` `patch` חסרים ב-.gitattributes סוגים בינאריים ו-bat/cmd — נוספו.
    - `medium` `patch` `.claude/settings.local.json` ו-`.claude/*.lock`, וקובצי חתימה מחוץ ל-mobile, לא מוחרגים — נוספו לשורש.
    - `medium` `patch` ב-.gitleaks.toml: צורה deprecated, ו-regex גלובלי בלי עוגן — קבוצת `.gitleaks.toml`.
    - `low` `reject` בדיקת הסוד המזויף לא אוטומטית — אומתה ידנית, ונבדקת שוב אחרי ה-patch. אוטומציה דורשת תשתית נוספת.
    - `low` `patch` ב-README חסרים gen:api אחרי uv sync, ואמולטור ומכשיר — נוספו.
  - Edge Case Hunter:
    - `maybe-false` `patch` regexTarget ברירת מחדל = secret — קבוצת `.gitleaks.toml` (regexTarget מפורש).
    - `medium` `patch` regex בלי עוגן מאפשר `cartwiseProd!23` — קבוצת `.gitleaks.toml`.
    - `medium` `patch` קובצי lock שלמים לא נסרקים — קבוצת `.gitleaks.toml`.
    - `low` `patch` היקף הסריקה של gitleaks בהיסטוריה — קבוצת ה-scan השבועי.
    - `maybe-false` `patch` הרשאות PR — קבוצת `pull-requests: write`.
    - `low` `patch` git diff מפספס קבצים לא במעקב — קבוצת `git status`.
    - `low` `patch` `cd` בבלוק הבדיקות — קבוצת ה-README.
    - `low` `patch` פורט 8000 — קבוצת ה-README.
    - `low` `patch` `.env` בשורש לא נקרא — קבוצת `.env.example`.
    - `maybe-false` `defer` ה-validator של prod דוחה רק את ה-URL המדויק של localhost — ההערה ב-.gitleaks.toml תוקנה. הקשחת ה-validator היא שינוי ב-backend ונדחתה.

## Auto Run Result

Status: done

**סיכום:**
- **CI:** workflow של GitHub Actions עם 4 jobs: backend, mobile, api-schema ו-secrets (gitleaks).
  - טריגרים: push ל-main ול-dev, PR, סריקה שבועית והרצה ידנית.
  - timeouts, הרשאות מינימליות, ו-actions מוצמדים לתגיות.
- **היגיינת ריפו:** `.gitignore` ו-`.gitattributes` בשורש (LF, בינאריים, bat ו-cmd), `.env.example` עם הסבר איפה כל משתנה מוגדר, ו-README בעברית.
- **`.gitleaks.toml`:** allowlists מצומצמים לנתיבים מסוימים, עם regexes מעוגנים.

**קבצים:** `.github/workflows/ci.yml`, `.gitleaks.toml`, `.gitignore`, `.gitattributes`, `.env.example`, `README.md`.

**ממצאי הסקירה:** 31 ממצאים. 10 קבוצות patch הוחלו (8 medium, והשאר low). פריט אחד נדחה ל-deferred: הקשחת ה-validator של prod. השאר נדחו או נמצאו false, והנימוק של כל אחד רשום ב-Review Triage Log.

**המלצה לסקירת המשך:** `true`. הוחלו כמה patches בדרגת medium: `.gitleaks.toml` נכתב מחדש, ושונו הטריגרים וההרשאות ב-CI. אלה לא אומתו בריצה אמיתית ב-GitHub. ה-allowlists ברמת השורה הם מניעתיים, ולא נבדקו מול ממצא אמיתי.

**אימות (מקומי):**
- YAML תקין, ו-actionlint 1.7.7 עבר.
- gitleaks v8.28.0 על כל ההיסטוריה: `no leaks found`. סוד AKIA מזויף נתפס.
- `git check-ignore` מחריג את כל קובצי ה-`.env` ולא את `.env.example`. `git ls-files -ci` ריק.
- `gen:api`: ה-schema מעודכן.
- backend: 45 בדיקות עברו (`CARTWISE_REQUIRE_DOCKER=1`). mobile: lint, typecheck ו-63 בדיקות עברו.

**סיכונים שנשארו:**
- ה-CI לא רץ עדיין ב-GitHub, כי נדרש push.
- gitleaks-action צריך license רק אם הריפו יעבור ל-organization.
