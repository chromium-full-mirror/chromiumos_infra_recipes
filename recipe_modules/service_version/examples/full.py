# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'service_version',
]

from PB.recipe_modules.chromeos.service_version.service_version import \
  ServiceVersionProperties
from PB.test_platform import service_version


def RunSteps(api):
  api.service_version.validate_skylab_version()


def GenTests(api):
  yield api.test(
      'valid skylab version',
      api.properties(
          **{
              '$chromeos/service_version':
                  ServiceVersionProperties(
                      version=service_version.ServiceVersion(skylab_tool=1))
          }))

  yield api.test(
      'invalid skylab version',
      api.properties(
          **{
              '$chromeos/service_version':
                  ServiceVersionProperties(
                      version=service_version.ServiceVersion(skylab_tool=0))
          }))

  yield api.test('missing skylab version')
