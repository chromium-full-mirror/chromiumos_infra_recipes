# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'cros_sdk',
    'cros_source',
    'depot_tools/gsutil',
    'gitiles',
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/python',
    'recipe_engine/step',
]

from PB.recipe_modules.chromeos.code_coverage.code_coverage import (
    CodeCoverageProperties)

PROPERTIES = CodeCoverageProperties
