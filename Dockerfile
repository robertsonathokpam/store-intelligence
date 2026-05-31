
# Use an official Python runtime as a parent image
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the app code
COPY app/ .

# Create data directory for POS transaction files
RUN mkdir -p data

# Copy POS transaction data for conversion-rate correlation (if available)
# Use a shell form to handle cases where hackathon-resources may not exist
COPY hackathon-resource[s]/*.csv data/

# Copy the tests code
COPY tests/ tests/

# Command to run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]