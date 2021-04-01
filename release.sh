#!/bin/bash
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Releases a CrOS infra recipe bundle to prod.
# Will release either the latest recipe bundle or the bundle indicated
# by a -i instanceid argument. The script will prompt before doing
# the release unless provided the -f argument.

set -e

no_changes="No changes pending."
infra_recipes_root="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
bundle=infra/recipe_bundles/chromium.googlesource.com/chromiumos/infra/recipes

function usage() {
  echo "Usage: $0 [-i instanceid] [-f]" >&2
  echo "-f bypasses the prompt" >&2
  echo "-s skips staging checks" >&2
  exit 1
}

function check_bb_auth() {
  if ! bb auth-info > /dev/null; then
    bb auth-login
  fi
}

function check_staging() {
  check_bb_auth
  checks=("staging-Annealing" "staging-StarDoctor" "staging-DutTracker"
          "staging-amd64-generic-postsubmit" "staging-RoboCrop"
          "staging-chrome-pupr-generator")
  baddies=()
  echo "Looking for 5 consecutive successes in staging."
  for name in "${checks[@]}"; do
    printf "Checking the status of: %s --> " "${name}"
    # Look for statuses that match "SUCCESS" or "FAILURE".
    statuses=$(bb ls -n 5 -json "chromeos/staging/${name}" |
      jq -r '.status|select(.|test("(SUCCESS|FAILURE)"))' |
      sort | uniq)
    # These ops first give statuses good printing, then good matching.
    statuses=$(echo "${statuses}" | tr '\n' ' ')
    echo "${statuses}"
    statuses=$(echo "${statuses}" | tr -d ' ')
    if [[ "${statuses}" != SUCCESS ]]; then
      baddies+=("${name}")
    fi
  done
  if [[ ${#baddies[@]} -ne 0 ]]; then
    echo "Please address the failures in the above builders."
    echo "When you're certain staging is OK, you may use -s to continue."
    exit 1
  fi
}

# Get the git revision associated with a cipd version (dereference it).
cipd_version_to_githash() {
  cipd describe -json-output /proc/self/fd/2 -version "$1" "${bundle}" 2>&1 > /dev/null |
    jq -r '.result.tags|map(.tag|select(startswith("git_revision:")))[0]|sub(".*:";"")'
}

# Get the instance id associated with ref.
cipd_ref_to_instance() {
  cipd resolve -version "$1" "${bundle}" | sed 's/^[^:]*://g' | awk NF
}

# Print recipe commits pending release to production.
recipe-pending() {
  changes=$(git -C "${infra_recipes_root}" log --color --graph --decorate \
            --oneline "${git_prod}".."${git_target}")

  if [ -z "${changes}" ]; then
      echo "${no_changes}"
  else
      while IFS= read -r line; do
        echo -e "  ${line}"
      done <<< "${changes}"
  fi
}

# "Main" function.
prompt="yes"
cipd_target=""

# Update to remote.
git -C "${infra_recipes_root}" remote update > /dev/null

while getopts "fi:s" opt; do
  case $opt in
    f) prompt="no";;
    i) cipd_target=$OPTARG;;
    s) skip_check="true";;
    *) usage;;
  esac
done

if [[ ! ${skip_check} == "true" ]]; then
  check_staging
fi

git_prod=$(cipd_version_to_githash "prod")

if [[ -z "${cipd_target}" ]]; then
  git_target="$(cipd_version_to_githash "refs/heads/main")"
  cipd_target=$(cipd_ref_to_instance "git_revision:${git_target}")
else
  git_target=$(cipd_version_to_githash "${cipd_target}")
fi


echo "CIPD versions can be found here: https://chrome-infra-packages.appspot.com/p/infra/recipe_bundles/chromium.googlesource.com/chromiumos/infra/recipes/+/"
printf "Here are the changes from the provided (or default main) environment:\n"
pending=$(recipe-pending)
echo "${pending}"
if [[ $pending == "$no_changes" ]]; then
    exit 0
fi

if [[ "${prompt}" == "yes" ]]; then
  read -rp "Set prod to git @ ${git_target}? (y/N): " answer
  if [[ "${answer^^}" != "Y" ]]; then
    exit 0
  fi
fi

cipd set-ref "${bundle}" -version="${cipd_target}"
  -ref="release_$(TZ='America/Los_Angeles' date +%Y/%m/%d-%H)"

cipd set-ref "${bundle}" -version="${cipd_target}" -ref=prod
