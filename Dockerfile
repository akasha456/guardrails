FROM python:3.11-slim

ARG GUARDRAILS_TOKEN

ENV VIRTUAL_ENV=/opt/envguardrails
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR /app


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc g++ git && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


RUN python -m nltk.downloader -d /opt/nltk_data punkt
ENV NLTK_DATA=/opt/nltk_data


RUN python -m spacy download en_core_web_sm && \
    python -m spacy link en_core_web_sm en


RUN if [ -z "$GUARDRAILS_TOKEN" ]; then \
        echo "❌ Error: GUARDRAILS_TOKEN not provided. Build with: --build-arg GUARDRAILS_TOKEN=grdk_..."; \
        exit 1; \
    fi && \
    echo "➡️ Configuring Guardrails..." && \
    guardrails configure \
        --enable-metrics \
        --enable-remote-inferencing \
        --token "$GUARDRAILS_TOKEN" && \
    echo "➡️ Installing Guardrails hub validators..." && \
    guardrails hub install hub://guardrails/toxic_language && \
    guardrails hub install hub://guardrails/profanity_free && \
    guardrails hub install hub://guardrails/detect_pii && \
    echo "✅ Guardrails configured successfully."



# Copy application code
COPY . .

CMD ["python", "--version"]