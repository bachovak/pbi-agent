"""
sanitiser.py — Model.bim sanitisation module
Scans for sensitive data and replaces it with safe placeholders.
Never modifies the original file.

Architecture: parse JSON first, sanitise decoded string values in-place,
re-serialise. This guarantees the output is always valid JSON regardless
of what the regex patterns do inside individual string values.
"""

import re
import json

# ── Regex Patterns ────────────────────────────────────────────────────────────
# These operate on *decoded* Python strings (not raw JSON text), so:
# - Backslashes are real backslashes, not \\
# - Newlines are real newlines, not \n escape sequences
# - Quotes are real quotes, not \"

# Sql.Database("server", "db") — M query Power Query source
_RE_SQL_DATABASE = re.compile(
    r'Sql\.Database\s*\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)',
    re.IGNORECASE
)

# Data Source=<server> in connection strings
_RE_DATA_SOURCE = re.compile(
    r'(Data\s+Source\s*=\s*)([^;"\s]+)',
    re.IGNORECASE
)

# Initial Catalog=<db> in connection strings
_RE_INITIAL_CATALOG = re.compile(
    r'(Initial\s+Catalog\s*=\s*)([^;"\s]+)',
    re.IGNORECASE
)

# Windows file paths: C:\... or D:\... etc. (real backslashes)
_RE_WIN_PATH = re.compile(
    r'[A-Za-z]:\\(?:[^\\/:*?"<>|\r\n]+\\)*[^\\/:*?"<>|\r\n]*'
)

# UNC network paths: \\server\share (real backslashes)
_RE_UNC_PATH = re.compile(
    r'\\\\[A-Za-z0-9._-]+\\[A-Za-z0-9._\-$\\]*'
)

# URLs
_RE_URL = re.compile(
    r'https?://[^\s"\'<>\])]+'
)

# Email addresses
_RE_EMAIL = re.compile(
    r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}'
)

# GUIDs
_RE_GUID = re.compile(
    r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
)

# DAX/M single-line comments: // ... (stops at real newline)
_RE_LINE_COMMENT = re.compile(r'//[^\n]*')

# DAX/M block comments: /* ... */ (DOTALL OK — operating on decoded strings)
_RE_BLOCK_COMMENT = re.compile(r'/\*.*?\*/', re.DOTALL)


# ── Core Sanitiser ────────────────────────────────────────────────────────────

