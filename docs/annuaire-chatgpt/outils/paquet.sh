#!/bin/sh
# Construit romkade-chatgpt.zip (paquet de plugin pour platform.openai.com/plugins) à partir de paquet/,
# après validation de plugin.json et mcp.json par les schémas officiels (Agent Plugins 1.0.0).
set -e
cd "$(dirname "$0")/.."
PY=../../cloud/server/.venv/bin/python
for f in plugin mcp; do
  curl -fsS "https://agent-plugins.org/schemas/1.0.0/$f.schema.json" -o "/tmp/romkade-$f.schema.json"
  $PY -c "import json, jsonschema; jsonschema.validate(json.load(open('paquet/$f.json')), json.load(open('/tmp/romkade-$f.schema.json')))"
done
rm -f romkade-chatgpt.zip
(cd paquet && zip -qrX ../romkade-chatgpt.zip plugin.json mcp.json assets -x '*.DS_Store')
unzip -l romkade-chatgpt.zip
