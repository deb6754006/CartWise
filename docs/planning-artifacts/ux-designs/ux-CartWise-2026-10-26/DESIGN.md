---
version: alpha
name: CartWise
description: אפליקציה חמה ומשפחתית להשוואת סל קניות. בסיס בהיר כמו נייר, סגול-לילך ותכלת, ודמות עגלה קטנה.
status: final
created: 2026-10-26
updated: 2026-10-26
colors:
  surface-base: '#FBFAF7'
  surface-raised: '#FFFFFF'
  surface-sunken: '#F3F1EC'
  ink-primary: '#374151'
  ink-secondary: '#78716C'
  ink-disabled: '#A8A29E'
  border-hairline: '#EFECE6'
  border-strong: '#E7E5E4'
  primary: '#7C3AED'
  primary-soft: '#8B5CF6'
  primary-tint: '#F5F3FF'
  on-primary: '#FFFFFF'
  sky: '#7DD3FC'
  sky-tint: '#F0F9FF'
  sky-ink: '#0369A1'
  sky-decor: '#E0F2FE'
  lilac-decor: '#DDD6FE'
  estimate-bg: '#FEF3C7'
  estimate-ink: '#92400E'
  reliability-green: '#16A34A'
  reliability-yellow: '#CA8A04'
  reliability-red: '#DC2626'
  error-ink: '#B91C1C'
  error-tint: '#FEF2F2'
  success-tint: '#F0FDF4'
typography:
  display:
    fontFamily: 'Rubik'
    fontSize: 24px
    fontWeight: 700
    lineHeight: 1.3
  title:
    fontFamily: 'Rubik'
    fontSize: 20px
    fontWeight: 700
    lineHeight: 1.35
  heading:
    fontFamily: 'Rubik'
    fontSize: 16px
    fontWeight: 600
    lineHeight: 1.4
  body:
    fontFamily: 'Rubik'
    fontSize: 15px
    fontWeight: 400
    lineHeight: 1.5
  meta:
    fontFamily: 'Rubik'
    fontSize: 13px
    fontWeight: 400
    lineHeight: 1.45
  price-lg:
    fontFamily: 'Rubik'
    fontSize: 20px
    fontWeight: 800
    lineHeight: 1.2
  price:
    fontFamily: 'Rubik'
    fontSize: 15px
    fontWeight: 600
    lineHeight: 1.3
rounded:
  sm: 8px
  md: 12px
  lg: 18px
  full: 9999px
spacing:
  '1': 4px
  '2': 8px
  '3': 12px
  '4': 16px
  '5': 24px
  '6': 32px
  margin-mobile: 16px
components:
  card:
    background: '{colors.surface-raised}'
    border: '1px solid {colors.border-hairline}'
    radius: '{rounded.lg}'
    padding: '{spacing.3} {spacing.4}'
  card-best:
    border: '2px solid {colors.primary}'
  badge-best:
    background: '{colors.primary}'
    color: '{colors.on-primary}'
    radius: '{rounded.full}'
    typography: '{typography.meta}'
  chip:
    background: '{colors.sky-tint}'
    color: '{colors.sky-ink}'
    radius: '{rounded.md}'
    height: 32px
  chip-quota:
    border: '1px dashed {colors.border-strong}'
    color: '{colors.ink-secondary}'
  button-primary:
    background: '{colors.primary}'
    color: '{colors.on-primary}'
    radius: '{rounded.md}'
    height: 48px
    typography: '{typography.heading}'
  button-secondary:
    background: '{colors.primary-tint}'
    color: '{colors.primary}'
    radius: '{rounded.md}'
    height: 48px
  estimate-tag:
    background: '{colors.estimate-bg}'
    color: '{colors.estimate-ink}'
    radius: '{rounded.sm}'
  segmented:
    background: '{colors.surface-sunken}'
    selected: '{colors.surface-raised}'
    radius: '{rounded.md}'
  tab-bar:
    background: '#FFFDF9'
    active: '{colors.primary}'
    inactive: '{colors.ink-secondary}'
    scan-fab: '{colors.primary}'
---

## Brand & Style

CartWise היא האפליקציה של המשפחה: חמה, ביתית ופשוטה. היא לא מרגישה כמו כלי פיננסי. היא מרגישה כמו חבר שעזר לך לחסוך.

