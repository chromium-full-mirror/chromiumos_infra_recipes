# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.cros_test_proctor.proctor import ProctorProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/cq',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/step',
    'cros_bisect',
    'cros_history',
    'cros_infra_config',
    'cros_tags',
    'cros_test_plan',
    'cros_test_plan_v2',
    'easy',
    'git',
    'gitiles',
    'gerrit',
    # TODO(b/201608160): Remove dependency upon completion of experiment.
    'git_footers',
    'greenness',
    'failures',
    'naming',
    'skylab',
    'src_state',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2'

PROPERTIES = ProctorProperties
