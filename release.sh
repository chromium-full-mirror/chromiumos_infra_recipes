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
  exit 1
}

# Get the git revision associated with a cipd version (dereference it).
cipd_version_to_githash() {
  cipd describe -json-output /proc/self/fd/2 -version "$1" "${bundle}" 2>&1 > /dev/null \
    | jq -r '((.result.tags[].tag | select(startswith("git_revision"))) / ":")[1]'
}

# Get the instance id associated with ref.
cipd_ref_to_instance() {
  cipd resolve -version "$1" \
    infra/recipe_bundles/chromium.googlesource.com/chromiumos/infra/recipes | \
    sed 's/^[^:]*://g' | awk NF
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

while getopts "fi:" opt; do
  case $opt in
    f) prompt="no";;
    i) cipd_target=$OPTARG;;
    *) usage;;
  esac
done


git_prod=$(cipd_version_to_githash "prod")

if [[ -z "${cipd_target}" ]]; then
  git_target="$(cipd_version_to_githash "refs/heads/master")"
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

cipd set-ref \
  infra/recipe_bundles/chromium.googlesource.com/chromiumos/infra/recipes \
  -ref="release_$(TZ='America/Los_Angeles' date +%Y/%m/%d-%H)" \
  -version="${cipd_target}"

cipd set-ref \
  infra/recipe_bundles/chromium.googlesource.com/chromiumos/infra/recipes \
  -ref=prod \
  -version="${cipd_target}"
