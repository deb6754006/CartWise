# CartWise: הנחיות לעבודה בפרויקט

## רשת מסוננת (NetFree): שגיאות תעודה

האינטרנט במחשב הפיתוח עובר סינון של NetFree, שמיירט חיבורי TLS.

- **מה זה אומר:** שגיאת תעודה, כמו `x509`, `certificate verify failed`, `SSL`, `self-signed certificate` או `unable to get local issuer certificate`, בפקודות כמו `docker pull`, `docker build`, `npm install`, `pip`, `uv sync` או `curl`, נגרמת **מהסינון, ולא מהקוד**.
- **אסור לעקוף או לבטל בדיקות SSL.** לא `--insecure`, לא `-k`, לא `strict-ssl=false`, לא `verify=False`, לא `NODE_TLS_REJECT_UNAUTHORIZED=0`, לא `--trusted-host`, לא `UV_INSECURE_HOST`, ולא registry לא מאובטח. גם לא להחליף לתעודה או למקור אחרים "כדי שזה יעבוד".
- **מה עושים:** עוצרים מיד, ומדווחים למשתמשת: איזו פקודה נכשלה, ואת שגיאת התעודה המדויקת. המשתמשת מטפלת בתעודה בעצמה. בלולאת build: עוצרים את הלולאה ומדווחים.
- **מה כבר קיים:** בבניית ה-image של ה-backend יש מנגנון אופציונלי שמקבל תעודת CA נוספת דרך משתנה הסביבה `CARTWISE_EXTRA_CA` (ראו `deploy/README.md`). משתמשים בו רק אם המשתמשת הגדירה אותו. לא מגדירים אותו ולא משנים אותו בלי אישור שלה.

## כללי הפרויקט

- **הריפו ציבורי:** אין סודות, מפתחות, קובצי `.env`, קבלות אמיתיות או נתוני משתמשים בריפו.
- **ענפים:** העבודה נעשית על הענף `dev`. לא עושים commit ל-`main`, ולא עושים `git push`.
- **ארכיטקטורה:** ההחלטות המחייבות נמצאות ב-`docs/planning-artifacts/architecture/architecture-CartWise-2026-10-26/ARCHITECTURE-SPINE.md`.
- **תקשורת:** בעברית.
