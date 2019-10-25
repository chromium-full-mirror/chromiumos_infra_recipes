#!/bin/bash
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Releases a CrOS infra recipe bundle to prod.
# Will release either the latest recipe bundle or the bundle indicated
# by a -i instanceid argument. The script will prompt before doing
# the release unless provided the -f argument.

function usage() {
  echo "Usage: $0 [-i instanceid] [-f]" >&2
  echo "-f bypasses the prompt" >&2
  exit 1
}

instance_id=""
prompt="yes"

while getopts "fi:" opt; do
  case $opt in
    f) prompt="no";;
    i) instance_id=$OPTARG;;
    *) usage;;
  esac
done

if [[ -z "${instance_id}" ]]; then
  instance_id=$(cipd resolve -version refs/heads/master \
    infra/recipe_bundles/chromium.googlesource.com/chromiumos/infra/recipes |\
    sed 's/^[^:]*://g' |\
    awk NF)
fi

if [[ "${prompt}" == "yes" ]]; then
  read -p "Release version ${instance_id}? (Yy) " answer

  if [[ "${answer^^}" != "Y" ]]; then
    exit 0
  fi
fi

cipd set-ref \
  infra/recipe_bundles/chromium.googlesource.com/chromiumos/infra/recipes \
  -ref="release_$(TZ='America/Los_Angeles' date +%Y/%m/%d-%H)" \
  -version="${instance_id}"

cipd set-ref \
  infra/recipe_bundles/chromium.googlesource.com/chromiumos/infra/recipes \
  -ref=prod \
  -version="${instance_id}"
