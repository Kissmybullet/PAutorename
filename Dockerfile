FROM python:3.10-slim

# Install FFmpeg
RUN apt update && \
    apt install -y ffmpeg && \
    apt clean && \
    rm -rf /var/lib/apt/lists/*

# Explicitly set PATH to ensure FFmpeg is accessible
ENV PATH="/usr/bin:$PATH"

# Set working directory
WORKDIR /app

# Copy project files
COPY . /app

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Verify FFmpeg installation (optional, for debugging purposes)
RUN ffmpeg -version

# Start the bot
CMD ["python", "bot.py"]
