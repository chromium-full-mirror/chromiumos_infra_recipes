# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Deps and properties for auto_runner_util functions."""

from PB.recipe_modules.chromeos.auto_runner_util.auto_runner_util import AutoRunnerUtilProperties

DEPS = ['recipe_engine/step', 'gerrit', 'recipe_engine/time']

PROPERTIES = AutoRunnerUtilProperties
