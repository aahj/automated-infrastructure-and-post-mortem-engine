FROM python:3.13-slim as base
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir uv

FROM base as api
COPY main.py ./
COPY src ./src
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base as worker
COPY worker.py ./
COPY src ./src
ENV PYTHONUNBUFFERED=1
CMD ["python", "worker.py"]

FROM base as tests
COPY src ./src
COPY tests ./tests
ENV PYTHONUNBUFFERED=1
