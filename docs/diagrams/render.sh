#!/bin/sh
# Render every Mermaid source in this directory to SVG (docs/slides) and PNG (raster fallback).
# Usage: ./render.sh   (needs Node; set PUPPETEER_EXECUTABLE_PATH to a local Chrome if Chromium isn't downloaded)
set -e
cd "$(dirname "$0")"
for f in *.mmd; do
  b="${f%.mmd}"
  npx -y @mermaid-js/mermaid-cli@11 -c mermaid.config.json -b white -i "$f" -o "$b.svg" ${PUPPETEER_CFG:+-p "$PUPPETEER_CFG"}
  npx -y @mermaid-js/mermaid-cli@11 -c mermaid.config.json -b white -s 2 -i "$f" -o "$b.png" ${PUPPETEER_CFG:+-p "$PUPPETEER_CFG"}
done
