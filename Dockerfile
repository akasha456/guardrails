FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Download spacy model
RUN python -m spacy download en_core_web_sm

# Copy the rest of the application
COPY . .

# Expose ports for all services
EXPOSE 8501 8765 5000

# Set environment variables
ENV PYTHONUNBUFFERED=1

# The entrypoint script will be specified in docker-compose.yml