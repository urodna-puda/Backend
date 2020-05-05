FROM python:3.8.0-alpine

WORKDIR /usr/src/pos

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

RUN apk update &&\
    apk add postgresql-dev gcc python3-dev musl-dev libffi-dev git

RUN pip install --upgrade pip
COPY ./requirements.txt /usr/src/pos/requirements.txt
RUN pip install -r requirements.txt

COPY . /usr/src/pos/

ENTRYPOINT ["/usr/src/pos/entrypoint.sh"]
