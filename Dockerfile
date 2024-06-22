FROM python:3.12-slim-bullseye

RUN apt update && apt install firefox-esr -y --no-install-recommends
WORKDIR /app
COPY . .
RUN pip3 install -r requirements.txt
CMD [ "python3", "main.py"]