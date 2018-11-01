#!/bin/sh
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

HERE="$(dirname "$(readlink -f "$0")")"
WORKDIR="${HERE}/workdir"

mkdir -p "${WORKDIR}"
./recipes.py run --workdir "${WORKDIR}" prototype
