FROM python:3.12-alpine

# Set environment
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=America/Sao_Paulo

# Install system dependencies (tzdata for accurate Brazil timezone handling)
RUN apk add --no-cache tzdata

WORKDIR /app

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Ensure entrypoint is executable
RUN chmod +x entrypoint.sh

# Expose web interface port
EXPOSE 3456

ENTRYPOINT ["/app/entrypoint.sh"]
