# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.recipe_modules.chromeos.service_version.service_version import ServiceVersionProperties
from PB.test_platform import service_version

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'service_version',
]



def RunSteps(api):
  api.service_version.validate_service_version_if_exists()


def GenTests(api):
  yield api.test('no-service-version-no-validation-performed',)

  yield api.test(
      'empty-service-version-no-validation-performed',
      api.properties(
          **{
              '$chromeos/service_version':
                  ServiceVersionProperties(
                      version=service_version.ServiceVersion())
          }))

  yield api.test(
      'good-crosfleet-version-bad-skylab-version',
      api.properties(
          **{
              '$chromeos/service_version':
                  ServiceVersionProperties(
                      version=service_version.ServiceVersion(
                          crosfleet_tool=4, skylab_tool=3))
          }),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'bad-crosfleet-version-good-skylab-version',
      api.properties(
          **{
              '$chromeos/service_version':
                  ServiceVersionProperties(
                      version=service_version.ServiceVersion(
                          crosfleet_tool=3, skylab_tool=4))
          }),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'bad-crosfleet-version-bad-skylab-version',
      api.properties(
          **{
              '$chromeos/service_version':
                  ServiceVersionProperties(
                      version=service_version.ServiceVersion(
                          crosfleet_tool=3, skylab_tool=3))
          }),
      # TODO (b/275363240): audit this test.
      status='FAILURE',
  )

  yield api.test(
      'good-crosfleet-version-good-skylab-version',
      api.properties(
          **{
              '$chromeos/service_version':
                  ServiceVersionProperties(
                      version=service_version.ServiceVersion(
                          crosfleet_tool=4, skylab_tool=4))
          }))
