#!/bin/bash

curl 'https://chat.googleapis.com/v1/spaces/AAAAjzRh34M/messages?key=AIzaSyDdI0hCZtE6vySjMm-WEfRq3CPzqKqqsHI&token=teFwsOpYB8z-yD9n1gzsgSS8Zuf_5-dhvFwIbYKaGd0%3D' -H 'Content-type: application/json' -d '{"text": "'"${USER} is launching a prototype build"'"}' > /dev/null || echo 'Notify failed!'

# Change to repo root.
cd "$(dirname "$(readlink -f "$0")")/.." || exit 1

./recipes.py bundle

cipd create -in bundle -name infra/recipe_bundles/chromium.googlesource.com/chromiumos/infra/recipes -ref prototype

if [ "$1" == "run" ]; then
  buildbucket.py put -b luci.chromeos.prototype -n Prototype
fi
