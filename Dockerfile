FROM python:3.13-slim

WORKDIR /app

COPY . .

RUN pip install -r requirement.txt

CMD [ "python", '-m', 'app' ]