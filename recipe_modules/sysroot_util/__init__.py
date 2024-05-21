# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Init for sysroot_util module."""

from PB.recipe_modules.chromeos.sysroot_util.sysroot_util import SysrootUtilProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/cv',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/step',
    'recipe_engine/time',
    'android',
    'chrome',
    'cros_artifacts',
    'cros_build_api',
    'cros_infra_config',
    'cros_relevance',
    'cros_sdk',
    'cros_source',
    'easy',
    'goma',
    'image_builder_failures',
    'remoteexec',
    'src_state',
    'workspace_util',
]


PROPERTIES = SysrootUtilProperties
