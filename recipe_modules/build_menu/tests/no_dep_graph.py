# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/swarming',
    'build_menu',
    'test_util',
]

from PB.chromiumos import common


def RunSteps(api):
  build_target = common.BuildTarget(name='amd64-generic')

  with api.build_menu.configure_builder(build_target), \
      api.build_menu.setup_workspace_and_chroot():
    pass

  # If we never call setup_sysroot_and_determine_relevance, we still get a
  # dep_graph (and therefore have validated the SDK for reuse.)
  api.assertions.assertIsNotNone(api.build_menu.dep_graph)


def GenTests(api):

  yield api.test(
      'cq-build',
      api.swarming.properties(
          bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.test_util.test_child_build('amd64-generic', cq=True).build)

  yield api.test(
      'staging-cq-build',
      api.swarming.properties(
          bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
      api.test_util.test_child_build('amd64-generic', cq=True).build)
