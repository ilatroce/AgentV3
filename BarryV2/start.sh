#!/bin/bash

# 1. Start Barry (Trend Follower)
echo "⚓ Starting Barry (Agent)..."
python barry.py &

# 2. Start Harvest (Funding Scanner) - NEW
echo "🚜 Starting Harvest (Funding Scanner)..."
python harvest_logic/main_harvest.py &

# 3. Start the Dashboard in the foreground
echo "📊 Starting Happy Harbor Dashboard..."
python -m streamlit run dashboard.py --server.port $PORT --server.address 0.0.0.0
