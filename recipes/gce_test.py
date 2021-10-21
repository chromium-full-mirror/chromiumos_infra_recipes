# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

""" An experimental recipe for running GCE tests."""

from PB.recipes.chromeos.gce_test import GceTestProperties

DEPS = [
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


def RunSteps(api, properties):
  test_artifacts_dir = api.path.mkdtemp(prefix='test-artifacts')
  api.tast_exec.download_tast(properties.build_payload.artifacts_gs_bucket,
                              properties.build_payload.artifacts_gs_path,
                              test_artifacts_dir)

  api.gcloud.set_gce_project(project=properties.gce_metadata.project)
  api.gcloud.auth_list()

  # TODO use buildbucket id (in LED runs id=0)
  api.random.seed(int(api.time.time()))
  rand_id = api.random.randint(1000000, 9999999)
  image = '{}-{}'.format(properties.build_target.name, rand_id)
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
    api.step('calibrate ssh key permissions',
             ['chmod', '400', str(private_key_path)])
    vm_context = api.tast_exec.create_gce_vm_context(
        image, project=properties.gce_metadata.project,
        zone=properties.gce_metadata.zone,
        machine=properties.gce_metadata.machine_type,
        network=properties.gce_metadata.network,
        subnet=properties.gce_metadata.subnet,
        private_key_path=private_key_path)

    with api.step.nest('run tast tests'):
      failures, empty_result = api.tast_exec.run_vm(
          properties.name, properties.expressions, vm_context,
          test_artifacts_dir, private_key_path,
          properties.build_payload.artifacts_gs_bucket,
          properties.build_payload.artifacts_gs_path)

    api.tast_results.print_results(failures, empty_result)

    return api.failures.aggregate_failures(failures)
  finally:
    api.gcloud.delete_image(image)


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          build_target=dict(name='board'),
          build_payload=dict(
              artifacts_gs_bucket='artifacts-bucket',
              artifacts_gs_path='artifacts-path',
          ),
          expressions=['expr'],
          gce_metadata=dict(
              project='project',
              zone='zone',
              machine_type='machine-type',
              network='network',
              subnet='subnet',
          ),
      ))
