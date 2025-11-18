FROM python:3.11-slim
WORKDIR /app/dbt_project
COPY . .
RUN pip install --no-cache-dir dbt-snowflake
ENTRYPOINT ["dbt"]
CMD ["run", "--profiles-dir", "."]
