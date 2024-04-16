# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Code coverage module."""

from PB.recipe_modules.chromeos.code_coverage.code_coverage import CodeCoverageProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/step',
    'recipe_engine/cipd',
    'recipe_engine/raw_io',
    'recipe_engine/cv',
    'recipe_engine/archive',
    'recipe_engine/time',
    'depot_tools/gsutil',
    'cros_source',
    'gitiles',
    'cros_infra_config',
    'gerrit',
    'easy',
]


PROPERTIES = CodeCoverageProperties
