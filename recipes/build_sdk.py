# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe that builds a ChromiumOS SDK and cross-compilers."""

from PB.recipes.chromeos.build_sdk import BuildSDKProperties

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = BuildSDKProperties


def RunSteps(api, properties):  # pylint: disable=unused-argument
  pass


def GenTests(api):
  yield api.test('basic')
