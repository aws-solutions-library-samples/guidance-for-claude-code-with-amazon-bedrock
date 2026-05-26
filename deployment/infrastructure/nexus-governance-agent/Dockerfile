FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
ENV NEXUS_API_URL=''
ENV AWS_REGION=us-east-1
ENV POLICIES_TABLE=QuotaPolicies
ENV METRICS_TABLE=ClaudeCodeMetrics
EXPOSE 8080
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "main:app"]
