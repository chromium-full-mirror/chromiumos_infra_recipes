# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'cros_infra_config',
    'test_util',
]



def RunSteps(api):
  realms_list = api.cros_infra_config.get_realms_list()

  api.assertions.assertEqual(realms_list, ['brya-taeko', 'dedede-galnat'])


def GenTests(api):
  yield api.test('basic')
