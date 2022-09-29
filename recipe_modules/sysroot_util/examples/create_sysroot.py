# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.chromiumos.common import BuildTarget
from PB.recipe_modules.chromeos.sysroot_util.examples.test import TestInputProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_infra_config',
    'sysroot_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = TestInputProperties


def RunSteps(api, properties):
  name = properties.builder_name or 'orderfile-generate-toolchain'

  _ = api.cros_infra_config.get_builder_config(name)

  sysroot = api.sysroot_util.create_sysroot(BuildTarget(name='eve'))
  api.assertions.assertEqual(sysroot, api.sysroot_util.sysroot)

  api.sysroot_util.bootstrap_sysroot()


def GenTests(api):
  yield api.test('basic')
