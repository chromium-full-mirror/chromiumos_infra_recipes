#!/bin/bash

# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


main() {

  if [[ $# -ne 1 ]]; then
    cat <<EOF >&2
USAGE: $0 <path>

A wrapper around 'sudo umount <path>' that provides diagnostics on failure.
EOF
    exit 1
  fi

  # Remove mount_path, use below with 'sudo umount'.
  local mount_path="$1"
  shift 1

  # -l means umount will be done as soon as filesystem is not busy anymore.
  sudo umount -l "${mount_path}"

  err=$?
  if [[ $err -ne 0 ]]; then
    # umount was not successful, provide diagnostics.
    set -x
    sudo fuser "${mount_path}"
    sudo lsof "${mount_path}"
    sudo losetup -a
    ps auxf
    set +x
    exit $err
  fi
}

main "$@"
