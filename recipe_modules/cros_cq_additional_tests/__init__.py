# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.cros_cq_additional_tests.cros_cq_additional_tests import CrosCQAdditionalTestsProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/step',
    'cros_infra_config',
    'cros_source',
    'easy',
    'git',
    'gitiles',
    'repo',
    'src_state',
    'git_footers',
]


PROPERTIES = CrosCQAdditionalTestsProperties
