# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.cros_test_proctor.proctor import ProctorProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/cq',
    'recipe_engine/step',
    'cros_bisect',
    'cros_history',
    'cros_infra_config',
    'cros_tags',
    'cros_test_plan',
    'cros_test_plan_v2',
    'easy',
    'gerrit',
    'failures',
    'naming',
    'skylab',
]

PROPERTIES = ProctorProperties
