# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.cts_results_archive.cts_results_archive import \
  CTSResultsArchiveProperties

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/step',
]

PROPERTIES = CTSResultsArchiveProperties
