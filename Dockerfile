# ── Stage 1: Build PhoneInfoga binary ────────────────────────────────────────
FROM golang:1.20-alpine AS phoneinfoga_builder

RUN apk add --no-cache git make bash build-base nodejs npm yarn unzip

WORKDIR /build
COPY phoneinfoga-master.zip .
RUN unzip phoneinfoga-master.zip

WORKDIR /build/phoneinfoga-master

# Build frontend (if client dir exists)
RUN if [ -d "web/client" ]; then \
      cd web/client && yarn install --immutable && yarn build && yarn cache clean; \
    fi

# Build Go binary
RUN go get -v -t -d ./... && \
    CGO_ENABLED=0 GOOS=linux go build -o /bin/phoneinfoga .


# ── Stage 2: Install holehe from zip ─────────────────────────────────────────
FROM python:3.11-slim AS holehe_builder

WORKDIR /holehe
COPY holehe-master.zip .
RUN apt-get update && apt-get install -y --no-install-recommends unzip && \
    unzip holehe-master.zip && \
    pip install --no-cache-dir ./holehe-master && \
    rm -rf holehe-master holehe-master.zip

# ── Stage 3: Final image ──────────────────────────────────────────────────────
FROM python:3.11-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    supervisor curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy PhoneInfoga binary
COPY --from=phoneinfoga_builder /bin/phoneinfoga /usr/local/bin/phoneinfoga

# Copy holehe from builder
COPY --from=holehe_builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir dnspython python-whois httpx trio tqdm termcolor bs4 colorama

# Copy application
COPY . .

# Supervisor config
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Create required dirs
RUN mkdir -p logs data

EXPOSE 5000

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
