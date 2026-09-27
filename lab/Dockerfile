FROM python:3.12.12-slim
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps .
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "rackops.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
