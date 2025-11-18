FROM python:3.11-slim
WORKDIR /app
COPY analysis.py ./
RUN pip install pandas scipy statsmodels networkx snowflake-connector-python
CMD ["python", "analysis.py"]
