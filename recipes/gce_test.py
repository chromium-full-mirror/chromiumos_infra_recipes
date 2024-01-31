# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

""" An experimental recipe for running GCE tests."""
from typing import Generator

from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData
from PB.recipe_engine import result as result_pb2
from PB.recipes.chromeos.gce_test import GceTestProperties

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/random',
    'recipe_engine/step',
    'recipe_engine/time',
    'failures',
    'gcloud',
    'tast_exec',
    'tast_results',
]


PROPERTIES = GceTestProperties

_TEST_IMAGE_GCE_TAR = 'chromiumos_test_image_gce.tar.gz'
_IMAGE_LICENSES = [
    # Enable nested virtualization.
    'https://www.googleapis.com/compute/v1/projects/vm-options/global/licenses/enable-vmx',
]


def RunSteps(api: RecipeApi,
             properties: GceTestProperties) -> result_pb2.RawResult:
  test_artifacts_dir = api.path.mkdtemp(prefix='test-artifacts')
  api.tast_exec.download_tast(properties.build_payload, test_artifacts_dir)

  api.gcloud.set_gce_project(project=properties.gce_metadata.project)
  api.gcloud.auth_list()

  suffix = api.buildbucket.build.id
  if suffix == 0:
    # LED runs have buildbucket id=0. Use a random number.
    api.random.seed(int(api.time.time()))
    suffix = api.random.randint(1000000, 9999999)
  image = '{}-{}'.format(properties.build_target.name, suffix)
  source_uri = 'https://storage.googleapis.com/{}/{}/{}'.format(
      properties.build_payload.artifacts_gs_bucket,
      properties.build_payload.artifacts_gs_path, _TEST_IMAGE_GCE_TAR)

  api.gcloud.create_image(image, source_uri=source_uri,
                          licenses=_IMAGE_LICENSES)
  try:
    private_key_path = api.path.join(
        test_artifacts_dir,
        'autotest/utils/frozen_chromite/ssh_keys/testing_rsa',
    )
    api.tast_exec.add_ssh_key(private_key_path)
    api.tast_exec.fetch_partner_key()

    vm_context = api.tast_exec.create_gce_vm_context(
        image, project=properties.gce_metadata.project,
        zone=properties.gce_metadata.zone,
        machine=properties.gce_metadata.machine_type,
        network=properties.gce_metadata.network,
        subnet=properties.gce_metadata.subnet)

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
      results, empty_result = api.tast_exec.run_vm(
          properties.name, vm_context,
          api.tast_exec.TastInputs(properties.expressions, test_artifacts_dir,
                                   properties.build_payload,
                                   shard_args=shard_args))

    api.tast_results.print_results(results.failures, empty_result)

    return api.failures.aggregate_failures(results)
  finally:
    with api.failures.ignore_exceptions():
      api.gcloud.delete_image(image)


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  props = api.properties(
      build_target={'name': 'board'}, build_payload={
          'artifacts_gs_bucket': 'artifacts-bucket',
          'artifacts_gs_path': 'artifacts-path',
      }, expressions=['expr'], gce_metadata={
          'project': 'project',
          'zone': 'zone',
          'machine_type': 'machine-type',
          'network': 'network',
          'subnet': 'subnet',
      })

  yield api.test('basic', props, api.buildbucket.generic_build())

  yield api.test(
      'forgives-delete-image-failure',
      props,
      api.buildbucket.generic_build(),
      api.step_data('delete image', retcode=1),
      api.step_data('delete image (2)', retcode=1),
  )

  yield api.test('led-build', props, api.buildbucket.generic_build(build_id=0))

  yield api.test('sharded', api.buildbucket.generic_build(build_id=0), props,
                 api.properties(total_shards=2, shard_index=0))

  yield api.test(
      'sharded-hashed', api.buildbucket.generic_build(build_id=0), props,
      api.properties(total_shards=2, shard_index=0, shard_method='hash'))
