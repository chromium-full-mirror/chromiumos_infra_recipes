#!/bin/bash
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Used to rollback a CrOS infra recipe release. The bundle to
# rollback to is indicated by a -i instanceid argument. The script
# will prompt before doing the rollback unless provided the -f argument.

function usage() {
  echo "Usage: $0 -i instanceid [-f]" >&2
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
  usage
fi

if [[ "${prompt}" == "yes" ]]; then
  read -p "Rollback to version ${instance_id}? (Yy) " answer

  if [[ "${answer^^}" != "Y" ]]; then
    exit 0
  fi
fi

cipd set-ref \
  infra/recipe_bundles/chromium.googlesource.com/chromiumos/infra/recipes \
  -ref=prod \
  -version="${instance_id}"
