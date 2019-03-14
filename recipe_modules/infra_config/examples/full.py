# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'infra_config',
]


def RunSteps(api):
  builder_configs = api.infra_config.get_builder_configs()

  # Sanity check that the jsonpb was parsed.
  builder_configs_list = builder_configs.builder_configs
  api.assertions.assertEqual(len(builder_configs_list), 2)
  api.assertions.assertEqual(builder_configs_list[0].id.name,
                             "amd64-generic-postsubmit")
  api.assertions.assertEqual(builder_configs_list[1].id.name,
                             "arm-generic-postsubmit")


def GenTests(api):
  yield api.test('basic')
