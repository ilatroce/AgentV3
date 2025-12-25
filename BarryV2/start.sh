#!/bin/bash

# Force execution from the project root (where hyperliquid_trader.py lives)
cd /app

# 1. Start Harvest (The Funding Scanner)
echo "🚜 Starting Harvest (Funding Scanner)..."
python harvest_logic/main_harvest.py &

# 2. Start Barry (The Trader)
echo "⚓ Starting Barry (Agent)..."
python BarryV2/barry.py &

# 3. Start the Dashboard
echo "📊 Starting Happy Harbor Dashboard..."
# We use 'python -m streamlit' from root, pointing to the file in BarryV2
python -m streamlit run BarryV2/dashboard.py --server.port $PORT --server.address 0.0.0.0
