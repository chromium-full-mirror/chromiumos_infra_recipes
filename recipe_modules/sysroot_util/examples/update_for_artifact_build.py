# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/properties',
    'cros_infra_config',
    'cros_sdk',
    'sysroot_util',
]

from PB.recipe_modules.chromeos.sysroot_util.examples.test import (
    TestInputProperties)

PROPERTIES = TestInputProperties


def RunSteps(api, properties):
  name = properties.builder_name or 'orderfile-generate-toolchain'

  build_config = api.cros_infra_config.get_builder_config(name)
  artifacts = build_config.artifacts

  # Early check: this can be done before the chroot and sysroot are created.
  _ = api.sysroot_util.update_for_artifact_build(None, artifacts)

  # Later check, since some artifacts need the chroot and sysroot to be able to
  # complete their update.
  _ = api.sysroot_util.update_for_artifact_build(api.cros_sdk.chroot, artifacts,
                                                 name='final')


def GenTests(api):
  yield api.test('basic')
