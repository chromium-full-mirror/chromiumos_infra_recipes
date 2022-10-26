# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

""" An experimental recipe for running Tast VM tests without Chroot and
    ChromeOS checkout, resulting in much faster tests. The tests will
    use tast executable from build_artifacts.
"""

from PB.recipes.chromeos.tast_vm import TastVmProperties

DEPS = [
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'failures',
    'tast_exec',
    'tast_results',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = TastVmProperties


def RunSteps(api, properties):
  test_artifacts_dir = api.path.mkdtemp(prefix='test-artifacts')
  api.tast_exec.download_tast(properties.build_payload, test_artifacts_dir)

  image_archive_dir = api.path.mkdtemp(prefix='image-archive')
  qcow_image_path, private_key_path = api.tast_exec.download_vm(
      properties.build_payload, image_archive_dir)
  vm_context = api.tast_exec.create_qemu_vm_context(qcow_image_path,
                                                    private_key_path)
  # Only specify shards if there is more than 1.
  shard_args = []
  if properties.total_shards > 1:
    shard_args.extend([
        '-totalshards={}'.format(properties.total_shards),
        '-shardindex={}'.format(properties.shard_index)
    ])

  with api.step.nest('run tast tests'):
    failures, empty_result = api.tast_exec.run_vm(
        properties.name, vm_context,
        api.tast_exec.TastInputs(properties.expressions, test_artifacts_dir,
                                 properties.build_payload, private_key_path,
                                 shard_args=shard_args))

  api.tast_results.print_results(failures, empty_result)

  return api.failures.aggregate_failures(failures)


def GenTests(api):
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
