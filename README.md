# PŮDA POS

[![pipeline status](https://gitlab.blep.cz/puda-pos/backend/badges/master/pipeline.svg)](https://gitlab.blep.cz/puda-pos/backend/-/commits/master)

This is a POS tool used in a church that I frequently visit. It is a basic
restaurant cashier program with open ticket capability and storage level
keeping. What more do we need?

## GitHub note

If you are accessing this repository via GitHub, please note that it is only a mirror
of our [GitLab repo](https://gitlab.blep.cz/puda-pos/backend). Issues in this repo
**will** be monitored, however most of the feature issues will be maintained there.
Pull requests will not be accepted through GitHub as it should remain a read-only
mirror.

## Running the project

1. Clone this repo to `~/backend`
1. Move into the Django directory: `cd ~/backend/pos`
1. Create a virtual environment: `virtualenv venv -p python3.8`
1. Activate the environment: `. venv/bin/activate`
1. Install dependencies: `pip install -r requirements.txt`
1. Start Django internal test server: `./manage.py runserver`

## Creating first user

To create the first user you have two options:
- Use Django's `cratesuperuser` command. If you use this method, the app will 
keep redirecting you back to the login form unless you explicitly go to `/admin`. 
There you need to give yourself the waiter, manager and director roles by going 
to your user and ticking the boxes.
- Use a debug-only form to create a user. The form is located at `/debug/createUser`.
It will only be there if the `DEBUG` variable is `True` (defaults to `True` outside 
Docker and to `False` when run using docker-compose). If you use this method you 
will need to give yourself the `is_staff` and `is_superuser` Django roles manually 
through the Django interactive shell or directly in the database, if you need them.
They are not used by the app and you will only need them to access Django admin for
occasional debugging. Here is a sample about how to use the shell:
```
$ ./manage.py shell
Python 3.8.0 (v3.8.0:fa919fdf25, Oct 14 2019, 10:23:27) 
[Clang 6.0 (clang-600.0.57)] on darwin
Type "help", "copyright", "credits" or "license" for more information.
(InteractiveConsole)
>>> from posapp import models
>>> me = models.User.objects.get(username="user")
>>> me.is_staff = True
>>> me.is_superuser = True
>>> me.clean()
>>> me.save()
>>> exit()
```

## Non-pip dependencies (install using your distro's package manager)

- `python3.8` and `python3.8-dev`
- `postgresql` or `postgresql-dev`
- `musl-dev`
- `libffi-dev`
- `gcc`
- `jpeg-dev`
- `zlib-dev`

## Deployment

Deploying PUDA POS is quite easy. This repository contains a `docker-compose.yml` file 
that can be used. The only changes required are in the `.env` file, you need to change
the `SECRET_KEY` variable to something, well, secret and then keep it constant when 
upgrading. If you change the key later, you risk destroying all user sessions and
password reset requests. Here is a script that is used together with Gitlab CI to deploy
out rest environments. It assumes there is a gzipped backend copied from CI, it then unpacks
said archive, changes the key and `docker-compose up`s is. Because PUDA POS stores all data
in named volumes, the `backend` folder can be safely deleted and replaced with the new version.
```bash
#!/bin/bash
SECRET_KEY="CHANGE_THIS_KEY_TO_ANYTHING_SUFFICIENTLY_LONG_AND_RANDOM"
cd ~/beta/backend
docker-compose -p pudapos down
cd ..
rm -rf backend
mkdir backend
tar -C backend -zxf backend.tar.gz
cd backend
sed -ie 's~^SECRET_KEY=.*$~SECRET_KEY='"$SECRET_KEY"'~g' .env
docker-compose -p pudapos up -d --build
```
The `backend.tar.gz` file can be downloaded from the releases tab.

It is also possible to use git to pull a new version from the repo and then use a similar
script to start it. One thing to keep in mind is to always `down` the docker before
pulling. Something might have changed in the `docker-compose.yml` file and if it did, the 
`down` will fail.

If for whatever reason you need to run multiple instances of PUDA POS, try changing the
`-p pudapos` parameter of `docker-compose` to something else, like `-p pudapos_1`.
