# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.recipe_modules.chromeos.sysroot_util.examples.test import TestInputProperties

DEPS = [
    'recipe_engine/properties',
    'cros_infra_config',
    'cros_sdk',
    'sysroot_util',
]


PROPERTIES = TestInputProperties


def RunSteps(api, properties):
  name = properties.builder_name or 'sarien-code-coverage-cq'

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
