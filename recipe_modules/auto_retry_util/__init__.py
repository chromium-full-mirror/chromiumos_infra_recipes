# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/step',
    'cros_infra_config',
    'cros_tags',
    'exonerate',
    'exoneration_util',
    'naming',
    'skylab_results',
    'test_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'
