# -*- coding: utf-8 -*-

# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/path',
    'recipe_engine/properties',
    'tast_exec',
]

def RunSteps(api):
  test_artifacts = api.path.mkdtemp(prefix='temp')
  api.tast_exec.download_tast('bucket', 'path', test_artifacts)
  vm_dir = api.path.mkdtemp(prefix='temp')
  qcow_image, private_key_path = api.tast_exec.download_vm(
      'bucket', 'path', vm_dir)

  # Run with retry
  api.tast_exec.run_vm('tast_vm', ['!informational'], qcow_image,
                       test_artifacts, private_key_path, 'artifacts-bucket',
                       'artifacts-path')

  # Run without retry
  results_dir = api.path.mkdtemp(prefix='temp')
  api.tast_exec.run_direct_vm(['!informational'], qcow_image, test_artifacts,
                              private_key_path, 'artifacts-bucket',
                              'artifacts-path', results_dir)
  api.tast_exec.run_direct_vm(['example.Pass'], qcow_image, test_artifacts,
                              private_key_path, 'artifacts-bucket',
                              'artifacts-path', results_dir,
                              run_args=['-var=myVar=myVal'])


def GenTests(api):
  yield api.test(
      'basic', api.properties(**{'$chromeos/tast_exec': {
          'should_retry': True
      }}))
