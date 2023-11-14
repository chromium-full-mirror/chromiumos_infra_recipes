# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/step',
    'cros_sdk',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  api.cros_sdk.create_chroot(chroot_upgrade=False)
  api.cros_sdk.update_chroot()


def GenTests(api):
  yield api.test('basic')
