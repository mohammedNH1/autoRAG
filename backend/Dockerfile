FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Copy your Django project files into the container
COPY . .

# Start Django dev server on all interfaces
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
