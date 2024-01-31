# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.cros_test_platform.cros_test_platform import \
    CrosTestPlatformModuleProperties

DEPS = [
    'cros_infra_config',
    'easy',
    'recipe_engine/buildbucket',
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/step',
]


PROPERTIES = CrosTestPlatformModuleProperties
