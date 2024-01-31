# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

DEPS = [
    'recipe_engine/raw_io',
    'recipe_engine/swarming',
    'build_menu',
    'code_coverage',
]



def RunSteps(api):
  with api.build_menu.configure_builder(
  ), api.build_menu.setup_workspace_and_chroot():
    api.build_menu.setup_sysroot_and_determine_relevance()
    api.build_menu.bootstrap_sysroot()
    api.build_menu.install_packages()
    api.build_menu.build_and_test_images()
    api.code_coverage.upload_code_coverage('[START_DIR]/coverage.tbz2', 'LLVM',
                                           'chromeos-image-archive',
                                           'buildername/id')


def GenTests(api):
  yield api.build_menu.test(
      'cq-only-uploads-incremental',
      api.post_check(
          post_process.MustRun,
          'upload code coverage data.upload incremental coverage to gerrit'),
      api.post_check(
          post_process.DoesNotRun,
          'upload code coverage data.upload incremental coverage to gerrit.upload filtered.file.123456 for 123456 (ps #7)'
      ),
      api.post_check(post_process.MustRun,
                     'upload code coverage data.Set merger properties'),
      api.post_check(
          post_process.DoesNotRun,
          'upload code coverage data.upload absolute coverage to Code Search'),
      api.post_check(
          post_process.DoesNotRun,
          'upload code coverage data.upload absolute coverage to chromium coverage'
      ),
      cq=True,
      input_properties={
          '$chromeos/code_coverage': {
              'project': 'chromiumos/platform2',
              'cq_builder': True,
          }
      },
  )

  yield api.build_menu.test(
      'cq-should-write-cleaned-and-filtered-coverage-file-for-incremental',
      api.post_check(
          post_process.MustRun,
          'upload code coverage data.upload incremental coverage to gerrit.filter to changed files only.write filtered file'
      ),
      cq=True,
      input_properties={
          '$chromeos/code_coverage': {
              'project': 'chromiumos/platform2',
              'cq_builder': True,
          }
      },
  )

  yield api.build_menu.test(
      'non-cq-uploads-absolute-to-code-search-and-chromium',
      api.post_check(
          post_process.DoesNotRun,
          'upload code coverage data.upload incremental coverage to gerrit'),
      api.post_check(
          post_process.MustRun,
          'upload code coverage data.upload absolute coverage to Code Search'),
      api.post_check(post_process.MustRun,
                     'upload code coverage data.Set merger properties'),
      api.post_check(
          post_process.MustRun,
          'upload code coverage data.upload absolute coverage to chromium coverage'
      ),
      cq=False,
      input_properties={
          '$chromeos/code_coverage': {
              'project': 'chromiumos/platform2'
          },
          '$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          },
      },
  )

  yield api.build_menu.test(
      'non-cq-should-should-skip-chromium-coverage-upload',
      api.post_check(
          post_process.DoesNotRun,
          'upload code coverage data.upload absolute coverage to chromium coverage'
      ),
      cq=False,
      input_properties={
          '$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          },
          '$chromeos/code_coverage': {
              'project': 'chromiumos/platform2',
              'coverage_env': 'autopush',
          }
      },
  )

  yield api.build_menu.test(
      'non-cq-should-should-skip-chromium-coverage-upload-check',
      api.post_check(
          post_process.DoesNotRun,
          'upload code coverage data.upload absolute coverage to chromium coverage'
      ),
      cq=False,
      input_properties={
          '$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          },
          '$chromeos/code_coverage': {
              'project': 'chromiumos/platform2',
              'skip_chromium_upload': True,
          }
      },
  )

  yield api.build_menu.test(
      'non-cq-should-not-write-cleaned-coverage-file-for-chromium-coverage',
      api.post_check(
          post_process.DoesNotRun,
          'upload code coverage data.upload absolute coverage to chromium coverage.writing cleaned coverage file'
      ),
      cq=False,
      input_properties={
          '$chromeos/cros_relevance': {
              'force_postsubmit_relevance': True
          },
          '$chromeos/code_coverage': {
              'project': 'chromiumos/platform2'
          }
      },
  )
