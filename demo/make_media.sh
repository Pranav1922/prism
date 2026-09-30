#!/bin/sh
# Regenerate the demo media (macOS): spoken requests via `say`, the boarding-pass image via AppKit.
set -e
cd "$(dirname "$0")"
say -o media/find_delhi.aiff "Find a flight from Bangalore to Delhi on Friday."
say -o media/wait_mumbai.aiff "Wait, Mumbai instead."
say -o media/ticket_request.aiff "Find flights from Bangalore to Delhi on the date on this ticket."
swift render_ticket.swift media/ticket.png
echo "demo media written to demo/media/"
