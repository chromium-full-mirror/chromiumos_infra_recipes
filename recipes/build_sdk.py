# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that builds a ChromiumOS SDK and cross-compilers."""

from PB.recipes.chromeos.build_sdk import BuildSDKProperties

from recipe_engine import post_process

DEPS = [
    'build_menu',
    'cros_sdk',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = BuildSDKProperties


def RunSteps(api, properties):  # pylint: disable=unused-argument
  with api.build_menu.configure_builder(missing_ok=True), \
      api.build_menu.setup_workspace_and_chroot(bootstrap_chroot=True, replace=True):
    pass


def GenTests(api):
  yield api.test('basic', api.post_check(post_process.StatusSuccess))
