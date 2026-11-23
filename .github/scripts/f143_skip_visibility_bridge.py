#!/usr/bin/env python3
"""Apply minimal Android Skip visibility edits to temporary F143 SwiftUI sources.

Only compiler-reported files/views are touched. When an originally private View is
promoted to internal, its own wrapped state is promoted at the same time because
Skip's bridge requires that too. NEVER edits the original F143 ZIP.
"""
import argparse
import json
import re
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--log', type=Path, required=True)
p.add_argument('--source-root', type=Path, required=True)
p.add_argument('--report', type=Path, required=True)
a = p.parse_args()
if not a.log.is_file() or not a.source_root.is_dir():
    p.error('Missing compiler log or staged F143 Swift source directory')

log = a.log.read_text(encoding='utf-8', errors='replace')
rx = re.compile(
    r"(?m)^.*?/(?P<file>[A-Za-z0-9_./-]+\.swift):(?P<line>\d+):(?P<column>\d+): error: "
    r"(?P<error>Private state property '(?P<field>[^']+)' cannot be bridged to Android"
    r"|Private views cannot be bridged to Android)"
)
root = a.source_root.resolve()
matched = list(rx.finditer(log))
errors_by_file = {}
for m in matched:
    candidates = list(root.rglob(Path(m.group('file')).name))
    if len(candidates) != 1:
        continue  # fail closed for ambiguous duplicate source names
    f = candidates[0].resolve()
    if not f.is_relative_to(root):
        continue
    errors_by_file.setdefault(f, []).append({
        'line': int(m.group('line')),
        'field': m.group('field'),
        'error': m.group('error'),
    })

wrapped_state = re.compile(
    r'^\s*@(?:State|FocusState|StateObject|ObservedObject|EnvironmentObject|Binding|GestureState|AppStorage|SceneStorage|Environment)\b'
    r'[^\n]*\bprivate\s+var\s+(?P<name>[A-Za-z_][A-Za-z_0-9]*)\b'
)
view_decl = re.compile(r'^\s*private\s+(?:struct|final\s+class|class)\s+[A-Za-z_][A-Za-z_0-9]*(?:<[^\n]*>)?\s*:\s*[^\n]*\b(?:View|ViewModifier)\b')
toplevel = re.compile(r'^(?:(?:public|private|internal|fileprivate|open|final)\s+)*(?:struct|class|enum|extension|actor|protocol)\s+\w+')
changes = []
for f, errors in errors_by_file.items():
    lines = f.read_text(encoding='utf-8').splitlines(keepends=True)
    touched = set()

    def apply(i, category, why):
        old = lines[i]
        new = old.replace('private var ', 'var ', 1) if category == 'wrapped_state' else re.sub(r'^(\s*)private\s+', r'\1', old, count=1)
        if old == new or i in touched:
            return False
        lines[i] = new
        touched.add(i)
        changes.append({'file': str(f.relative_to(root)), 'line': i + 1, 'type': category,
                        'reason': why, 'before': old.strip(), 'after': new.strip()})
        return True

    for err in errors:
        origin = err['line'] - 1
        if err['field']:
            # Skip anchors a property error to the enclosing View declaration,
            # not necessarily to the declaration of the wrapped property.
            # Skip often reports the first line of a huge enclosing View
            # rather than the property's own declaration. Property names such
            # as "focused" repeat in different Views, so a file-wide lookup
            # cannot safely choose one. Restrict matching to the top-level
            # declaration containing the reported position.
            declarations = [i for i, line in enumerate(lines) if toplevel.match(line)]
            preceding = [i for i in declarations if i <= origin]
            following = [i for i in declarations if i > origin]
            # Skip may report an error at an attribute such as @MainActor
            # immediately BEFORE the View declaration, instead of on its
            # struct line. Treat that one-line annotation as belonging to
            # the upcoming declaration, not to the previous type.
            upcoming = following[0] if following else None
            before_next = lines[origin].strip() if 0 <= origin < len(lines) else ''
            if (upcoming is not None and upcoming - origin <= 3
                    and before_next.startswith('@')):
                start = upcoming
                end = following[1] if len(following) > 1 else len(lines)
            else:
                start = preceding[-1] if preceding else 0
                end = following[0] if following else len(lines)
            matches = [
                i for i in range(start, end)
                if (m := wrapped_state.match(lines[i])) and m.group('name') == err['field']
            ]
            if len(matches) == 1:
                apply(matches[0], 'wrapped_state', 'compiler reported state in enclosing SwiftUI declaration')
            elif len(matches) != 1:
                print(f"Unresolved private state {err['field']} in {f.name} "
                      f"at {err['line']}: {len(matches)} matches within lines {start+1}-{end}")
        else:
            for i in range(max(0, origin - 2), min(len(lines), origin + 3)):
                if not view_decl.match(lines[i]):
                    continue
                if apply(i, 'view_visibility', 'compiler reported private SwiftUI view or modifier'):
                    # This View is newly bridge-visible. Expose only its own
                    # wrapped state now to avoid an extra compile/retry cycle.
                    stop = len(lines)
                    for k in range(i + 1, len(lines)):
                        if toplevel.match(lines[k]):
                            stop = k
                            break
                    for k in range(i + 1, stop):
                        if wrapped_state.match(lines[k]):
                            apply(k, 'wrapped_state', 'state within newly exposed View')
                break
    # A promoted wrapped-state property's declared type must be at least as
    # visible as the property. Swift rejects e.g. internal @FocusState var
    # focusedAction: Action? when Action is a nested private enum.
    promoted_state_lines = [
        change['line'] - 1 for change in changes
        if change['file'] == str(f.relative_to(root))
        and change['type'] == 'wrapped_state'
    ]
    for i in promoted_state_lines:
        m = re.search(r'\bvar\s+\w+\s*:\s*(?P<type>[A-Za-z_][A-Za-z_0-9]*)', lines[i])
        if not m:
            continue
        name = m.group('type')
        enclosing = max((j for j in range(i + 1) if toplevel.match(lines[j])), default=-1)
        if enclosing < 0:
            continue
        stop = next((j for j in range(i + 1, len(lines)) if toplevel.match(lines[j])), len(lines))
        rx_private_type = re.compile(r'^\s+private\s+(?:enum|struct|class|typealias)\s+' + re.escape(name) + r'\b')
        for j in range(enclosing + 1, stop):
            if rx_private_type.match(lines[j]):
                apply(j, 'nested_type_visibility', f'promoted SwiftUI state references private type {name}')
                break

    if touched:
        f.write_text(''.join(lines), encoding='utf-8')

result = {
    'reported_visibility_errors': len(matched),
    'applied_change_count': len(changes),
    'source_archive_modified': False,
    'changes': changes,
}
a.report.parent.mkdir(parents=True, exist_ok=True)
a.report.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'reported_visibility_errors': len(matched),
                  'applied_change_count': len(changes)}, indent=2))
