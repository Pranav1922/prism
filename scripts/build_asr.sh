#!/bin/sh
# Build the macOS on-device ASR helper used by the local perception worker (agent/perception.py).
# Output: .build/prism_asr. On other platforms, perception falls back to the scripted transcripts.
set -e
cd "$(dirname "$0")/.."
mkdir -p .build
swiftc -O agent/perception_macos/asr.swift -o .build/prism_asr \
  -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker agent/perception_macos/Info.plist
echo "built .build/prism_asr"
