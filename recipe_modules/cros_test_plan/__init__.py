# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Functions for end-to-end test planning."""

from PB.recipe_modules.chromeos.cros_test_plan.cros_test_plan import CrosTestPlanProperties

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
    'gobin',
    'repo',
    'src_state',
]


PROPERTIES = CrosTestPlanProperties
