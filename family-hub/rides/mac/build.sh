#!/bin/sh
# Compile family-rides with Info.plist embedded. The embedded usage string is
# what lets macOS show a Calendars permission prompt for a command-line tool.
set -e
cd "$(dirname "$0")"
mkdir -p "$HOME/.local/bin"
swiftc -O -swift-version 5 rides.swift -o "$HOME/.local/bin/family-rides" \
  -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker Info.plist
echo "built $HOME/.local/bin/family-rides"
