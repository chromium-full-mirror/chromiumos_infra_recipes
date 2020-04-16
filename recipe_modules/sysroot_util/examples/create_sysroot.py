# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'recipe_engine/properties',
    'cros_infra_config',
    'cros_sdk',
    'sysroot_util',
]

from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import PrepareForBuildResponse
from PB.recipe_modules.chromeos.sysroot_util.examples.test import (
    TestInputProperties)

PROPERTIES = TestInputProperties


def RunSteps(api, properties):
  name = properties.builder_name or 'orderfile-generate-toolchain'

  build_config = api.cros_infra_config.get_builder_config(name)

  sysroot = api.sysroot_util.create_sysroot(BuildTarget(name='eve'))
  api.assertions.assertEqual(sysroot, api.sysroot_util.sysroot)

def GenTests(api):
  yield api.test('basic')
