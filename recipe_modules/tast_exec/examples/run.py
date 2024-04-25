# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process
from PB.testplans.generate_test_plan import BuildPayload
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/step',
    'tast_exec',
]



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

  qcow_image = api.tast_exec.download_vm(
      BuildPayload(
          artifacts_gs_bucket='bucket',
          artifacts_gs_path='path',
      ), vm_dir, modify_image=modify_image)

  api.assertions.assertTrue(image_modified)

  vm_context = api.tast_exec.create_qemu_vm_context(
      qcow_image, second_image_path=vm_dir / 'second_disk.bin')

  # Run with retry
  api.buildbucket.build.critical = common_pb2.YES
  api.tast_exec.run_vm(
      'tast_vm', vm_context,
      api.tast_exec.TastInputs(['!informational'], test_artifacts,
                               BuildPayload(
                                   artifacts_gs_bucket='artifacts-bucket',
                                   artifacts_gs_path='artifacts-path',
                               )))

  # Run without retry
  api.buildbucket.build.critical = common_pb2.NO
  results_dir = api.path.mkdtemp(prefix='temp')
  api.tast_exec.run_direct_vm(
      vm_context, results_dir,
      api.tast_exec.TastInputs(['!informational'], test_artifacts,
                               BuildPayload(
                                   artifacts_gs_bucket='artifacts-bucket',
                                   artifacts_gs_path='artifacts-path',
                               )))
  api.tast_exec.run_direct_vm(
      vm_context, results_dir,
      api.tast_exec.TastInputs(['example.Pass'], test_artifacts,
                               BuildPayload(
                                   artifacts_gs_bucket='artifacts-bucket',
                                   artifacts_gs_path='artifacts-path',
                               ), run_args=['-var=myVar=myVal']))

  # Just run the VM context in isolation to test VM kill.
  with api.step.nest('run VM context'):
    with vm_context():
      pass

  # Run with GCE VM
  vm_context = api.tast_exec.create_gce_vm_context('image', 'project',
                                                   'machine', 'zone', 'network',
                                                   'subnet')
  api.tast_exec.run_vm(
      'tast_vm', vm_context,
      api.tast_exec.TastInputs(['!informational'], test_artifacts,
                               BuildPayload(
                                   artifacts_gs_bucket='artifacts-bucket',
                                   artifacts_gs_path='artifacts-path',
                               )))


def GenTests(api):
  yield api.test('basic', api.buildbucket.ci_build(),
                 api.tast_exec.simulate_test_list_ret('some.test'),
                 api.post_check(post_process.MustRun, 'second tast iteration'))

  yield api.test(
      'forgives-delete-instance-failures', api.buildbucket.ci_build(),
      api.tast_exec.simulate_test_list_ret('some.test'),
      api.step_data('first tast iteration (2).delete instance', retcode=1))

  yield api.test(
      'public',
      api.buildbucket.ci_build(),
      api.tast_exec.simulate_test_list_ret('some.test'),
      api.properties(**{'$chromeos/tast_exec': {
          'public_builder': True
      }}),
  )

  # Test killing the VM: if the VM has not exited when the VM context
  # ends it should be killed, otherwise not.
  yield api.test(
      'normal VM exit',
      api.step_data('run VM context.check if VM running', retcode=0),
      api.post_check(post_process.MustRun, 'run VM context.kill vm'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'ssh does not connect',
      api.step_data('connect via ssh', retcode=1),
      api.step_data('connect via ssh (2)', retcode=1),
      api.step_data('connect via ssh (3)', retcode=1),
      api.step_data('connect via ssh (4)', retcode=1),
      api.step_data('connect via ssh (5)', retcode=1),
      api.step_data('connect via ssh (6)', retcode=1),
      api.step_data('connect via ssh (7)', retcode=1),
      api.step_data('connect via ssh (8)', retcode=1),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.test(
      'run VM context',
      api.step_data('run VM context.check if VM running', retcode=1),
      api.post_check(post_process.DoesNotRun, 'run VM context.kill vm'),
      api.post_process(post_process.DropExpectation),
  )
