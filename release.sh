#!/bin/bash
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Releases a CrOS infra recipe bundle to prod.
# Will release either the latest recipe bundle or the bundle indicated
# by a -i instanceid argument.

function usage() {
  echo "Usage: $0 [-i instanceid]" >&2
  exit 1
}

instance_id=""

while getopts "i:" opt; do
  case $opt in
    i) instance_id=$OPTARG;;
    *) usage;;
  esac
done

if [ -z "${instance_id}" ]; then
  instance_id=$(cipd resolve -version refs/heads/master \
    infra/recipe_bundles/chromium.googlesource.com/chromiumos/infra/recipes |\
    sed 's/^[^:]*://g' |\
    awk NF)
fi

read -p "Release version ${instance_id}? (Yy) " answer

if [[  ${answer^^} != 'Y' ]]; then
  exit 0
fi

cipd set-ref \
  infra/recipe_bundles/chromium.googlesource.com/chromiumos/infra/recipes \
  -ref="release_$(TZ='America/Los_Angeles' date +%Y/%m/%d-%H)" \
  -version="${instance_id}"

cipd set-ref \
  infra/recipe_bundles/chromium.googlesource.com/chromiumos/infra/recipes \
  -ref=prod \
  -version="${instance_id}"
