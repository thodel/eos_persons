FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY build_db.py db.py server.py ./

# Build the DB first with:
#   docker run --rm -v /path/to/data:/data hbls-mcp \
#     python build_db.py --json /data/persons_resolved.json --db /data/hbls.db

EXPOSE 8003

CMD ["python", "server.py", "--db", "/data/hbls.db", "--host", "0.0.0.0", "--port", "8003"]
