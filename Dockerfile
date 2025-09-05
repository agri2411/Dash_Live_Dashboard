FROM python:3.10-slim
# Set environment
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# Workdir
WORKDIR /app
# Copy files
COPY . /app
#COPY /app/key.json /app
ENV GOOGLE_APPLICATION_CREDENTIALS=/tmp/secret/key.json

# Install pip requirements
RUN pip install --upgrade pip && \
    pip install -r requirements.txt


RUN chmod 766 /app/cache/auction_data.json

EXPOSE 8050


COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Start app and refresh loop
CMD ["/app/start.sh"]
