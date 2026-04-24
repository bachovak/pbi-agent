# DAX Best Practices Reference

Authoritative anti-patterns and correct alternatives, compiled from Microsoft Learn, SQLBI, Tabular Editor Best Practice Analyzer, and DAX Patterns. Used as the source for the condensed rules injected into the System B system prompt in `dax_agent.py` and `app.py`.

---

## 1. Type and Casting Mistakes

### 1.1 Do not use type-cast functions as measure output wrappers
**Anti-pattern:**
```dax
Revenue Int = INT([Revenue])
Label = TEXT([Sales], "#,0")
Rate = FLOAT([Ratio])
```
**Correct pattern:** Omit the cast entirely. Power BI infers the data type of a measure from the expression that produces it. Wrapping a result in `INT()`, `TEXT()`, or `FLOAT()` is at best redundant and at worst silently changes semantics (`INT()` truncates toward negative infinity, not rounds).
```dax
Revenue Int = [Revenue]   -- set the Format String property separately
```
*Source: Power BI data model behaviour / internal testing*

---

### 1.2 Do not use INT() to force a whole-number result from count functions
**Anti-pattern:**
```dax
Distinct Products = INT(DISTINCTCOUNT('Product'[ProductKey]))
Row Count = INT(COUNTROWS(Sales))
```
**Correct pattern:**
```dax
Distinct Products = DISTINCTCOUNT('Product'[ProductKey])
Row Count = COUNTROWS(Sales)
```
`DISTINCTCOUNT`, `COUNT`, `COUNTROWS`, and `COUNTBLANK` all return `Int64` natively.
*Source: internal testing*

---

### 1.3 Use correct Power BI / Tabular data-type names
**Anti-pattern:** Integer, Float, Text, Date, Bool
**Correct pattern:** `Int64`, `Double`, `String`, `DateTime`, `Boolean`, `Decimal`, `Numeric`, `Variant`

These are the enum values used by the Tabular Object Model (TOM) and by tools such as Tabular Editor.
*Source: internal testing / TOM documentation*

---

