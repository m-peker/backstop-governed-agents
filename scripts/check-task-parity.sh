#!/usr/bin/env sh
# Two entry points into the developer loop drift the moment nobody checks.
#
# Compares the target names exposed by the Makefile (any target carrying a `##`
# help comment) against the switch branches in task.ps1. `help` and `doctor` are
# intentionally asymmetric and excluded.
#
# Uses POSIX sed rather than `grep -P` so it runs identically on CI and on a
# developer's Git Bash.

set -eu

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

sed -n 's/^\([a-z][a-z-]*\):.*##.*/\1/p' Makefile | grep -vx 'help' | sort -u > "$tmp/make.txt"
sed -n "s/^    '\([a-z]*\)'.*/\1/p" task.ps1 | grep -vxE 'help|doctor' | sort -u > "$tmp/ps.txt"

if diff -u "$tmp/make.txt" "$tmp/ps.txt"; then
  printf 'Task parity OK (%s targets)\n' "$(wc -l < "$tmp/make.txt" | tr -d ' ')"
else
  printf '\nMakefile and task.ps1 expose different targets.\n' >&2
  printf 'Lines prefixed with - exist only in the Makefile, + only in task.ps1.\n' >&2
  exit 1
fi
