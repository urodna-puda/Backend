FROM python:3.8.0-alpine

WORKDIR /usr/src/pos

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

COPY ./Pipfile /usr/src/pos/Pipfile
COPY ./Pipfile.lock /usr/src/pos/Pipfile.lock
RUN apk update &&\
    apk add postgresql-dev gcc python3-dev musl-dev &&\
    pip install pipenv &&\
    pipenv install

COPY . /usr/src/pos/

ENTRYPOINT ["/usr/src/pos/entrypoint.sh"]
