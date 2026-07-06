FROM python:3.12

ENV RUNNING_IN_DOCKER=1

RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY ./src /app/src
COPY ./requirements.txt /app

RUN mkdir -p /app/data/input /app/data/output 

RUN pip install --no-cache-dir -r requirements.txt

ENTRYPOINT ["python", "src/main.py"]