### 1.4 Use DIVIDE for safe division; do not use the / operator when the denominator can be zero
**Anti-pattern:**
```dax
Profit Margin = IF(ISERROR([Profit] / [Sales]), BLANK(), [Profit] / [Sales])
Profit Margin = IFERROR([Profit] / [Sales], BLANK())
```
**Correct pattern:**
```dax
Profit Margin = DIVIDE([Profit], [Sales])
```
Exception: when the denominator is a literal constant that can never be zero (e.g. `/ 100`), the `/` operator is preferable — `DIVIDE` always tests the denominator, which is wasted work for a guaranteed non-zero constant.
*Source: [Microsoft Learn — DIVIDE function vs divide operator](https://learn.microsoft.com/en-us/dax/best-practices/dax-divide-function-operator)*

---

### 1.5 Do not use FORMAT() to display numbers — set the Format String property instead
**Anti-pattern:**
```dax
Revenue Display = FORMAT([Revenue], "#,0")
```
**Correct pattern:** Return the numeric measure and set the **Format String** property on the measure object in the model. Use `FORMAT()` only when a string result is genuinely required (e.g. a dynamic label that concatenates text).

`FORMAT()` always returns `String`, which prevents further numeric aggregation and breaks axis scaling in visuals.
*Source: [Microsoft Learn — FORMAT function](https://learn.microsoft.com/en-us/dax/format-function-dax)*

---

## 2. Aggregation Mistakes

### 2.1 Do not add aggregation expressions inside SUMMARIZE
**Anti-pattern:**
```dax
SUMMARIZE(
    Store,
    Store[Country],
    "Stores", COUNTROWS(Store)
)
```
**Correct pattern:**
```dax
ADDCOLUMNS(
    SUMMARIZE(Store, Store[Country]),
    "Stores", CALCULATE(COUNTROWS(Store))
)
```
Aggregation expressions inside `SUMMARIZE` run in an inconsistently documented filter context and have produced wrong results in past engine versions.
*Source: [SQLBI — Best practices using SUMMARIZE and ADDCOLUMNS](https://www.sqlbi.com/articles/best-practices-using-summarize-and-addcolumns/)*

---

### 2.2 Always wrap aggregations in ADDCOLUMNS with CALCULATE
**Anti-pattern:**
```dax
ADDCOLUMNS(
    SUMMARIZE(Store, Store[Country]),
    "Stores", COUNTROWS(Store)   -- returns total, not per-country
)
```
**Correct pattern:**
```dax
ADDCOLUMNS(
    SUMMARIZE(Store, Store[Country]),
    "Stores", CALCULATE(COUNTROWS(Store))
)
```
Without `CALCULATE`, the aggregation ignores the row context grouping and scans the full table.
*Source: [SQLBI — Best practices using SUMMARIZE and ADDCOLUMNS](https://www.sqlbi.com/articles/best-practices-using-summarize-and-addcolumns/)*

---

### 2.3 Do not convert BLANK to zero unless explicitly requested
**Anti-pattern:**
```dax
Sales (No Blank) = IF(ISBLANK([Sales]), 0, [Sales])
Profit Margin = DIVIDE([Profit], [Sales], 0)
```
**Correct pattern:**
```dax
Sales = [Sales]
Profit Margin = DIVIDE([Profit], [Sales])
```
Forcing zero turns sparse calculations dense, causing Power BI to retrieve and render every group even those with no data.
*Source: [Microsoft Learn — Avoid converting BLANKs to values](https://learn.microsoft.com/en-us/dax/best-practices/dax-avoid-converting-blank)*

---

### 2.4 Extract repeated sub-expressions into VAR
**Anti-pattern:**
```dax
Sales YoY % =
DIVIDE(
    [Sales] - CALCULATE([Sales], PARALLELPERIOD('Date'[Date], -12, MONTH)),
    CALCULATE([Sales], PARALLELPERIOD('Date'[Date], -12, MONTH))
)
```
**Correct pattern:**
```dax
Sales YoY % =
VAR SalesPriorYear =
    CALCULATE([Sales], PARALLELPERIOD('Date'[Date], -12, MONTH))
RETURN
    DIVIDE([Sales] - SalesPriorYear, SalesPriorYear)
```
Each repeated expression is evaluated independently, roughly doubling query time.
*Source: [Microsoft Learn — Use variables to improve your DAX formulas](https://learn.microsoft.com/en-us/dax/best-practices/dax-variables)*

---

## 3. CALCULATE and Filter Context Mistakes

### 3.1 Use Boolean filter arguments in CALCULATE; avoid FILTER for simple column comparisons
**Anti-pattern:**
```dax
Red Sales = CALCULATE([Sales], FILTER('Product', 'Product'[Color] = "Red"))
```
**Correct pattern:**
```dax
Red Sales = CALCULATE([Sales], 'Product'[Color] = "Red")
```
Boolean filter arguments exploit the in-memory columnar store directly; `FILTER()` materialises a full table scan first. Use `FILTER()` only when the condition references a measure, spans multiple tables, or requires `OR`/`||`.
*Source: [Microsoft Learn — Avoid using FILTER as a filter argument](https://learn.microsoft.com/en-us/dax/best-practices/dax-avoid-avoid-filter-as-filter-argument)*

---

### 3.2 When FILTER is necessary, scope it to the smallest possible table
**Anti-pattern:**
```dax
Sales for Profitable Months =
CALCULATE([Sales], FILTER('Date', [Profit] > 0))
```
**Correct pattern:**
```dax
Sales for Profitable Months =
CALCULATE(
    [Sales],
    FILTER(VALUES('Date'[Month]), [Profit] > 0)
)
```
`VALUES('Date'[Month])` returns only the distinct months visible in context, far smaller than the full `Date` table.
*Source: [Microsoft Learn — Avoid using FILTER as a filter argument](https://learn.microsoft.com/en-us/dax/best-practices/dax-avoid-avoid-filter-as-filter-argument)*

---

### 3.3 Use SELECTEDVALUE instead of IF(HASONEVALUE(...), VALUES(...))
**Anti-pattern:**
```dax
Australian Sales Tax =
IF(
    HASONEVALUE(Customer[Country-Region]),
    IF(VALUES(Customer[Country-Region]) = "Australia", [Sales] * 0.10)
)
```
**Correct pattern:**
```dax
Australian Sales Tax =
IF(SELECTEDVALUE(Customer[Country-Region]) = "Australia", [Sales] * 0.10)
```
*Source: [Microsoft Learn — Use SELECTEDVALUE instead of VALUES](https://learn.microsoft.com/en-us/dax/best-practices/dax-selectedvalue)*

---

### 3.4 Do not wrap SELECTEDVALUE in a redundant HASONEVALUE guard
**Anti-pattern:**
```dax
Color Label =
IF(HASONEVALUE('Product'[Color]), SELECTEDVALUE('Product'[Color]), "All")
```
**Correct pattern:**
```dax
Color Label = SELECTEDVALUE('Product'[Color], "All")
```
`SELECTEDVALUE` already performs the `HASONEVALUE` check internally.
*Source: [XXL BI — Power BI Anti-patterns #2](https://xxlbi.com/blog/power-bi-antipatterns-2/)*

---

### 3.5 Note: SELECTEDVALUE alternate result fires on zero rows too, not just multi-selection
When a slicer matches nothing, the filter context contains zero rows and `SELECTEDVALUE` returns its alternate result. Design the alternate accordingly — do not assume it only fires on multi-select.
*Source: [SQLBI — Using the SELECTEDVALUE function in DAX](https://www.sqlbi.com/articles/using-the-selectedvalue-function-in-dax/)*

---

### 3.6 Do not use IFERROR or ISERROR to mask division errors
**Anti-pattern:**
```dax
Profit Margin = IFERROR([Profit] / [Sales], BLANK())
```
**Correct pattern:**
```dax
Profit Margin = DIVIDE([Profit], [Sales])
```
`IFERROR`/`ISERROR` force row-by-row evaluation and increase storage engine scans. They also mask bugs that should be fixed at the data or model level.
*Source: [Microsoft Learn — Appropriate use of error functions](https://learn.microsoft.com/en-us/dax/best-practices/dax-error-functions)*

---

### 3.7 Do not compare VALUES() directly to a scalar
**Anti-pattern:**
```dax
Is Australia = IF(VALUES(Customer[Country]) = "Australia", 1, 0)
```
**Correct pattern:**
```dax
Is Australia = IF(SELECTEDVALUE(Customer[Country]) = "Australia", 1, 0)
```
When more than one value is in context, `VALUES()` returns a multi-row table and `=` raises an error.
*Source: [Microsoft Learn — Use SELECTEDVALUE instead of VALUES](https://learn.microsoft.com/en-us/dax/best-practices/dax-selectedvalue)*

---

## 4. Time Intelligence Mistakes

### 4.1 Time intelligence requires a dedicated marked Date table
Do not call `TOTALYTD`, `SAMEPERIODLASTYEAR`, `DATESYTD`, etc. against a date column on a fact table, or against a date table that has not been marked as a Date table. The table must be contiguous (no gaps, Jan 1 through Dec 31 for every required year).
*Source: [Microsoft Learn — Time intelligence functions](https://learn.microsoft.com/en-us/dax/time-intelligence-functions-dax)*

---

### 4.2 Do not nest time intelligence functions
**Anti-pattern:**
```dax
YTD vs LY = TOTALYTD(CALCULATE([Sales], SAMEPERIODLASTYEAR('Date'[Date])), 'Date'[Date])
```
**Correct pattern:** Calculate each period in a separate VAR, then combine.
```dax
VAR SalesLY = CALCULATE([Sales], SAMEPERIODLASTYEAR('Date'[Date]))
VAR SalesYTD = CALCULATE([Sales], DATESYTD('Date'[Date]))
RETURN DIVIDE(SalesYTD, SalesLY) - 1
```
*Source: Towards Data Science — Advanced Time Intelligence in DAX*

---

### 4.3 Use built-in time intelligence functions instead of hand-crafted FILTER date ranges
**Anti-pattern:**
```dax
YTD Sales = CALCULATE([Sales], FILTER('Date', 'Date'[Date] <= MAX('Date'[Date]) && YEAR('Date'[Date]) = YEAR(MAX('Date'[Date]))))
```
**Correct pattern:**
```dax
YTD Sales = CALCULATE([Sales], DATESYTD('Date'[Date]))
```
*Source: [DAX Patterns — Standard time-related calculations](https://www.daxpatterns.com/standard-time-related-calculations/)*

---

### 4.4 DATESYTD fiscal year-end must be a string literal
**Anti-pattern:**
```dax
Fiscal YTD = CALCULATE([Sales], DATESYTD('Date'[Date], [FiscalYearEnd]))
```
**Correct pattern:**
```dax
Fiscal YTD = CALCULATE([Sales], DATESYTD('Date'[Date], "6/30"))
```
The `year_end_date` argument must be a constant literal string; a measure reference causes an error.
*Source: [Microsoft Learn — DATESYTD](https://learn.microsoft.com/en-us/dax/datesytd-function-dax)*

---

## 5. Performance Anti-Patterns

### 5.1 Use VAR instead of EARLIER
**Anti-pattern:**
```dax
Subcategory Rank =
COUNTROWS(
    FILTER(Subcategory, EARLIER(Subcategory[Sales]) < Subcategory[Sales])
) + 1
```
**Correct pattern:**
```dax
Subcategory Rank =
VAR CurrentSales = Subcategory[Sales]
RETURN
    COUNTROWS(FILTER(Subcategory, CurrentSales < Subcategory[Sales])) + 1
```
`EARLIER` was necessary before `VAR` existed; `VAR` is clearer and easier to optimise.
*Source: [Microsoft Learn — Use variables to improve your DAX formulas](https://learn.microsoft.com/en-us/dax/best-practices/dax-variables)*

---

### 5.2 Use CALCULATE(COUNTROWS(...), filter) not COUNTROWS(FILTER(...))
**Anti-pattern:**
```dax
High Value Orders = COUNTROWS(FILTER(Orders, Orders[Amount] > 10000))
```
**Correct pattern:**
```dax
High Value Orders = CALCULATE(COUNTROWS(Orders), Orders[Amount] > 10000)
```
`FILTER` returns a full intermediate table before `COUNTROWS` counts it; `CALCULATE` with a Boolean filter pushes the predicate directly to the storage engine.
*Source: [Microsoft Learn — Avoid using FILTER as a filter argument](https://learn.microsoft.com/en-us/dax/best-practices/dax-avoid-avoid-filter-as-filter-argument)*

---

### 5.3 Use MAX() not LASTDATE() as the SELECTEDVALUE alternate result
**Anti-pattern:**
```dax
SelectedDate = SELECTEDVALUE('Date'[Date], LASTDATE('Date'[Date]))
```
**Correct pattern:**
```dax
SelectedDate = SELECTEDVALUE('Date'[Date], MAX('Date'[Date]))
```
`LASTDATE` returns a one-row table that is implicitly coerced to a scalar; `MAX` is a direct scalar function.
*Source: [XXL BI — Power BI Anti-patterns #2](https://xxlbi.com/blog/power-bi-antipatterns-2/)*

---

## 6. Syntax Mistakes

### 6.1 Always fully qualify column references
**Anti-pattern:**
```dax
Revenue = SUM([SalesAmount])
```
**Correct pattern:**
```dax
Revenue = SUM(Sales[SalesAmount])
```
Bare `[Column]` references are ambiguous when two tables share a column name.
*Source: [Tabular Editor — Best Practice Analyzer](https://docs.tabulareditor.com/te2/Best-Practice-Analyzer.html)*

---

### 6.2 Use VAR/RETURN for multi-step logic; never chain expressions with semicolons
**Anti-pattern:**
```dax
Sales Calc = [Sales] * 1.1; IF([Sales] > 0, [Sales])   -- invalid
```
**Correct pattern:**
```dax
Sales Calc =
VAR GrossSales = [Sales] * 1.1
RETURN IF(GrossSales > 0, GrossSales)
```
*Source: [Microsoft Learn — VAR](https://learn.microsoft.com/en-us/dax/var-dax)*

---

### 6.3 DAX UDF syntax uses the => arrow operator, not RETURN at the top level
**Correct structure:**
```dax
DEFINE
  FUNCTION MyLib.CalcTax([amount] AS Double, [rate] AS Double)
  RETURNS Double
  => [amount] * [rate]
```
The `DEFINE` block is only valid in DAX Query View, not in measures.
*Source: [Microsoft Learn — DAX user-defined functions](https://learn.microsoft.com/en-us/power-bi/transform-model/desktop-user-defined-functions-overview)*

---

## Quick Reference

| # | Anti-pattern | Correct alternative | Source |
|---|---|---|---|
| 1.1 | `INT([Revenue])`, `TEXT([x])` as wrappers | Remove cast; set Format String | Internal |
| 1.2 | `INT(COUNTROWS(...))` | `COUNTROWS(...)` directly | Internal |
| 1.3 | Type names: Integer, Float, Text, Bool | `Int64`, `Double`, `String`, `Boolean` | TOM docs |
| 1.4 | `[A] / [B]` or `IFERROR([A]/[B], ...)` | `DIVIDE([A], [B])` | [MS Learn](https://learn.microsoft.com/en-us/dax/best-practices/dax-divide-function-operator) |
| 1.5 | `FORMAT([Revenue], "#,0")` as measure | Numeric measure + Format String property | [MS Learn](https://learn.microsoft.com/en-us/dax/format-function-dax) |
| 2.1 | Aggregation inside `SUMMARIZE(...)` | `ADDCOLUMNS(SUMMARIZE(...), "col", CALCULATE(...))` | [SQLBI](https://www.sqlbi.com/articles/best-practices-using-summarize-and-addcolumns/) |
| 2.2 | Aggregation in `ADDCOLUMNS` without `CALCULATE` | Wrap in `CALCULATE` | [SQLBI](https://www.sqlbi.com/articles/best-practices-using-summarize-and-addcolumns/) |
| 2.3 | `IF(ISBLANK([x]), 0, [x])` | Return `BLANK()` naturally | [MS Learn](https://learn.microsoft.com/en-us/dax/best-practices/dax-avoid-converting-blank) |
| 2.4 | Repeated sub-expression evaluated twice | Extract to `VAR` | [MS Learn](https://learn.microsoft.com/en-us/dax/best-practices/dax-variables) |
| 3.1 | `CALCULATE([x], FILTER(Table, col = val))` | `CALCULATE([x], Table[col] = val)` | [MS Learn](https://learn.microsoft.com/en-us/dax/best-practices/dax-avoid-avoid-filter-as-filter-argument) |
| 3.2 | `FILTER(BigTable, measure > 0)` | `FILTER(VALUES(col), measure > 0)` | [MS Learn](https://learn.microsoft.com/en-us/dax/best-practices/dax-avoid-avoid-filter-as-filter-argument) |
| 3.3 | `IF(HASONEVALUE(col), VALUES(col) = x)` | `SELECTEDVALUE(col) = x` | [MS Learn](https://learn.microsoft.com/en-us/dax/best-practices/dax-selectedvalue) |
| 3.4 | `IF(HASONEVALUE(col), SELECTEDVALUE(col), alt)` | `SELECTEDVALUE(col, alt)` | [XXL BI](https://xxlbi.com/blog/power-bi-antipatterns-2/) |
| 3.6 | `IFERROR([A]/[B], BLANK())` | `DIVIDE([A], [B])` | [MS Learn](https://learn.microsoft.com/en-us/dax/best-practices/dax-error-functions) |
| 3.7 | `VALUES(col) = "scalar"` | `SELECTEDVALUE(col) = "scalar"` | [MS Learn](https://learn.microsoft.com/en-us/dax/best-practices/dax-selectedvalue) |
| 4.1 | Time intelligence on unmarked date column | Dedicated marked Date table | [MS Learn](https://learn.microsoft.com/en-us/dax/time-intelligence-functions-dax) |
| 4.2 | Nested time intelligence functions | Separate `VAR` per period | TDS |
| 4.3 | Hand-crafted `FILTER` for YTD ranges | `DATESYTD`, `DATESMTD`, `DATESQTD` | [DAX Patterns](https://www.daxpatterns.com/standard-time-related-calculations/) |
| 4.4 | `DATESYTD(..., [DynamicMeasure])` | `DATESYTD(..., "6/30")` literal | [MS Learn](https://learn.microsoft.com/en-us/dax/datesytd-function-dax) |
| 5.1 | `EARLIER(col)` | `VAR CurrentVal = col` | [MS Learn](https://learn.microsoft.com/en-us/dax/best-practices/dax-variables) |
| 5.2 | `COUNTROWS(FILTER(T, col > x))` | `CALCULATE(COUNTROWS(T), T[col] > x)` | [MS Learn](https://learn.microsoft.com/en-us/dax/best-practices/dax-avoid-avoid-filter-as-filter-argument) |
| 5.3 | `SELECTEDVALUE(col, LASTDATE(...))` | `SELECTEDVALUE(col, MAX(...))` | [XXL BI](https://xxlbi.com/blog/power-bi-antipatterns-2/) |
| 6.1 | `SUM([SalesAmount])` unqualified | `SUM(Sales[SalesAmount])` | [Tabular Editor BPA](https://docs.tabulareditor.com/te2/Best-Practice-Analyzer.html) |
| 6.2 | Semicolons to chain statements | `VAR` / `RETURN` block | [MS Learn](https://learn.microsoft.com/en-us/dax/var-dax) |
| 6.3 | `RETURN` at top level of UDF | `=>` arrow operator | [MS Learn](https://learn.microsoft.com/en-us/power-bi/transform-model/desktop-user-defined-functions-overview) |
