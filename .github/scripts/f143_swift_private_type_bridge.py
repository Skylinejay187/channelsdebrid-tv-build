#!/usr/bin/env python3
"""Fix compiler-proven private type visibility leaks in staged F143 Swift.

Skip exposes formerly-private SwiftUI views. Their properties then leak
private declared types; Swift rejects this. Promote only compiler-identified
private type declarations to internal, never source ZIP and never based on
uncorroborated full-file string replacements.
"""
import argparse,json,re
from collections import defaultdict
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument("--log",type=Path,required=True)
p.add_argument("--source-root",type=Path,required=True)
p.add_argument("--report",type=Path,required=True)
a=p.parse_args()
root=a.source_root.resolve()
log=a.log.read_text(encoding="utf-8",errors="replace")
log=re.sub(r"\x1b\[[0-9;]*m","",log)
err_rx=re.compile(r"(?m)^.*?/(?P<file>[A-Za-z0-9_./-]+\.swift):(?P<line>\d+):\d+: error: property must be declared fileprivate because its type(?: '(?P<type>[A-Za-z_][\w]*)')? uses a private type")
private_rx=re.compile(r"^(\s*)private\s+((?:final\s+)?(?:class|struct|enum|actor|typealias)\s+)([A-Za-z_]\w*)\b")
code_rx=re.compile(r"(?m)^\s*(?P<line>\d+)\s+\|\s*(?P<decl>private\s+(?:final\s+)?(?:class|struct|enum|actor|typealias)\s+[A-Za-z_]\w*)")
targets=defaultdict(set)
unresolved=[]
for match in err_rx.finditer(log):
    candidates=list(root.rglob(Path(match.group("file")).name))
    if len(candidates)!=1:
        unresolved.append({"error_line":int(match.group("line")),"reason":"Ambiguous source filename"})
        continue
    file=candidates[0]
    lines=file.read_text(encoding="utf-8").splitlines()
    name=match.group("type")
    if name:
        hits=[i for i,line in enumerate(lines) if (decl:=private_rx.match(line)) and decl.group(3)==name]
        if len(hits)==1:
            targets[file].add(hits[0])
            continue
    # For inferred types (and ambiguous named types), compiler emits a note
    # with the exact source declaration. Match quoted line and source text.
    section=log[match.end():match.end()+1000]
    notes=[]
    for note in code_rx.finditer(section):
        index=int(note.group("line"))-1
        if 0<=index<len(lines):
            source=lines[index].strip()
            if source.startswith(note.group("decl").strip()):
                notes.append(index)
    if len(set(notes))==1:
        targets[file].add(notes[0])
    else:
        unresolved.append({"file":str(file.relative_to(root)),
                           "error_line":int(match.group("line")),
                           "type":name,"matching_declarations":len(set(notes))})
changes=[]
for file,locations in targets.items():
    lines=file.read_text(encoding="utf-8").splitlines(keepends=True)
    for i in sorted(locations):
        declaration=private_rx.match(lines[i])
        if not declaration:continue
        before=lines[i]
        after=re.sub(r"^(\s*)private\s+",r"\1",before,count=1)
        if after==before:continue
        lines[i]=after
        changes.append({"file":str(file.relative_to(root)),"line":i+1,
                        "before":before.strip(),"after":after.strip()})
    file.write_text("".join(lines),encoding="utf-8")
result={"matched_property_type_errors":len(list(err_rx.finditer(log))),
        "applied_change_count":len(changes),"changes":changes,
        "unresolved":unresolved,"original_source_zip_modified":False}
a.report.parent.mkdir(parents=True,exist_ok=True)
a.report.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
print(json.dumps({k:result[k] for k in ("matched_property_type_errors","applied_change_count","unresolved")}))
