FROM python:3.11-slim
WORKDIR /app
COPY neo4j_loader.py ./
RUN pip install pandas snowflake-connector-python neo4j
CMD ["python", "neo4j_loader.py"]
