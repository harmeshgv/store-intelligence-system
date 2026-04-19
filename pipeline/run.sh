#!/bin/bash

echo "🚀 Starting Store Intelligence Pipeline..."

.venv/Scripts/activate

python pipeline/run.py

echo "✅ Pipeline finished."