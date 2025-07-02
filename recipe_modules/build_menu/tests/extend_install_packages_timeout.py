# -*- coding: utf-8 -*-
# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for build_menu.extend_install_packages_timeout"""

from PB.recipe_modules.chromeos.build_menu.tests.test import TestProperties

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'build_menu',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = TestProperties


def RunSteps(api, properties):
  api.assertions.assertEqual(properties.extend_install_packages_timeout,
                             api.build_menu.extend_install_packages_timeout)
  # Testing boolean stickiness.
  api.build_menu.extend_install_packages_timeout = True
  api.assertions.assertTrue(api.build_menu.extend_install_packages_timeout)
  api.build_menu.extend_install_packages_timeout = False
  api.assertions.assertTrue(api.build_menu.extend_install_packages_timeout)


def GenTests(api):
  yield api.test(
      'basic',
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'with-extended_timeouts',
      api.properties(
          **{'$chromeos/build_menu': {
              "extend_install_packages_timeout": True
          }}, extend_install_packages_timeout=True),
      api.post_process(post_process.DropExpectation))
