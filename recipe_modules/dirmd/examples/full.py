# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

DEPS = [
    'recipe_engine/file',
    'recipe_engine/path',
    'dirmd',
]



def RunSteps(api):
  # Call validate_dir twice, once on a dir that has DIR_METADATA files, once on
  # a dir that doesn't. Note that although two separate directories are created,
  # the difference in behavior is caused by the `glob_paths` test data.
  testdir = api.path.mkdtemp()
  api.dirmd.validate_dir(testdir)

  testdir_without_metadata_files = api.path.mkdtemp()
  api.dirmd.validate_dir(testdir_without_metadata_files)


def GenTests(api):

  dirmd_glob_paths = api.step_data(
      'dirmd validate [CLEANUP]/tmp_tmp_1.find DIR_METADATA files',
      api.file.glob_paths(['a/b/DIR_METADATA']),
  )

  yield api.test(
      'basic',
      dirmd_glob_paths,
      api.post_process(
          post_process.StepCommandContains,
          'dirmd validate [CLEANUP]/tmp_tmp_1.dirmd validate',
          [
              '[START_DIR]/cipd_dirmd/dirmd', 'validate',
              '[CLEANUP]/tmp_tmp_1/a/b/DIR_METADATA'
          ],
      ),
      api.post_process(
          post_process.DoesNotRun,
          'dirmd validate [CLEANUP]/tmp_tmp_2.dirmd validate',
      ),
  )

  yield api.test(
      'validation failure',
      dirmd_glob_paths,
      api.step_data('dirmd validate [CLEANUP]/tmp_tmp_1.dirmd validate',
                    retcode=1),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )
