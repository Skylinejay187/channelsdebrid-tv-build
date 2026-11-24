#!/usr/bin/env python3
"""Explicit Swift 5 compatibility mode for legacy F143 sources under Swift 6.

The supplied tvOS source pre-dates Swift 6's strict global actor checking.
This is a transitional language-mode compatibility setting, not a substitute
for auditing actor isolation and Sendable references.
"""
import argparse,json,re
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument("--project-root",type=Path,required=True)
p.add_argument("--report",type=Path,required=True)
a=p.parse_args()
package=a.project_root/"Package.swift"
if not package.is_file():p.error("Generated Skip Package.swift missing")
text=package.read_text(encoding="utf-8")
if "swiftLanguageModes:" in text or "swiftLanguageVersions:" in text:
    p.error("Package already has a Swift language mode: inspect before changing")
marker="let package = Package("
if text.count(marker)!=1:p.error("Unexpected Skip package manifest structure")
start=text.index(marker)+len(marker)
# Locate Package(...) closing paren, ignoring quoted content and line comments.
depth=1;quoted=False;esc=False;comment=False;end=None
for i in range(start,len(text)):
    c=text[i]
    if comment:
        if c=="\n":comment=False
        continue
    if quoted:
        if esc:esc=False
        elif c=="\\":esc=True
        elif c=='"':quoted=False
        continue
    if c=='"':quoted=True;continue
    if c=="/" and i+1<len(text) and text[i+1]=="/":comment=True;continue
    if c=="(":depth+=1
    elif c==")":
        depth-=1
        if depth==0:
            end=i;break
if end is None:p.error("Could not find Package closing parenthesis")
prefix=text[:end].rstrip()
if not prefix.endswith(","):prefix+=","
fixed=prefix+"\n    swiftLanguageModes: [.v5]\n"+text[end:]
package.write_text(fixed,encoding="utf-8")
a.report.parent.mkdir(parents=True,exist_ok=True)
a.report.write_text(json.dumps({
 "swift_language_mode":"5",
 "swift_toolchain":"6 still used",
 "reason":"legacy F143 singleton and sendability diagnostics",
 "scope":"generated Android Skip Package.swift only",
 "strict_concurrency_fixes_completed":False,
 "apple_source_changed":False
},indent=2)+"\n",encoding="utf-8")
print("Applied Swift 5 language mode to generated Skip package; Swift 6 toolchain retained")
