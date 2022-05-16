# -*- coding: utf-8 -*-

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'tast_exec',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

from recipe_engine import post_process
from PB.testplans.generate_test_plan import BuildPayload


def RunSteps(api):
  test_artifacts = api.path.mkdtemp(prefix='temp')
  api.tast_exec.download_tast(
      BuildPayload(
          artifacts_gs_bucket='bucket',
          artifacts_gs_path='path',
      ), test_artifacts)
  vm_dir = api.path.mkdtemp(prefix='temp')

  # Use a dict rather than a bool so that it can be modified within the
  # nested scope.
  image_modified = {}

  def modify_image(image_path):
    image_modified[image_path] = True

  qcow_image, private_key_path = api.tast_exec.download_vm(
      BuildPayload(
          artifacts_gs_bucket='bucket',
          artifacts_gs_path='path',
      ), vm_dir, modify_image=modify_image)

  api.assertions.assertTrue(image_modified)

  vm_context = api.tast_exec.create_qemu_vm_context(
      qcow_image, private_key_path,
      second_image_path=vm_dir.join('second_disk.bin'))

  # Run with retry
  api.tast_exec.run_vm(
      'tast_vm', vm_context,
      api.tast_exec.TastInputs(['!informational'], test_artifacts,
                               BuildPayload(
                                   artifacts_gs_bucket='artifacts-bucket',
                                   artifacts_gs_path='artifacts-path',
                               ), private_key_path))

  # Run without retry
  results_dir = api.path.mkdtemp(prefix='temp')
  api.tast_exec.run_direct_vm(
      vm_context, results_dir,
      api.tast_exec.TastInputs(['!informational'], test_artifacts,
                               BuildPayload(
                                   artifacts_gs_bucket='artifacts-bucket',
                                   artifacts_gs_path='artifacts-path',
                               ), private_key_path))
  api.tast_exec.run_direct_vm(
      vm_context, results_dir,
      api.tast_exec.TastInputs(['example.Pass'], test_artifacts,
                               BuildPayload(
                                   artifacts_gs_bucket='artifacts-bucket',
                                   artifacts_gs_path='artifacts-path',
                               ), private_key_path,
                               run_args=['-var=myVar=myVal']))

  # Run with GCE VM
  vm_context = api.tast_exec.create_gce_vm_context('image', 'project',
                                                   'machine', 'zone', 'network',
                                                   'subnet', private_key_path)
  api.tast_exec.run_vm(
      'tast_vm', vm_context,
      api.tast_exec.TastInputs(['!informational'], test_artifacts,
                               BuildPayload(
                                   artifacts_gs_bucket='artifacts-bucket',
                                   artifacts_gs_path='artifacts-path',
                               ), private_key_path))


def GenTests(api):
  yield api.test(
      'basic', api.buildbucket.ci_build(),
      api.properties(**{'$chromeos/tast_exec': {
          'should_retry': True
      }}), api.post_check(post_process.MustRun, 'second tast iteration'))

  yield api.test(
      'public',
      api.buildbucket.ci_build(),
      api.properties(**{'$chromeos/tast_exec': {
          'public_builder': True
      }}),
  )
