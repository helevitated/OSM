# Use the official Python slim image for a smaller footprint
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies needed for compiling certain python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install dependencies, ensuring we grab the CPU-only version of PyTorch to save space
RUN pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

# Pre-download the DistilBERT model into the image during build
# This ensures Cloud Run can cold-boot instantly without downloading the 260MB model on the first request
RUN python -c "from transformers import pipeline; pipeline('fill-mask', model='distilbert-base-uncased', device=-1)"

# Copy the rest of the application
COPY . .

# Cloud Run expects the app to listen on the port specified by the PORT environment variable
ENV PORT=8080

# Command to run the application using Uvicorn
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
