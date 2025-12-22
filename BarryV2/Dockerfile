FROM python:3.12-slim

# Set working directory
WORKDIR /app

# COPY requirements first
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the code
COPY . .

# --- THE FIX IS HERE ---
# This forces Python to print logs to Railway immediately
ENV PYTHONUNBUFFERED=1

# Run the bot
CMD ["python", "main.py"]
