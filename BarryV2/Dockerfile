FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Make the start script executable
RUN chmod +x start.sh

ENV PYTHONUNBUFFERED=1

# Run the shell script that launches both
CMD ["./start.sh"]
