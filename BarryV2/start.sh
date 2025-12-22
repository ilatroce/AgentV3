#!/bin/bash

# Start the Trading Bot in the background
echo "⚓ Starting Barry (Agent)..."
python barry.py &

# Start the Dashboard in the foreground
echo "📊 Starting Happy Harbor Dashboard..."
streamlit run dashboard.py --server.port $PORT --server.address 0.0.0.0
