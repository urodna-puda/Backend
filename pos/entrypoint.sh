#!/bin/sh

if [ "$DATABASE" = "postgres" ]
then
    echo "Waiting for postgres..."

    while ! nc -z $SQL_HOST $SQL_PORT; do
      sleep 0.1
    done

    echo "PostgreSQL started"
fi

if [ "$DJANGO_TASKS" = "yes" ]
then
  pipenv run python manage.py migrate
  pipenv run python manage.py collectstatic --no-input --clear
fi

pipenv run $@
