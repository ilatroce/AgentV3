# Use Python 3.12
FROM python:3.12-slim

# Set the working directory to /app
WORKDIR /app

# Copy requirements from the root directory
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# COPY EVERYTHING (BarryV2, harvest_logic, hyperliquid_trader.py) into /app
COPY . .

# Make the start script executable
RUN chmod +x BarryV2/start.sh

# Run the start script
CMD ["./BarryV2/start.sh"]