**אווירה:** בסיס בהיר כמו נייר, סגול-לילך כצבע מוביל, ונגיעות תכלת. הצורות רכות, והטקסט פונה אל המשתמש אישית ("מצאתי לך...").

**הדמות:** דמות קטנה של עגלה עם פרצוף ושקית תכלת (כיוון D). היא מלווה רגעים של הצלחה, מצבים ריקים וה-Onboarding. בשום מקום היא לא מסתירה מידע. לדמות אין שם.

**חמים, אבל אמין.** המספרים, ובראשם המחירים, הכיסוי והאמינות, תמיד ברורים, מיושרים ובולטים. החום נמצא סביב המידע, לא במקומו.

## Colors

- **רקע נייר (`#FBFAF7`):** קנבס ראשי. לבן חמים, כדי שהמסך לא ירגיש קליני.
- **לבן (`#FFFFFF`):** כרטיסים וגיליונות תחתונים (sheets).
- **שקוע (`#F3F1EC`):** רקע של מתג מקטעים (segmented control) ושל שדות קלט.
- **דיו (`#374151`):** הטקסט הראשי. אפור כהה, לא שחור.
- **דיו משני (`#78716C`):** מידע משני, כמו זמן הגעה, כיסוי והפרש מחיר. אפור חם.
- **סגול (`#7C3AED`):** פעולה ראשית, תגית "הכי משתלם", מסגרת החנות המומלצת, וטאב פעיל. זה גם הגוון היחיד של סגול לטקסט על לבן, כי `#8B5CF6` לא עומד בניגודיות AA לטקסט קטן.
- **לילך (`#8B5CF6`, `#DDD6FE`, `#F5F3FF`):** דקורציה, הדמות, ורקע של הדגשות רכות.
- **תכלת (`#7DD3FC`, `#E0F2FE`, `#F0F9FF`, ובטקסט `#0369A1`):** תגיות (טווח, רשימה), עיגולים דקורטיביים, והשקית של הדמות.
- **צבעי אמינות (ירוק `#16A34A`, צהוב `#CA8A04`, אדום `#DC2626`):** משמשים **רק** לאייקון האמינות, ותמיד יחד עם צורה וטקסט. לא משתמשים בהם לשום דבר אחר, כדי שלא יתבלבלו עם המשמעות שלהם.
- **הערכה (רקע `#FEF3C7`, טקסט `#92400E`):** תגית "כולל הערכה". המטרה: שאי אפשר יהיה לטעות בין מחיר ידוע למחיר משוער.

**להימנע מ:**
- גרדיאנטים על משטחים
- רקע כהה (אין Dark mode ב-MVP)
- אדום לשגיאות רגילות. לשגיאות משתמשים ב-`error-ink` עם טקסט מסביר, בלי מילוי אדום גדול.

## Typography

**גופן אחד: Rubik.** יש לו תמיכה מלאה בעברית, והצורות המעוגלות שלו מתאימות לאווירה החמה.

| תפקיד | גודל ומשקל | שימוש |
|---|---|---|
| `display` | 24 / 700 | ברכה וכותרות של Onboarding |
| `title` | 20 / 700 | כותרת מסך |
| `heading` | 16 / 600 | שם חנות, כותרות כרטיסים |
| `body` | 15 / 400 | טקסט רגיל |
| `meta` | 13 / 400 | פרטים משניים |
| `price-lg` | 20 / 800 | מחיר סל |
| `price` | 15 / 600 | מחיר פריט |

**כללים:**
- **ספרות במחירים** מוצגות ברוחב קבוע (tabular), כדי שמחירים ברשימה יתיישרו.
- **סימן ₪** תמיד צמוד למספר: ₪412.30.
- **כל הגדלים מתאימים את עצמם** להגדרות הגופן של מערכת ההפעלה (Dynamic Type ו-Font scale), עד 200%.

## Layout & Spacing

