#!/bin/bash
cd /app

# Start Harvest (Scanner)
echo "🚜 Starting Harvest..."
python harvest_logic/main_harvest.py &

# Start Barry (Trader)
echo "⚓ Starting Barry..."
python BarryV2/barry.py &

# Start Dashboard
echo "📊 Starting Dashboard..."
python -m streamlit run BarryV2/dashboard.py --server.port $PORT --server.address 0.0.0.0
