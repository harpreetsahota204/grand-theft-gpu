FROM python:3.12-slim

# Run as non-root UID 1000, matching Hugging Face Spaces container permissions.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH="/home/user/.local/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --chown=user:user requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /app/requirements.txt

COPY --chown=user:user . /app
RUN mkdir -p /app/data /app/builds

EXPOSE 7860

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "2"]
