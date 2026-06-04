#!/usr/bin/env bash
# Compute rolling alias tags from a set of EXACT X.Y.Z image tags.
#
# Reads exact version tags on stdin (one per line; anything not matching
# X.Y.Z is ignored, so it is safe to pipe a full tag list including edge,
# nightly, *-amd64, etc.). Emits one "aliastag<TAB>target" line per alias:
#
#   X.Y    -> newest patch within that minor
#   X      -> newest version within that major
#   latest -> newest version overall
#
# Aliases are computed over exactly the tags given, so a target is always a
# tag that exists. Feed it the tags actually present in the registry.
set -euo pipefail

awk '
  function key(v,  p,n){ n=split(v,p,"."); return (p[1]+0)*1000000+(p[2]+0)*1000+(p[3]+0) }
  /^[0-9]+\.[0-9]+\.[0-9]+$/ { tags[++n]=$0 }
  END{
    for(i=2;i<=n;i++){ pos=i; while(pos>1 && key(tags[pos-1])>key(tags[pos])){ t=tags[pos];tags[pos]=tags[pos-1];tags[pos-1]=t;pos-- } }
    for(i=1;i<=n;i++){ v=tags[i]; split(v,p,"."); minor[p[1]"."p[2]]=v; major[p[1]]=v; latest=v }
    for(k in minor) print k"\t"minor[k]
    for(k in major) print k"\t"major[k]
    if(latest!="") print "latest\t"latest
  }'
