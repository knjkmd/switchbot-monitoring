FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY collector.py metrics.py ./
USER 10001:10001
CMD ["python", "-u", "collector.py"]
