#!/usr/bin/env python3
"""Summarize distinct Android Swift compile blockers without repeating Gradle logs.
Returns status 0; emitted JSON and Markdown are diagnostic only.
"""
import argparse,collections,json,re
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument("--log",required=True,type=Path)
p.add_argument("--output",required=True,type=Path)
a=p.parse_args()
s=a.log.read_text(encoding="utf-8",errors="replace")
pattern=re.compile(r"/F143Original/([^:\n]+\.swift):(\d+):(\d+): error: ([^\n]+)")
errors=sorted(set((m.group(1),int(m.group(2)),m.group(4)) for m in pattern.finditer(s)))
categories={
    "tvOS remote input":lambda t: any(x in t for x in ("onMoveCommand","onExitCommand","onPlayPauseCommand","MoveCommandDirection","unavailable in iOS")),
    "Swift concurrency / actor isolation":lambda t: any(x in t for x in ("concurrency-safe","Sendable","actor-isolated","nonisolated")),
    "Swift visibility":lambda t: "fileprivate" in t or "private type" in t,
    "missing Android bridge symbols":lambda t: "cannot find" in t or "has no member" in t,
}
groups=collections.defaultdict(list)
for file,line,message in errors:
    category=next((k for k,fn in categories.items() if fn(message)),"other Swift compile errors")
    groups[category].append({"file":file,"line":line,"error":message})
counts={k:len(v) for k,v in groups.items()}
result={
    "unique_error_count":len(errors),
    "affected_file_count":len(set(f for f,_,_ in errors)),
    "counts":counts,
    "examples":{k:v[:12] for k,v in groups.items()},
    "requires_actual_android_implementation": True,
}
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
print(json.dumps({"unique_error_count":result["unique_error_count"],
    "affected_file_count":result["affected_file_count"],
    "counts":counts},indent=2))
