FROM python:3.10-slim

WORKDIR /app

# Install system-level libraries required for scipy
RUN apt-get update && apt-get install -y \
	libgomp1 \
	&& rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the advanced analysis script (run_analysis.py expects to be present)
COPY run_analysis.py .

# This folder will hold the CSV outputs
RUN mkdir /app/output

ENV PYTHONUNBUFFERED=1
CMD ["python", "run_analysis.py"]
