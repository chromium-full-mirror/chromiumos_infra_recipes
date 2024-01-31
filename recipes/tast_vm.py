# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

""" An experimental recipe for running Tast VM tests without Chroot and
    ChromeOS checkout, resulting in much faster tests. The tests will
    use tast executable from build_artifacts.
"""

from PB.recipes.chromeos.tast_vm import TastVmProperties
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'bot_scaling',
    'cros_infra_config',
    'failures',
    'tast_exec',
]


PROPERTIES = TastVmProperties


def RunSteps(api: RecipeApi, properties: TastVmProperties):

  if api.cros_infra_config.is_staging:  #pragma: no cover
    api.bot_scaling.drop_cpu_cores(min_cpus_left=2, max_drop_ratio=.90)

  test_artifacts_dir = api.path.mkdtemp(prefix='test-artifacts')
  api.tast_exec.download_tast(properties.build_payload, test_artifacts_dir)

  image_archive_dir = api.path.mkdtemp(prefix='image-archive')
  qcow_image_path = api.tast_exec.download_vm(properties.build_payload,
                                              image_archive_dir)
  vm_context = api.tast_exec.create_qemu_vm_context(qcow_image_path)
  # Only specify shards if there is more than 1.
  shard_args = []
  if properties.total_shards > 1:
    shard_args.extend([
        '-totalshards={}'.format(properties.total_shards),
        '-shardindex={}'.format(properties.shard_index)
    ])
  if properties.shard_method:
    shard_args.extend(['-shardmethod={}'.format(properties.shard_method)])

  with api.step.nest('run tast tests'):
    results, _ = api.tast_exec.run_vm(
        properties.name, vm_context,
        api.tast_exec.TastInputs(properties.expressions, test_artifacts_dir,
                                 properties.build_payload,
                                 shard_args=shard_args))

  return api.failures.aggregate_failures(results)


def GenTests(api: RecipeTestApi):
  yield api.test(
      'basic',
      api.properties(
          expressions=['expr'], build_payload={
              'artifacts_gs_bucket': 'artifacts-bucket',
              'artifacts_gs_path': 'artifacts-path'
          }))

  yield api.test(
      'sharded',
      api.properties(
          expressions=['expr'], build_payload={
              'artifacts_gs_bucket': 'artifacts-bucket',
              'artifacts_gs_path': 'artifacts-path'
          }, total_shards=2, shard_index=0))

  yield api.test(
      'hash-sharded',
      api.properties(
          expressions=['expr'], build_payload={
              'artifacts_gs_bucket': 'artifacts-bucket',
              'artifacts_gs_path': 'artifacts-path'
          }, total_shards=2, shard_index=1, shard_method='hash'))