- **סולם הריווח:** 4, 8, 12, 16, 24, 32 פיקסלים. השוליים בצדי המסך הם 16 פיקסלים.
- **עמודה אחת תמיד.**
- **כרטיסי חנויות:** הרווח בין כרטיסים הוא `{spacing.3}`. הריפוד בתוך הכרטיס הוא `{spacing.3}` למעלה ולמטה, ו-`{spacing.4}` בצדדים.
- **כיוון (RTL):** כל הפריסה מתחילה מימין. הכותרות מיושרות לימין, וכפתור "חזרה" נמצא בצד ימין ומצביע ימינה.
- **שורת מחיר:** שם החנות מימין, המחיר משמאל.
- **סרגל הניווט התחתון:** הטאב הראשון ("בית") נמצא בצד ימין.

## Elevation & Depth

שכבות מבוטאות בעיקר בגוון:
- **קנבס:** נייר.
- **כרטיס:** לבן עם קו דק.
- **גיליון תחתון:** לבן עם צל רך אחד (`0 -4px 16px rgba(55,65,81,.08)`).
- **כפתור הסריקה המרכזי:** הרכיב היחיד עם צל בולט, כדי שיבלוט כפעולה.

## Shapes

| רדיוס | שימוש |
|---|---|
| `{rounded.sm}` (8 פיקסלים) | תגיות קטנות ושדות |
| `{rounded.md}` (12 פיקסלים) | כפתורים, תגיות טווח, מתג מקטעים |
| `{rounded.lg}` (18 פיקסלים) | כרטיסים וגיליונות |
| `{rounded.full}` | תגית "הכי משתלם" וכפתור הסריקה |

**עיגולים דקורטיביים:** עיגולי תכלת ולילך גדולים מאחורי כותרות. מותר להשתמש בהם רק בראש מסך, ובאחד בכל מסך לכל היותר.

## Components

- **כרטיס חנות:**
  - **שורה ראשונה:** שם הרשת והסניף מימין, מחיר הסל (`price-lg`) משמאל.
  - **שורת מידע:** ההפרש מהזולה ביותר, הכיסוי, תגית הערכה (אם יש), זמן ההגעה ואייקון האמינות.
  - **החנות המומלצת:** מסגרת סגולה, תגית "הכי משתלם", ושורת חיסכון בסגול.
- **אייקון אמינות:** צורה, צבע ומילה יחד.
  - ● עיגול ירוק: "עדכני"
  - ▲ משולש צהוב: "בינוני"
  - ■ ריבוע אדום: "ישן"
  - גודל הצורה: 10 פיקסלים. אזור המגע: לפחות 44 פיקסלים.
- **תגית הערכה:** רקע צהבהב, והטקסט "כולל הערכה ₪X".
- **תגיות טווח:** תכלת, עם אמוג'י של אמצעי התחבורה (🚶 🚗 🚌) והדקות.
- **תגית מכסה:** מסגרת מקווקוות, למשל "נשארו 3 השוואות".
- **שורת פריט ברשימה:** שם המוצר, אילוץ המותג (`meta`) והכמות, עם כפתורי ‎+ ו-‎−‎. מחיקה בהחלקה.
- **כפתור ראשי:** סגול מלא, בגובה 48 פיקסלים. כפתור משני: רקע לילך בהיר וטקסט סגול.
- **סרגל ניווט תחתון:** חמישה טאבים: בית, רשימות, סריקה (כפתור עגול ומוגבה במרכז), הוצאות, פרופיל.
- **סיכה במפה:** עיגול לבן עם מחיר הסל. לחנות המומלצת: מילוי סגול וטקסט לבן.
- **הדמות:** SVG בשלושה גדלים: 24 (סמל), 56 (כותרת) ו-120 (מצב ריק או הצלחה). אין לה אנימציה ב-MVP.

## Do's and Don'ts

| כן | לא |
|---|---|
| מחירים גדולים, מיושרים ובולטים | להסתיר מחיר מאחורי לחיצה |
| אמינות = צורה + צבע + מילה | אמינות בצבע בלבד |
| הדמות ברגעי הצלחה ובמצבים ריקים | הדמות במסכי שגיאה של פרטיות, או מעל נתונים |
| סגול `#7C3AED` לטקסט ולכפתורים | `#8B5CF6` לטקסט קטן |
| עיגול דקורטיבי אחד בכל מסך | רקעים עמוסים, גרדיאנטים |
| ירוק, צהוב ואדום רק לאמינות | ירוק ל"חיסכון", אדום ל"יקר" |