def sanitise_model(
    bim_path,
    mask_sql_connections=True,
    mask_file_paths=True,
    mask_urls=True,
    mask_emails=True,
    mask_guids=False,
    remove_rls=False,
    remove_comments=True,
):
    """
    Read a model.bim file, detect and redact sensitive items.
    The original file is never modified.

    Strategy: parse the JSON first, walk every string value and apply
    regex patterns on the decoded text, then re-serialise. This guarantees
    the output is always valid, parseable JSON.

    Returns (sanitised_content: str, report: dict).
    """
    with open(bim_path, "r", encoding="utf-8") as f:
        raw = f.read()

    data = json.loads(raw)

    items_found = []
    categories = {}

    def _record(category, original, replacement):
        items_found.append({
            "category": category,
            "original": original,
            "replacement": replacement,
            "location": "string value",
        })
        categories[category] = categories.get(category, 0) + 1

    def _sub(pattern, replacement_fn, category, text):
        def _replacer(m):
            original = m.group(0)
            replacement = replacement_fn(m)
            if original != replacement:
                _record(category, original, replacement)
            return replacement
        return pattern.sub(_replacer, text)

    def sanitise_str(s):
        """Apply all enabled patterns to a single decoded string value."""
        if mask_sql_connections:
            s = _sub(
                _RE_SQL_DATABASE,
                lambda m: f'Sql.Database("SERVER_REDACTED", "DATABASE_REDACTED")',
                "sql_database", s,
            )
            s = _sub(_RE_DATA_SOURCE, lambda m: m.group(1) + "SERVER_REDACTED", "data_source", s)
            s = _sub(_RE_INITIAL_CATALOG, lambda m: m.group(1) + "DATABASE_REDACTED", "initial_catalog", s)

        if mask_file_paths:
            # UNC before Windows so \\\\ is caught before [A-Za-z]:\\
            s = _sub(_RE_UNC_PATH, lambda m: "PATH_REDACTED", "unc_path", s)
            s = _sub(_RE_WIN_PATH, lambda m: "PATH_REDACTED", "file_path", s)

        if mask_urls:
            s = _sub(_RE_URL, lambda m: "URL_REDACTED", "url", s)

        if mask_emails:
            s = _sub(_RE_EMAIL, lambda m: "EMAIL_REDACTED", "email", s)

        if mask_guids:
            s = _sub(_RE_GUID, lambda m: "GUID_REDACTED", "guid", s)

        if remove_comments:
            s = _sub(_RE_BLOCK_COMMENT, lambda m: "", "block_comment", s)
            s = _sub(_RE_LINE_COMMENT, lambda m: "", "line_comment", s)

        return s

    def walk(obj):
        """Recursively walk the JSON structure and sanitise every string."""
        if isinstance(obj, str):
            return sanitise_str(obj)
        if isinstance(obj, list):
            return [walk(item) for item in obj]
        if isinstance(obj, dict):
            if remove_rls and "roles" in obj:
                original = json.dumps(obj["roles"])
                if obj["roles"]:  # only record if there was something to remove
                    _record("rls_roles", original, "[]")
                obj = {k: ([] if k == "roles" else walk(v)) for k, v in obj.items()}
                return obj
            return {k: walk(v) for k, v in obj.items()}
        return obj

    sanitised_data = walk(data)
    sanitised_content = json.dumps(sanitised_data, ensure_ascii=False, indent=2)

    total = sum(categories.values())

    # Safety check: scan the re-serialised content for any unredacted values
    # that belong to enabled categories (placeholders are excluded).
    _PLACEHOLDERS = {
        "SERVER_REDACTED", "DATABASE_REDACTED", "PATH_REDACTED",
        "URL_REDACTED", "EMAIL_REDACTED", "GUID_REDACTED",
    }
    remaining_checks = []
    if mask_sql_connections:
        remaining_checks += [_RE_SQL_DATABASE, _RE_DATA_SOURCE, _RE_INITIAL_CATALOG]
    if mask_file_paths:
        remaining_checks += [_RE_UNC_PATH, _RE_WIN_PATH]
    if mask_urls:
        remaining_checks.append(_RE_URL)
    if mask_emails:
        remaining_checks.append(_RE_EMAIL)

    def _has_unredacted(pattern, text):
        for m in pattern.finditer(text):
            if not any(ph in m.group(0) for ph in _PLACEHOLDERS):
                return True
        return False

    is_safe = not any(_has_unredacted(p, sanitised_content) for p in remaining_checks)

    report = {
        "total_replacements": total,
        "categories": categories,
        "items_found": items_found,
        "is_safe_to_proceed": is_safe,
        "settings": {
            "mask_sql_connections": mask_sql_connections,
            "mask_file_paths": mask_file_paths,
            "mask_urls": mask_urls,
            "mask_emails": mask_emails,
            "mask_guids": mask_guids,
            "remove_rls": remove_rls,
            "remove_comments": remove_comments,
        },
    }

    return sanitised_content, report


# ── Semantic Reference Validator (System C — T2-B) ───────────────────────────
# Validates that every object reference in a generated DAX expression exists in
# the model registry produced by model_inspector.build_model_registry().
#
# Implements the cross-reference and semantic validation patterns identified in
# the analysis of data-goblin/power-bi-agentic-development (GPL v3) —
# patterns C2 (valid syntax ≠ valid semantics), D1–D3 (orphan detection),
# F2 (summarizeBy semantic rules), F3 (compat level gating).
# Implementation here is original code.


