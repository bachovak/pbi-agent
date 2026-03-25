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
