# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
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
  api.assertions.assertRaises(LookupError,
                              api.cros_infra_config.get_builder_config,
                              api.buildbucket.build.builder.builder)


def GenTests(api):
  yield api.test(
      'no-BuilderConfig-found',
      api.test_util.test_child_build('amd64-generic',
                                     builder='bad-builder-name').build)
