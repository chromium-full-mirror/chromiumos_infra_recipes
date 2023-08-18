# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.auto_retry_util.auto_retry_util import AutoRetryUtilProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/cq',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_infra_config',
    'cros_tags',
    'exonerate',
    'exoneration_util',
    'gerrit',
    'git_footers',
    'naming',
    'skylab_results',
    'test_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = AutoRetryUtilProperties
