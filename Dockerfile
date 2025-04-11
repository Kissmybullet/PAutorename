FROM python:3.10-slim

# Install FFmpeg
RUN apt update && \
    apt install -y ffmpeg && \
    apt clean && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy project files
COPY . /app

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Optionally verify FFmpeg installation
RUN ffmpeg -version

# Start the bot
CMD ["python", "bot.py"]
