# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Setup for the tast_results module."""

from PB.recipe_modules.chromeos.tast_results.tast_results import TastResultsProperties

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/resultdb',
    'recipe_engine/step',
    'recipe_engine/swarming',
    'recipe_engine/time',
    'cros_infra_config',
    'cros_resultdb',
    'cros_tags',
    'failures_util',
]


PROPERTIES = TastResultsProperties
