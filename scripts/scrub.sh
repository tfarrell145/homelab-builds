#!/bin/sh
# Pre-push check: fails if anything that looks private is in the working tree.
#
#   scripts/scrub.sh                       generic checks only
#   scripts/scrub.sh ~/private-patterns    plus one extended regex per line
#                                          (names, hostnames, account IDs);
#                                          # comments and blank lines ignored
#
# The private pattern file lives outside this repo: a list of what must never
# be published is itself something that must never be published.
set -u
cd "$(dirname "$0")/.."

generic='(^|[^0-9])(10\.[0-9]+\.[0-9]+\.[0-9]+|192\.168\.[0-9]+\.[0-9]+|172\.(1[6-9]|2[0-9]|3[01])\.[0-9]+\.[0-9]+|100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.[0-9]+\.[0-9]+)|[A-Za-z0-9._%+-]+@(gmail|icloud|me|outlook|yahoo)\.com|ghp_[A-Za-z0-9]{20,}|github_pat_|sk-ant-|eyJ[A-Za-z0-9_-]{20,}\.|ts\.net|-----BEGIN [A-Z ]*PRIVATE KEY'

# Documentation examples that look like private addresses on purpose.
allow='192\.168\.1\.50|100\.x\.y\.z'

hits=$(grep -rnIE "$generic" --exclude-dir=.git --exclude=scrub.sh . | grep -vE "$allow")
if [ $# -gt 0 ]; then
  patterns=$(mktemp); trap 'rm -f "$patterns"' EXIT
  grep -vE '^[[:space:]]*(#|$)' "$1" > "$patterns"
  more=$(grep -rnIEif "$patterns" --exclude-dir=.git --exclude=scrub.sh .)
  hits=$(printf '%s\n%s' "$hits" "$more" | sed '/^$/d')
fi

if [ -n "$hits" ]; then
  echo "$hits"
  echo "scrub: $(echo "$hits" | wc -l | tr -d ' ') line(s) to review before pushing" >&2
  exit 1
fi
echo "scrub: clean"
