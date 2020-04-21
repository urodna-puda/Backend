# PŮDA POS

This is a POS tool used in a church that I frequently visit. It is a basic
restaurant cashier program with open ticket capability and storage level
keeping. What more do we need?

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