class SemanticReferenceValidator:
    """
    Validates that all object references in a DAX expression exist in the model
    registry produced by System A (build_model_registry()).

    Catches:
      - References to tables that don't exist in the model
      - References to columns that don't exist in those tables
      - References to measures that don't exist in the model
      - Direct aggregation of summarizeBy=none columns (semantic warning)
      - SELECTEDMEASURE() when model has no calculation groups
      - DAX UDFs when model compatibility level < 1702
    """

    def __init__(self, model_registry: dict):
        self.registry = model_registry
        self._build_lookup_sets()

    def _build_lookup_sets(self):
        """Build O(1) lookup sets from the registry."""
        self.valid_columns: set = set()
        for table, cols in self.registry.get("columns", {}).items():
            for col in cols:
                ref = col["ref"]  # e.g. "Sales[Amount]"
                self.valid_columns.add(ref.lower())

        self.valid_tables: set = {
            t.lower() for t in self.registry.get("tables", [])
        }

        self.valid_measures: set = {
            m["ref"].strip("[]").lower()
            for m in self.registry.get("measures", [])
        }

        self.non_additive_columns: set = set()
        for table, cols in self.registry.get("columns", {}).items():
            for col in cols:
                if col.get("summarizeBy") == "none" or col.get("isKey"):
                    self.non_additive_columns.add(col["ref"].lower())

    def validate(self, dax_expression: str) -> dict:
        """
        Validate all object references in a DAX expression.

        Returns:
            {
              "passed":   bool,
              "errors":   [str],   # blocking — object doesn't exist in model
              "warnings": [str]    # non-blocking — semantic concern
            }
        """
        errors = []
        warnings = []

        # Strip DAX line and block comments before pattern matching to avoid
        # false positives from Claude echoing registry tags (e.g. [no-aggregate])
        # inside comments. All patterns run against the comment-free copy.
        dax_clean = re.sub(r"//[^\n]*", "", dax_expression)
        dax_clean = re.sub(r"/\*.*?\*/", "", dax_clean, flags=re.DOTALL)

        # Track which non-additive refs have already generated a warning to
        # avoid duplicate entries when the same column appears multiple times.
        warned_agg_refs: set = set()

        # Track positions already covered by the quoted-column pattern so
        # the measure-reference pass doesn't double-count them.
        col_match_spans: list = []

        # 1. Validate 'Table'[Column] references (correct fully-qualified form)
        quoted_col_pattern = re.compile(r"'([^']+)'\[([^\]]+)\]")
        for match in quoted_col_pattern.finditer(dax_clean):
            col_match_spans.append(match.span())
            table_name = match.group(1)
            col_name = match.group(2)
            full_ref = f"{table_name}[{col_name}]".lower()

            if table_name.lower() not in self.valid_tables:
                errors.append(
                    f"UNKNOWN TABLE: '{table_name}' is not in the model "
                    f"(from '{match.group(0)}')"
                )
            elif full_ref not in self.valid_columns:
                errors.append(
                    f"UNKNOWN COLUMN: [{col_name}] does not exist in "
                    f"table '{table_name}' (from '{match.group(0)}')"
                )

            # Check for direct aggregation of non-additive / key columns.
            # Use warned_agg_refs to emit only one warning per unique ref.
            if full_ref in self.non_additive_columns and full_ref not in warned_agg_refs:
                agg_pattern = re.compile(
                    r"\b(SUM|AVERAGE|AVG|MIN|MAX|COUNT|COUNTA|DISTINCTCOUNT)\s*\(\s*"
                    + re.escape(match.group(0)),
                    re.IGNORECASE
                )
                if agg_pattern.search(dax_clean):
                    warnings.append(
                        f"SEMANTIC WARNING: '{match.group(0)}' is a key/attribute "
                        f"column (summarizeBy=none) but is being directly aggregated. "
                        f"This is almost certainly incorrect."
                    )
                    warned_agg_refs.add(full_ref)

        # 2. Also catch unquoted Table[Column] references — these are a format
        #    violation (should be 'Table'[Column]) and may still be wrong names.
        unquoted_col_pattern = re.compile(r"(?<!')\b([A-Za-z][A-Za-z0-9 _$]*)\[([^\]]+)\]")
        for match in unquoted_col_pattern.finditer(dax_clean):
            table_name = match.group(1).strip()
            col_name = match.group(2).strip()
            if table_name.lower() in self.valid_tables:
                full_ref = f"{table_name}[{col_name}]".lower()
                if full_ref not in self.valid_columns:
                    errors.append(
                        f"UNKNOWN COLUMN: [{col_name}] does not exist in "
                        f"table '{table_name}' (from '{match.group(0)}'). "
                        f"Also: use quoted form 'TableName'[ColumnName]."
                    )
                else:
                    warnings.append(
                        f"FORMAT: Use single-quoted table name: "
                        f"'{table_name}'[{col_name}] not {table_name}[{col_name}]"
                    )

        # 3. Validate [Measure] references (unqualified bracket notation).
        #    Skip anything whose '[' is immediately preceded by a single quote —
        #    those are column refs already handled above.
        measure_pattern = re.compile(r"\[([^\]]+)\]")
        for match in measure_pattern.finditer(dax_clean):
            start = match.start()
            if start > 0 and dax_clean[start - 1] == "'":
                continue  # column ref, already validated above
            measure_name = match.group(1)
            if measure_name.lower() not in self.valid_measures:
                errors.append(
                    f"UNKNOWN MEASURE: [{measure_name}] is not in the model. "
                    f"Check for typos or confirm it is defined elsewhere."
                )

        # 4. Compatibility level gating
        compat = self.registry.get("compatibility_level", 0)
        if compat > 0 and compat < 1702:
            udf_pattern = re.compile(r"\b\w+\.\w+\s*\(", re.IGNORECASE)
            if udf_pattern.search(dax_clean):
                warnings.append(
                    f"COMPATIBILITY: Model is at level {compat}. DAX UDFs "
                    f"(e.g. MyLib.Function()) require compatibility level 1702+."
                )

        if not self.registry.get("has_calculation_groups", False):
            if re.search(r"\bSELECTEDMEASURE\s*\(", dax_clean, re.IGNORECASE):
                errors.append(
                    "SEMANTIC ERROR: SELECTEDMEASURE() referenced but model has no "
                    "calculation groups (has_calculation_groups=False in registry)."
                )

        return {
            "passed": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }


