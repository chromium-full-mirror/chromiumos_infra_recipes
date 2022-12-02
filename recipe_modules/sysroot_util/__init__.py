# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/cq',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/step',
    'android',
    'chrome',
    'cros_build_api',
    'cros_infra_config',
    'cros_sdk',
    'cros_artifacts',
    'easy',
    'failures',
    'goma',
    'workspace_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'
