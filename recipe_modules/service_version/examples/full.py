# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'service_version',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

from PB.recipe_modules.chromeos.service_version.service_version import \
  ServiceVersionProperties
from PB.test_platform import service_version


def RunSteps(api):
  api.service_version.validate_service_version_if_exists()


def GenTests(api):
  yield api.test('no service version (no validation performed)',)

  yield api.test(
      'empty service version (no validation performed)',
      api.properties(
          **{
              '$chromeos/service_version':
                  ServiceVersionProperties(
                      version=service_version.ServiceVersion())
          }))

  yield api.test(
      'good crosfleet version, bad skylab version',
      api.properties(
          **{
              '$chromeos/service_version':
                  ServiceVersionProperties(
                      version=service_version.ServiceVersion(
                          crosfleet_tool=3, skylab_tool=2))
          }))

  yield api.test(
      'bad crosfleet version, good skylab version',
      api.properties(
          **{
              '$chromeos/service_version':
                  ServiceVersionProperties(
                      version=service_version.ServiceVersion(
                          crosfleet_tool=2, skylab_tool=3))
          }))

  yield api.test(
      'bad crosfleet version, bad skylab version',
      api.properties(
          **{
              '$chromeos/service_version':
                  ServiceVersionProperties(
                      version=service_version.ServiceVersion(
                          crosfleet_tool=2, skylab_tool=2))
          }))

  yield api.test(
      'good crosfleet version, good skylab version',
      api.properties(
          **{
              '$chromeos/service_version':
                  ServiceVersionProperties(
                      version=service_version.ServiceVersion(
                          crosfleet_tool=3, skylab_tool=3))
          }))
