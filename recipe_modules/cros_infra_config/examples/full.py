# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_infra_config',
    'test_util',
]

from PB.chromiumos.builder_config import BuilderConfig
from PB.recipe_modules.chromeos.cros_infra_config.examples.full import (
    FullProperties)

PROPERTIES = FullProperties


def RunSteps(api, properties):
  builder = api.buildbucket.build.builder.builder
  builder_config = api.cros_infra_config.get_builder_config(builder)
  api.cros_infra_config.force_reload()
  api.cros_infra_config.safe_get_builder_configs([builder])

  api.assertions.assertEqual(builder_config.id.name, builder)

  # Sanity check that the jsonpb was parsed.
  child_specs = builder_config.orchestrator.child_specs
  api.assertions.assertEqual(len(child_specs), len(properties.children_names))
  api.assertions.assertEqual([x.name for x in child_specs],
                             properties.children_names)


def GenTests(api):
  yield api.test(
      'basic',
      api.test_util.test_orchestrator().build,
      api.properties(
          FullProperties(children_names=[
              'amd64-generic-postsubmit', 'arm-generic-postsubmit'
          ])))
