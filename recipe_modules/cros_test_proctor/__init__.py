# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Setup for the cros_test_proctor module."""

from PB.recipe_modules.chromeos.cros_test_proctor.proctor import ProctorProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/cq',
    'recipe_engine/path',
    'recipe_engine/step',
    'recipe_engine/swarming',
    'cros_history',
    'cros_infra_config',
    'cros_tags',
    'cros_test_plan',
    'cros_test_plan_v2',
    'cros_cq_additional_tests',
    'cq_fault_attribution',
    'easy',
    'exonerate',
    'git',
    'git_footers',
    'greenness',
    'failures',
    'future_utils',
    'naming',
    'skylab',
    'skylab_results',
    'src_state',
]


PROPERTIES = ProctorProperties
