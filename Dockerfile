FROM python:3.10-slim
RUN apt update && apt install -y gcc
COPY bgmi-killer /app/
COPY api.py /app/
COPY requirements.txt /app/
WORKDIR /app
RUN chmod +x bgmi-killer
RUN pip install -r requirements.txt
EXPOSE 8080
CMD ["python", "api.py"]
