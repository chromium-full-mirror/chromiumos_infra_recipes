# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'infra_config',
]


def RunSteps(api):
  builder_config = api.infra_config.get_current_builder_config()

  api.assertions.assertEqual(builder_config.id.name, "postsubmit-orchestrator")

  # Sanity check that the jsonpb was parsed.
  children = builder_config.orchestrator.children
  api.assertions.assertEqual(len(children), 2)
  api.assertions.assertEqual(children[0], "amd64-generic-postsubmit")
  api.assertions.assertEqual(children[1], "arm-generic-postsubmit")


def GenTests(api):
  yield api.test('basic') + api.buildbucket.ci_build(
      project='chromeos', bucket='postsubmit',
      builder='postsubmit-orchestrator')