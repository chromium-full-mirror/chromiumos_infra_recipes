# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/step',
    'cros_infra_config',
    'cros_resultdb',
    'easy',
    'failures',
    'util',
]

from PB.recipe_modules.chromeos.tast_results.tast_results import (
    TastResultsProperties)

PROPERTIES = TastResultsProperties
