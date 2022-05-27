#!/bin/bash
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Releases a CrOS infra recipe bundle to prod.
# Will release either the latest recipe bundle or the bundle indicated
# by a -i instanceid argument. The script will prompt before doing
# the release unless provided the -f argument.
#
# By default, we grep out the trivial recipe rolls to provide a cleaner output,
# this can be bypassed with the -v option

set -eu

no_changes="No changes pending."
infra_recipes_root="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
bundle=infra/recipe_bundles/chromium.googlesource.com/chromiumos/infra/recipes

if ! type jq >/dev/null; then
  echo "Please install jq, on debian:"
  printf "\tsudo apt install jq\n"
  exit 1
fi

function usage() {
  echo "Usage: $0 [-i instanceid] [-f]" >&2
  echo "-i pass in instanceid tied to a commit to release up that commit" >&2
  echo "   instanceids are found at https://chrome-infra-packages.appspot.com/p/infra/recipe_bundles/chromium.googlesource.com/chromiumos/infra/recipes/+/" >&2
  echo "   click into an instance to see the commit attached to it" >&2
  echo "-f bypasses the prompt" >&2
  echo "-s skips staging checks" >&2
  echo "-v prints all pending changes, including trivial recipe rolls" >&2
  exit 1
}

function urlencode() {
  # The sed magic strips color codes.
  echo "$1" | sed 's/\x1b\[[0-9;]*m//g' | jq -sRr @uri
}

function check_bb_auth() {
  if ! bb auth-info > /dev/null; then
    bb auth-login
  fi
}

function check_staging() {
  ignore_errors="${1}"
  check_bb_auth
  checks=("staging-Annealing" "staging-StarDoctor" "staging-DutTracker"
          "staging-amd64-generic-postsubmit" "staging-RoboCrop"
          "staging-chrome-pupr-generator" "staging-backfiller"
          "staging-manifest-doctor" "staging-release-main-orchestrator"
          "LegacyNoopSuccess")
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
    if [[ -n ${ignore_errors} ]]; then
      echo "Ignoring errors in builders, as requested."
    else
      echo "Please address the failures in the above builders."
      echo "When you're certain staging is OK, you may use -s to continue."
      return 1
    fi
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
  log_fmt="%C(bold blue)%h %C(bold green)[%al]%C(auto)%d %C(reset)%s"
  changes=$(git -C "${infra_recipes_root}" log --color --graph --decorate \
      --pretty=format:"${log_fmt}" "${git_prod}".."${git_target}")

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
skip_staging_check=""
verbose=""

# Update to remote.
git -C "${infra_recipes_root}" remote update > /dev/null

while getopts "fi:sv" opt; do
  case $opt in
    f) prompt="no";;
    i) cipd_target=$OPTARG;;
    s) skip_staging_check="yes";;
    v) verbose="yes";;
    *) usage;;
  esac
done

git_prod=$(cipd_version_to_githash "prod")

if [[ -z "${cipd_target}" ]]; then
  git_target="$(cipd_version_to_githash "refs/heads/main")"
  cipd_target=$(cipd_ref_to_instance "git_revision:${git_target}")
else
  git_target=$(cipd_version_to_githash "${cipd_target}")
fi


echo "CIPD versions can be found here: https://chrome-infra-packages.appspot.com/p/infra/recipe_bundles/chromium.googlesource.com/chromiumos/infra/recipes/+/"
echo

echo "=== Checking for pending changes ==="
printf "Here are the changes from the provided (or default main) environment:\n"

if [[ "${verbose}" == "yes" ]]; then
    printf " - Verbose specified, printing all changes\n"
    pending=$(recipe-pending)
else
    pending=$(recipe-pending | grep -vE "Roll recipe.*\(trivial\)\.?$")
fi
echo "${pending}"
echo

echo "=== Checking staging status ==="
check_staging "${skip_staging_check}"

if [[ $pending == "$no_changes" ]]; then
    echo "No changes pending. Exiting early."
    exit 0
fi

if [[ "${prompt}" == "yes" ]]; then
  read -rp "Set prod to git @ ${git_target}? (y/N): " answer
  if [[ "${answer^^}" != "Y" ]]; then
    exit 0
  fi
fi

cipd set-ref "${bundle}" -version="${cipd_target}" \
  -ref="release_$(TZ='America/Los_Angeles' date +%Y/%m/%d-%H)"

cipd set-ref "${bundle}" -version="${cipd_target}" -ref=prod

email_subject="Recipes Release - $(TZ='America/Los_Angeles' date)"
email_message="We've deployed Recipes to prod!

Here is a summary of the changes:

${pending}"

email_link="https://mail.google.com/mail/?view=cm&fs=1&bcc=chromeos-infra-releases@google.com&to=chromeos-continuous-integration-team@google.com&su=$(urlencode "${email_subject}")&body=$(urlencode "${email_message}")"

echo
echo "Please click this link and send an email to chromeos-infra-releases!"
echo
echo "${email_link}"
