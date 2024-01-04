# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for factory util methods."""

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'cros_infra_config',
    'factory_util',
    'test_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  config = api.cros_infra_config.configure_builder()
  artifact_dir = '/path/to/artifacts'
  api.factory_util.upload_factory(config, artifact_dir)


def GenTests(api):
  yield api.test(
      'upload-artifacts',
      api.test_util.test_child_build('amd64-generic').build,
      api.post_check(
          post_process.StepCommandContains,
          'uploading factory artifacts for older branch.zip factory', [
              'zip', '-r', '/path/to/artifacts/factory_image.zip',
              'R99-1234.56.0-factory_shim', '--include',
              'R99-1234.56.0-factory_shim/*factory_install*.bin', '--include',
              'R99-1234.56.0-factory_shim/*partition*', '--include',
              'R99-1234.56.0-factory_shim/netboot/*'
          ]),
      api.post_check(
          post_process.StepCommandContains,
          'uploading factory artifacts for older branch.zip factory symlinks',
          ['zip', '-r', '/path/to/artifacts/factory_image.zip', '-y', '.']),
      api.post_check(
          post_process.StepCommandContains,
          'uploading factory artifacts for older branch.tar test image', [
              'tar', '-cJf', '/path/to/artifacts/chromiumos_test_image.tar.xz',
              'chromiumos_test_image.bin'
          ]),
      api.post_check(
          post_process.StepCommandContains,
          'uploading factory artifacts for older branch.gsutil cp', [
              'python3', '-u',
              'RECIPE_MODULE[depot_tools::gsutil]/resources/gsutil_smart_retry.py',
              '--', 'RECIPE_REPO[depot_tools]/gsutil.py', '-m', '----', 'cp',
              '/path/to/artifacts/factory_image.zip',
              'gs://chromeos-image-archive/amd64-generic-postsubmit/R99-1234.56.0-101-8945511751514863184'
          ]),
      api.post_process(post_process.DropExpectation),
  )
