#!/usr/bin/env python3
"""Patch only Skip-reported private SwiftUI bridge visibility errors.

Edits are restricted to staged Swift copies in the GitHub runner.
The original uploaded F143 ZIP is never changed.
"""
import argparse
import json
from pathlib import Path
import re
import sys

p = argparse.ArgumentParser()
p.add_argument("--log", type=Path, required=True)
p.add_argument("--source-root", type=Path, required=True)
p.add_argument("--report", type=Path, required=True)
args = p.parse_args()
if not args.log.is_file() or not args.source_root.is_dir():
    sys.exit("Skip compiler log or staged source directory missing")

log = args.log.read_text(encoding="utf-8", errors="replace")
error_re = re.compile(
    r"(?m)^.*?/(?P<file>[A-Za-z0-9_./-]+\.swift):(?P<line>\d+):(?P<column>\d+): error: "
    r"(?P<error>Private state property '(?P<field>[^']+)' cannot be bridged to Android"
    r"|Private views cannot be bridged to Android)"
)
by_file = {}
root = args.source_root.resolve()
for m in error_re.finditer(log):
    candidates = list(root.rglob(Path(m.group("file")).name))
    if len(candidates) != 1:
        continue
    file = candidates[0].resolve()
    if not file.is_relative_to(root):
        continue
    by_file.setdefault(file, []).append(
        (int(m.group("line")), m.group("field"), m.group("error"))
    )

changes = []
for path, errors in by_file.items():
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    for line_number, field, error in sorted(set(errors)):
        if field is not None:
            field_re = re.compile(
                r"^\s*@(?:State|FocusState|StateObject|ObservedObject|EnvironmentObject|Binding)\b"
                r"[^\n]*?\bprivate\s+var\s+" + re.escape(field) + r"\b"
            )
            matches = [
                i for i, line in enumerate(lines)
                if line_number - 1 <= i < line_number + 280 and field_re.search(line)
            ]
            if not matches:
                continue
            i = min(matches)
            before = lines[i]
            lines[i] = before.replace("private var ", "var ", 1)
            if before != lines[i]:
                changes.append({
                    "file": str(path.relative_to(root)), "line": i + 1,
                    "type": "private_state", "property": field,
                    "before": before.strip(), "after": lines[i].strip()
                })
        else:
            for i in range(max(0, line_number - 3), min(len(lines), line_number + 3)):
                before = lines[i]
                if (re.match(r"^\s*private\s+(?:struct|final\s+class|class)\s+", before)
                        and re.search(r"\bView\b", before)):
                    lines[i] = re.sub(r"^(\s*)private\s+", r"\1", before, count=1)
                    changes.append({
                        "file": str(path.relative_to(root)), "line": i + 1,
                        "type": "private_view", "before": before.strip(),
                        "after": lines[i].strip()
                    })
                    break
    updated = "".join(lines)
    if updated != original:
        path.write_text(updated, encoding="utf-8")

result = {
    "policy": "Only staged Swift files patched in runner; original F143 ZIP untouched",
    "reported_visibility_errors": len(list(error_re.finditer(log))),
    "applied_change_count": len(changes),
    "changes": changes
}
args.report.parent.mkdir(parents=True, exist_ok=True)
args.report.write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps({
    "reported_visibility_errors": result["reported_visibility_errors"],
    "applied_change_count": result["applied_change_count"]
}))
