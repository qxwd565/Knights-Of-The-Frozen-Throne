#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,sys,xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MANIFEST=ROOT/"sources"/"frozen-throne-undated-observations.json"
def local(tag): return tag.rsplit("}",1)[-1]
def parse(path,wanted):
 digest=hashlib.sha256(path.read_bytes()).hexdigest(); found={}
 for _,entity in ET.iterparse(path,events=("end",)):
  if local(entity.tag)!="Entity": continue
  cid=entity.attrib.get("CardID")
  if cid not in wanted: entity.clear(); continue
  tags={}; strings={}
  for child in list(entity):
   if local(child.tag)!="Tag": continue
   tid=int(child.attrib.get("enumID","-1"))
   if tid in (184,185):
    key="CARDTEXT_INHAND" if tid==184 else "CARDNAME"; locales={}
    for node in list(child):
     locale=local(node.tag)
     if locale in ("koKR","enUS"): locales[locale]=(node.text or "").replace(chr(92)+"n",chr(10))
    strings[key]=locales
   elif "value" in child.attrib: tags[tid]=str(child.attrib["value"])
  found[cid]={"dbfId":int(entity.attrib["ID"]),"tags":tags,"strings":strings}; entity.clear()
 missing=wanted-set(found)
 if missing: raise RuntimeError(f"{path.name}: missing {sorted(missing)}")
 return digest,found
def check(f,o,b,a):
 cid=o["cardID"]
 if b[cid]["dbfId"]!=a[cid]["dbfId"]: raise RuntimeError(f"{f['findingID']}:{cid}: DBF mismatch")
 for key,e in o["changes"].items():
  if key.isdigit():
   tid=int(key)
   def state(snapshot):
    tags=snapshot[cid]["tags"]
    return {"present":tid in tags,**({"value":tags[tid]} if tid in tags else {})}
   if state(b)!=e["before"] or state(a)!=e["after"]: raise RuntimeError(f"{f['findingID']}:{cid}:Tag{tid} mismatch")
  elif key in ("rawText","enText"):
   loc="koKR" if key=="rawText" else "enUS"
   x=b[cid]["strings"].get("CARDTEXT_INHAND",{}).get(loc); y=a[cid]["strings"].get("CARDTEXT_INHAND",{}).get(loc)
   if x!=e["before"] or y!=e["after"]: raise RuntimeError(f"{f['findingID']}:{cid}:{loc} text mismatch")
def main(root):
 m=json.loads(MANIFEST.read_text(encoding="utf-8")); fs=m["findings"]
 if len(fs)!=14 or any(f.get("koreanDay") is not None for f in fs): raise RuntimeError("Expected 14 undated findings")
 wanted={}
 for f in fs:
  if f.get("countedAsConfirmedGameplayHistory") is not False: raise RuntimeError("undated finding marked gameplay")
  for side in ("archiveBefore","archiveAfter"): wanted.setdefault(f[side]["commit"],set()).update(o["cardID"] for o in f["observations"])
 snaps={}
 for f in fs:
  for side in ("archiveBefore","archiveAfter"):
   meta=f[side]; sha=meta["commit"]
   if sha in snaps: continue
   path=root/f"CardDefs-{sha}.xml"
   if not path.exists(): raise RuntimeError(f"Missing {path}")
   digest,cards=parse(path,wanted[sha])
   if digest!=meta["xmlSha256"]: raise RuntimeError(f"{sha}: SHA-256 mismatch")
   snaps[sha]=cards
 count=0
 for f in fs:
  b=snaps[f["archiveBefore"]["commit"]]; a=snaps[f["archiveAfter"]["commit"]]
  for o in f["observations"]: check(f,o,b,a); count+=1
 print(json.dumps({"findings":len(fs),"verifiedSnapshots":len(snaps),"cardObservations":count,"datedEventsCreated":0,"outOfScopeGroups":len(m.get("excludedOutOfScope",[]))},ensure_ascii=False))
if __name__=="__main__":
 if len(sys.argv)!=2: raise SystemExit("Usage: verify-icc-undated-observations.py /tmp")
 main(Path(sys.argv[1]))
