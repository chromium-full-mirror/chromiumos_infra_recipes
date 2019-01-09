#!/bin/bash -e

led auth-info || {
  echo 'Run `led auth-login`'
  exit 1
}

# Change to repo root.
cd "$(dirname "$(readlink -f "$0")")/.." || exit 2

led get-builder 'luci.chromeos.prototype:Mini-annealing' | \
  led edit-recipe-bundle | \
  led launch || exit 3
