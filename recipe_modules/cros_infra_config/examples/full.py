# -*- coding: utf-8 -*-
# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process

from PB.chromiumos.builder_config import BuilderConfigs
from PB.recipe_modules.chromeos.cros_infra_config.examples.full import FullProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_infra_config',
    'test_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = FullProperties


def RunSteps(api, properties):
  builder_id = api.buildbucket.build.builder

  # Verify that the config can be fetched.
  builder_config = api.cros_infra_config.get_builder_config(
      builder_id.builder, bucket=builder_id.bucket)
  api.assertions.assertEqual(builder_config.id.name, builder_id.builder)

  # Verify that the config can also be fetched without specifying the bucket.
  builder_config = api.cros_infra_config.get_builder_config(builder_id.builder)
  api.assertions.assertEqual(builder_config.id.name, builder_id.builder)

  # Verify that the config can also be fetched with an incorrect bucket
  # specified (which should fall back to querying by builder name only).
  builder_config = api.cros_infra_config.get_builder_config(
      builder_id.builder, bucket="bad-bucket")
  api.assertions.assertEqual(builder_config.id.name, builder_id.builder)

  api.cros_infra_config.force_reload()
  api.cros_infra_config.safe_get_builder_configs([builder_id])

  # Verify that the jsonpb was parsed.
  child_specs = builder_config.orchestrator.child_specs
  api.assertions.assertEqual(len(child_specs), len(properties.children_names))
  api.assertions.assertEqual([x.name for x in child_specs],
                             properties.children_names)

  _ = api.cros_infra_config.experiments_for_child_build


def GenTests(api):
  yield api.test(
      'basic',
      api.test_util.test_orchestrator().build,
      api.properties(
          FullProperties(children_names=[
              'amd64-generic-postsubmit', 'arm-generic-postsubmit',
              'grunt-postsubmit'
          ])))

  # Verify that override_builder_configs_test_data works.
  configs = BuilderConfigs()
  orch = configs.builder_configs.add()
  orch.id.name = 'postsubmit-orchestrator'
  orch.orchestrator.child_specs.add().name = 'builder1'
  yield api.test(
      'forced-config',
      api.test_util.test_orchestrator().build,
      api.cros_infra_config.override_builder_configs_test_data(configs),
      api.properties(FullProperties(children_names=['builder1'])),
      api.post_check(post_process.StatusSuccess),
  )
