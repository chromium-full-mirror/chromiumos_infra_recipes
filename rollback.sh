#!/bin/bash
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Used to rollback a CrOS infra recipe release. The instance to
# rollback to is indicated by the -i argument. The ref to rollback
# is indicated by the -r argument (current options are "prod" and
# "release-prod"). The script will prompt before doing the rollback unless
# provided the -f argument.

function usage() {
  echo "Usage: $0 -i instanceid -r ref [-f]" >&2
  echo "current options for ref are 'prod' and 'release-prod'" >&2
  echo "-f bypasses the prompt" >&2
  exit 1
}

instance_id=""
ref=""
prompt="yes"

while getopts "fi:r:" opt; do
  case ${opt} in
    f) prompt="no";;
    i) instance_id=${OPTARG};;
    r) ref=${OPTARG};;
    *) usage;;
  esac
done

if [[ -z "${instance_id}" ]]; then
  usage
fi

if [[ -z "${ref}" ]]; then
  usage
fi

if [[ "${ref}" != "prod" && "${ref}" != "release-prod" ]]; then
  usage
fi

if [[ "${prompt}" == "yes" ]]; then
  read -r -p "Rollback ref ${ref} to version ${instance_id}? (Yy) " answer

  if [[ "${answer^^}" != "Y" ]]; then
    exit 0
  fi
fi

cipd set-ref \
  infra/recipe_bundles/chromium.googlesource.com/chromiumos/infra/recipes \
  -ref="${ref}" \
  -version="${instance_id}"
