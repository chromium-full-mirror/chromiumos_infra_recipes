# Copyright 2020 The ChromiumOS Authors
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

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = CTSResultsArchiveProperties
