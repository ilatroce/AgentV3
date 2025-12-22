# Use a stable, lightweight official Python image
# We use 3.12 to be safe, but you can change to 3.13 if strictly needed.
FROM python:3.12-slim

# Set the working directory in the cloud
WORKDIR /app

# Copy the requirements file first (for caching speed)
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your code
COPY . .

# Command to run the bot
CMD ["python", "main.py"]
