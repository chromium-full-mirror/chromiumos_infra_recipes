# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/python',
    'recipe_engine/step',
    'recipe_engine/cipd',
    'recipe_engine/raw_io',
    'recipe_engine/cq',
    'recipe_engine/archive',
    'depot_tools/gsutil',
    'cros_source',
    'gerrit',
    'gitiles',
]

from PB.recipe_modules.chromeos.code_coverage.code_coverage import (
    CodeCoverageProperties)

PROPERTIES = CodeCoverageProperties
