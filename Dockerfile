# Multi-stage build for ViewMaster application

# Stage 1: Build frontend
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

# Copy frontend package files (both package.json and package-lock.json)
COPY frontend/package.json frontend/package-lock.json ./

# Install frontend dependencies
RUN npm ci

# Copy frontend source files
COPY frontend/ ./

# Build frontend (outputs to ../static)
RUN npm run build

# Stage 2: Build Python backend
FROM python:3.11-slim AS backend

WORKDIR /app

# Install system dependencies if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application code
COPY app/ ./app/
COPY main.py .

# Copy built frontend from previous stage
COPY --from=frontend-builder /app/static ./static

# Create images directory and set up volume
RUN mkdir -p /app/images

# Volume for images directory (can be mounted from host)
VOLUME ["/app/images"]

# Set default images directory (can be overridden via environment variable)
ENV IMAGES_DIRECTORY=/app/images

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

