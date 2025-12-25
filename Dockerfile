FROM python:3.12-slim

# Set working directory
WORKDIR /app

# --- FIX LOGGING ---
# This ensures print statements show up immediately in Railway logs
ENV PYTHONUNBUFFERED=1 
# -------------------

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy everything
COPY . .

# Permissions
RUN chmod +x BarryV2/start.sh

# Run
CMD ["./BarryV2/start.sh"]
