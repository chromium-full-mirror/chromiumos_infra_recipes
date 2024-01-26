# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Setup for the cts_results_archive module."""

from PB.recipe_modules.chromeos.cts_results_archive.cts_results_archive import \
  CTSResultsArchiveProperties

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/buildbucket',
    'recipe_engine/json',
    'recipe_engine/step',
    'cros_tags',
]


PROPERTIES = CTSResultsArchiveProperties
