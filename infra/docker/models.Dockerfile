# Embedding and rerank service on CPU, for the production stack's "models" profile.
# (On a laptop with a GPU you run this service on the host instead; see the README.)
FROM python:3.15-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/home/app/.cache/huggingface

WORKDIR /app

# The CPU build of torch is a few hundred MB instead of several GB.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch

COPY pyproject.toml ./
COPY libs ./libs
COPY services ./services
RUN pip install ".[models]"

RUN useradd --create-home app && mkdir -p /home/app/.cache && chown -R app:app /home/app
USER app
EXPOSE 8100
CMD ["uvicorn", "mindnest_models.main:app", "--host", "0.0.0.0", "--port", "8100"]
