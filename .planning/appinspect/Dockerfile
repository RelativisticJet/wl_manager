FROM python:3.11-slim
RUN apt-get update -qq && apt-get install -y --no-install-recommends libmagic1 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir splunk-appinspect
WORKDIR /work
ENTRYPOINT ["splunk-appinspect"]
