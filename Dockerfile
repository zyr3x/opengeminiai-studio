# Use an official Python runtime as a parent image
FROM python:3.12-slim-bullseye

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt


# Make port 8080 available to the world outside this container
EXPOSE 8080

# Run the application
# Note: You MUST provide the API_KEY environment variable when running the container.
# Example: docker run -p 8081:8081 -e API_KEY="YOUR_GEMINI_API_KEY" gemini-proxy
CMD ["python", "gemini-proxy.py"]