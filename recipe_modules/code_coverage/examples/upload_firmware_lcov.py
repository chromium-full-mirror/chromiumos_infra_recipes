# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from recipe_engine import post_process

DEPS = [
    'recipe_engine/swarming',
    'build_menu',
    'code_coverage',
    'recipe_engine/cv',
    'repo',
]



def RunSteps(api):
  with api.build_menu.configure_builder(
  ), api.build_menu.setup_workspace_and_chroot():
    api.build_menu.setup_sysroot_and_determine_relevance()
    api.build_menu.bootstrap_sysroot()
    api.build_menu.install_packages()
    api.build_menu.build_and_test_images()
    api.code_coverage.upload_firmware_lcov('[START_DIR]/coverage.tbz2')


def GenTests(api):
  yield api.build_menu.test(
      'cq-only-uploads-incremental',
      api.post_check(
          post_process.MustRun,
          'upload code coverage data (firmware lcov).upload incremental coverage to gerrit'
      ),
      api.post_check(
          post_process.DoesNotRun,
          'upload code coverage data (firmware lcov).upload absolute coverage to Code Search'
      ),
      api.post_check(
          post_process.DoesNotRun,
          'upload code coverage data (firmware lcov).upload absolute coverage to chromium coverage'
      ),
      api.post_check(
          post_process.DoesNotRun,
          'upload code coverage data (firmware lcov).upload absolute coverage to chromium coverage'
      ),
      api.post_check(
          post_process.DoesNotRun,
          'upload code coverage data (firmware lcov).Set merger properties'),
      cq=True,
  )

  yield api.build_menu.test(
      'cq-should-not-filter-coverage-file-for-incremental',
      api.post_check(
          post_process.DoesNotRun,
          'upload code coverage data (code coverage llvm json).upload incremental coverage to gerrit.filter to changed files only'
      ),
      cq=True,
  )

  yield api.build_menu.test(
      'non-cq-uploads-absolute',
      api.post_check(
          post_process.DoesNotRun,
          'upload code coverage data (firmware lcov).upload incremental coverage to gerrit'
      ),
      api.post_check(
          post_process.MustRun,
          'upload code coverage data (firmware lcov).upload absolute coverage to Code Search'
      ),
      api.post_check(
          post_process.MustRun,
          'upload code coverage data (firmware lcov).upload absolute coverage to Code Search.Chunking coverage file'
      ),
      api.post_check(
          post_process.DoesNotRun,
          'upload code coverage data (firmware lcov).Set merger properties'),
      api.post_check(
          post_process.DoesNotRun,
          'upload code coverage data (firmware lcov).upload absolute coverage to chromium coverage'
      ),
      cq=False,
      input_properties={
          '$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          },
      },
  )

  yield api.build_menu.test(
      'cq-skips-excluded-project',
      api.repo.project_infos_step_data(
          'cherry-pick gerrit changes.apply gerrit patch sets', [{
              'project': 'chromiumos/third_party/zephyrproject',
              'path': 'src/third_party/zephyrproject'
          }]),
      api.post_check(
          post_process.MustRun,
          'upload code coverage data (firmware lcov).upload incremental coverage to gerrit'
      ),
      api.post_check(
          post_process.DoesNotRun,
          'upload code coverage data (firmware lcov).upload incremental coverage to gerrit.upload cleaned.file for 123456 (ps #7)'
      ),
      cq=True,
      gerrit_changes=[
          GerritChange(
              host='chromium-review.googlesource.com',
              project='chromiumos/third_party/zephyrproject',
              change=123456,
              patchset=7,
          )
      ],
  )
