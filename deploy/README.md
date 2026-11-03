# deploy

סביבת dev מקומית: Postgres עם PostGIS, API ו-worker.

```bash
cd deploy
docker compose up -d --build
curl http://localhost:8000/v1/health   # {"status":"ok","db":"ok"}
docker compose down
```

## worker

השירות `worker` משתמש באותו image ובאותו קוד כמו ה-`api`, עם פקודה אחרת: `python -m app.worker.main`. הוא מריץ את המשימות המתוזמנות עם APScheduler. כרגע יש משימה אחת: `purge_deleted`, פעם ביום ב-03:00 UTC. היא מוחקת סופית חשבונות שנמחקו לפני יותר מ-29 יום, כך שכל חשבון נמחק סופית תוך 30 יום.

ה-worker מוגדר עם `restart: unless-stopped`, כך שהוא עולה מחדש אחרי קריסה, ועם `init: true`, כך ש-`docker compose stop` עוצר אותו מיד (SIGTERM), בלי לחכות ל-SIGKILL.

```bash
cd deploy
docker compose logs -f worker      # הלוגים של ה-worker
docker compose restart worker      # הפעלה מחדש אחרי שינוי קוד (אחרי build)
```

הרצה ידנית של המחיקה הסופית, בלי לחכות לתזמון:

```bash
docker compose exec worker python -c "from app.worker.jobs import purge_deleted; print(purge_deleted.run())"
```

המיגרציות רצות ב-`api`, ולכן ה-worker עולה אחריו.

## רשת עם סינון TLS (למשל NetFree)

אם בניית ה-image נכשלת בשגיאת תעודה (certificate) בשלב `uv sync`, צריך להגדיר את משתנה הסביבה `CARTWISE_EXTRA_CA`, עם הנתיב לקובץ התעודות **המלא** של הרשת. התעודה משמשת רק בזמן הבנייה, ולא נכנסת ל-image.

```bash
# bash
export CARTWISE_EXTRA_CA="C:/ProgramData/NetFree/CA/netfree-ca-bundle-curl.crt"
```

```powershell
# PowerShell
$env:CARTWISE_EXTRA_CA = "C:/ProgramData/NetFree/CA/netfree-ca-bundle-curl.crt"
```