def validate_generated_dax(
    dax_expression: str,
    model_registry: dict,
    existing_measure_names=None,
) -> dict:
    """
    Top-level validation combining semantic reference resolution with amendment
    protection. Suitable for calling directly from the generation pipeline.

    existing_measure_names: list of measure names already in the library,
    used to warn about silent overwrites (non-blocking).
    """
    validator = SemanticReferenceValidator(model_registry)
    result = validator.validate(dax_expression)

    if existing_measure_names:
        import re as _re
        for existing in existing_measure_names:
            name_pattern = _re.compile(
                r"^\s*" + _re.escape(existing) + r"\s*=",
                _re.IGNORECASE | _re.MULTILINE,
            )
            if name_pattern.search(dax_expression):
                result["warnings"].append(
                    f"AMENDMENT RISK: Expression redefines existing measure "
                    f"'{existing}'. Confirm this replacement is intentional."
                )

    return result


# ── Self-test ─────────────────────────────────────────────────────────────────

def run_test():
    """Create a fake model.bim with one example of every sensitive category
    and assert each one is caught, replaced, and the output is valid JSON."""

    # Build the test data as a Python dict so json.dumps handles encoding correctly.
    # String values use real characters (backslashes, quotes) as they would appear
    # in a decoded JSON string — i.e. as the sanitiser will see them.
    fake_data = {
        "name": "FakeModel",
        "model": {
            "tables": [
                {
                    "name": "Sales",
                    "partitions": [
                        {
                            "source": {
                                "type": "m",
                                "expression": [
                                    "let",
                                    '    // Developer comment - server info below',
                                    '    Source = Sql.Database("prod-server.company.com", "SalesDB"),',
                                    '    /* block comment */ FilePath = "C:\\Users\\analyst\\data\\export.csv",',
                                    '    UNCPath = "\\\\fileserver\\shared\\reports",',
                                    '    ConnStr = "Data Source=legacy-server;Initial Catalog=LegacyDB",',
                                    '    ApiUrl = "https://api.company.com/v2/data",',
                                    '    ContactEmail = "data.team@company.com"',
                                    "in Source",
                                ]
                            }
                        }
                    ],
                    "measures": [
                        {
                            "name": "Total Sales",
                            "expression": "SUM(Sales[Amount]) // simple sum",
                        }
                    ],
                }
            ],
            "roles": [
                {
                    "name": "RegionFilter",
                    "members": [{"memberName": "DOMAIN\\user1"}],
                }
            ],
        },
        "guid_field": "550e8400-e29b-41d4-a716-446655440000",
    }

    import tempfile, os

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".bim", delete=False, encoding="utf-8"
    ) as tmp:
        json.dump(fake_data, tmp, indent=2)
        tmp_path = tmp.name

    try:
        sanitised, report = sanitise_model(
            tmp_path,
            mask_sql_connections=True,
            mask_file_paths=True,
            mask_urls=True,
            mask_emails=True,
            mask_guids=True,
            remove_rls=True,
            remove_comments=True,
        )
    finally:
        os.unlink(tmp_path)

    print("=" * 60)
    print("SANITISER TEST RESULTS")
    print("=" * 60)
    print(f"Total replacements : {report['total_replacements']}")
    print(f"Is safe to proceed : {report['is_safe_to_proceed']}")
    print()
    print("Replacements by category:")
    for cat, count in sorted(report["categories"].items()):
        print(f"  {cat:<20} {count}")
    print()
    print("Items found:")
    for item in report["items_found"]:
        orig = item["original"][:60].replace("\n", "\\n")
        print(f"  [{item['category']}]  '{orig}'  ->  '{item['replacement']}'")

    print()
    print("Assertions:")
    all_passed = True

    # All categories must be detected
    expected_categories = [
        "sql_database", "data_source", "initial_catalog",
        "file_path", "unc_path", "url", "email",
        "guid", "rls_roles", "line_comment", "block_comment",
    ]
    for cat in expected_categories:
        found = cat in report["categories"]
        status = "PASS" if found else "FAIL"
        if not found:
            all_passed = False
        print(f"  {status}  {cat} detected")

    # Output must be valid JSON
    try:
        json.loads(sanitised)
        print("  PASS  output is valid JSON")
    except json.JSONDecodeError as e:
        print(f"  FAIL  output is NOT valid JSON: {e}")
        all_passed = False

    safe_status = "PASS" if report["is_safe_to_proceed"] else "FAIL"
    if not report["is_safe_to_proceed"]:
        all_passed = False
    print(f"  {safe_status}  is_safe_to_proceed == True")

    print()
    print("Overall:", "ALL TESTS PASSED" if all_passed else "SOME TESTS FAILED")
    print("=" * 60)

    return all_passed


if __name__ == "__main__":
    run_test()
