# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.recipe_modules.chromeos.cros_relevance.examples.toolchain import ToolchainTest

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_relevance',
]


PROPERTIES = ToolchainTest


def RunSteps(api, properties):

  api.cros_relevance.toolchain_cls_applied = \
    properties.expected_toolchain_changed
  api.assertions.assertEqual(properties.expected_toolchain_changed,
                             api.cros_relevance.toolchain_cls_applied)


def GenTests(api):

  yield api.test(
      'no-cls', api.properties(ToolchainTest(expected_toolchain_changed=False)))

  yield api.test('test-value', api.cros_relevance.toolchain_cls_applied(True),
                 api.properties(ToolchainTest(expected_toolchain_changed=True)))
