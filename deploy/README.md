# deploy

סביבת dev מקומית: Postgres עם PostGIS, ו-API.

```bash
cd deploy
docker compose up -d --build
curl http://localhost:8000/v1/health   # {"status":"ok","db":"ok"}
docker compose down
```

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
