FROM python:3.12-slim

WORKDIR /app

# System build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install PyTorch CPU-only first (keeps image ~1.5 GB smaller than GPU build)
COPY requirements.txt .
RUN pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

# Pre-download NLTK corpora required by the engine
RUN python -c "import nltk; nltk.download('cmudict'); nltk.download('brown'); nltk.download('averaged_perceptron_tagger_eng')"

# Pre-download DistilBERT so Cloud Run cold-boots don't hit HuggingFace
RUN python -c "from transformers import pipeline; pipeline('fill-mask', model='distilbert-base-uncased', device=-1)"

# Copy application code
COPY . .

# Cloud Run injects PORT; default to 8080
ENV PORT=8080

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
