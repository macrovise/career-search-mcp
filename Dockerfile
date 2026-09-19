FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir --upgrade "pip>=26.2" && pip install --no-cache-dir . && mkdir /data && chown 1000:1000 /data
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CAREER_DB_PATH=/data/career.sqlite3
EXPOSE 8383
USER 1000:1000
CMD ["career-search-mcp"]
