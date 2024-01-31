# -*- coding: utf-8 -*-

# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/assertions',
    'cros_history',
]



def RunSteps(api):
  api.assertions.assertTrue('ap-aogh' in [
      pkg.package_name for pkg in api.cros_history.get_upreved_pkgs(
          api.cros_history.test_api.build_with_uprev_response())
  ])


def GenTests(api):
  yield api.test('retrieve-upreved-pkgs')
