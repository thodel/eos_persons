FROM python:3.12-slim

WORKDIR /app

# Build context is the repository root (see docker-compose.yml):
#   docker build -f mcp_server/Dockerfile -t hgb-mcp .

# Install dependencies
COPY mcp_server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy server code; hgb_corpus.py (the corpus reader build_db.py imports from
# the repo root) goes one level up, where build_db.py looks for it.
COPY mcp_server/build_db.py mcp_server/build_identities.py mcp_server/db.py mcp_server/server.py ./
COPY hgb_corpus.py /hgb_corpus.py

# hgb.db is mounted at runtime (see docker-compose.yml). Build it first with:
#   docker run --rm -v /path/to/data:/data hgb-mcp python build_db.py --street-dir /data/street_data --db /data/hgb.db
# then load the cross-corpus identities into the same file:
#   docker run --rm -v /path/to/data:/data hgb-mcp python build_identities.py --json /data/merged_persons.json --db /data/hgb.db

EXPOSE 8000

CMD ["python", "server.py", "--db", "/data/hgb.db", "--host", "0.0.0.0", "--port", "8000"]
