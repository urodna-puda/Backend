# PŮDA POS

This is a POS tool used in a church that I frequently visit. It is a basic
restaurant cashier program with open ticket capability and storage level
keeping. What more do we need?

## Running the project

For debug:
1. Clone this repo to `git clone ~/puda-pos`
1. `cd ~/puda-pos/backend/pos` to get into the Django directory
1. `pipenv install` to install the dependencies (a virtualenv will be created
in your `~/.local/share/virtualenvs` folder. (You need to have dependencies
installed, see below)
1. `pipenv exec python startweb` to start a Django test server.

You can run Django's `manage.py` script using `pipenv exec python manage.py <command>`.

## Requirements
- `python >= 3.8.0`
- `postgresql-dev`
