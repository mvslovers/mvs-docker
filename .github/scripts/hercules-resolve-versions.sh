#!/usr/bin/env bash
# Resolve SDL-Hyperion release tags into the canonical exact image-tag set.
#
#   - keep only Release_* tags
#   - dedup tags that point at the same commit, preferring the shorter
#     Release_X.Y name over Release_X.Y.0 (they are identical builds)
#   - normalize the image tag to 3 components (X.Y -> X.Y.0); the exact
#     image tag is always 3-part so it never collides with a rolling alias
#   - optionally drop everything below MIN_VERSION
#
# Output: one "version<TAB>Release_ref" line per release, ascending by version.
#   4.9.0	Release_4.9
#   4.9.1	Release_4.9.1
#
# Usage: hercules-resolve-versions.sh [MIN_VERSION]   (e.g. 4.8; default = all)
set -euo pipefail

REPO="SDL-Hercules-390/hyperion"
MIN="${1:-0.0.0}"

gh api "repos/$REPO/tags" --paginate \
  --jq '.[] | select(.name|startswith("Release_")) | "\(.name) \(.commit.sha)"' \
| awk '{
    name=$1; sha=$2; ver=name; sub(/^Release_/,"",ver)
    n=split(ver,p,".")
    v3=(p[1]+0)"."(n>=2?p[2]+0:0)"."(n>=3?p[3]+0:0)
    print sha, (n-1), v3, name            # sha, dot-count, normalized, ref
  }' \
| sort -k1,1 -k2,2n \
| awk '!seen[$1]++ { print $3"\t"$4 }' \
| sort -k1,1V \
| awk -F'\t' -v MIN="$MIN" '
    function key(v,  p,n){ n=split(v,p,"."); return (p[1]+0)*1000000+(p[2]+0)*1000+(p[3]+0) }
    BEGIN{ mk=key(MIN) }
    key($1) >= mk { print }'
