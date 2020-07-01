#!/bin/sh

./manage.py shell << EOF | xargs -I {} ./manage.py graph_transitions -o posapp/fsm_graphs/{}.png posapp.{}
import django_fsm
import inspect
import sys

classes = []

for _, cls in inspect.getmembers(sys.modules["posapp.models"], inspect.isclass):
    if cls.__module__ == "posapp.models":
        for member in inspect.getmembers(cls):
            if not member[0].startswith("_"):
                if type(member[1]) == django_fsm.FSMFieldDescriptor:
                    classes.append(f"{cls.__name__}")

for cls in classes:
    print(cls)
EOF
