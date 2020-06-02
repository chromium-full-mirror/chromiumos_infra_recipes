# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'cros_infra_config',
    'test_util',
]


def RunSteps(api):
  api.assertions.assertRaises(LookupError,
                              api.cros_infra_config.get_builder_config,
                              api.buildbucket.build.builder.builder)


def GenTests(api):
  yield api.test('no_BuilderConfig_found',
                 api.test_util.test_build(builder='bad-builder-name').build)
