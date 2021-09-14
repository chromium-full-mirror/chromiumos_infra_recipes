# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'build_menu',
    'code_coverage',
    'recipe_engine/raw_io',
]

from recipe_engine import post_process


def RunSteps(api):
  with api.build_menu.configure_builder(
  ), api.build_menu.setup_workspace_and_chroot():
    api.build_menu.setup_sysroot_and_determine_relevance()
    api.build_menu.bootstrap_sysroot()
    api.build_menu.install_packages()
    api.build_menu.build_and_test_images()
    api.code_coverage.upload_code_coverage_llvm_json(
        'sarien', '[START_DIR]/coverage.tbz2')


def GenTests(api):
  yield api.build_menu.test(
      'cq-only-uploads-incremental',
      api.post_check(
          post_process.MustRun,
          'upload code coverage data (code coverage llvm json).upload incremental coverage to gerrit'
      ),
      api.post_check(
          post_process.DoesNotRun,
          'upload code coverage data (code coverage llvm json).upload absolute coverage to Code Search'
      ),
      api.post_check(
          post_process.DoesNotRun,
          'upload code coverage data (code coverage llvm json).upload absolute coverage to chromium coverage'
      ),
      cq=True,
      input_properties={
          '$chromeos/code_coverage': dict(project='chromiumos/platform2')
      },
  )

  yield api.build_menu.test(
      'cq-should-write-cleaned-coverage-file-for-incremental',
      api.post_check(
          post_process.MustRun,
          'upload code coverage data (code coverage llvm json).upload incremental coverage to gerrit.writing cleaned coverage file'
      ),
      cq=True,
      input_properties={
          '$chromeos/code_coverage': dict(project='chromiumos/platform2')
      },
  )

  yield api.build_menu.test(
      'cq-should-write-cleaned-and-filtered-coverage-file-for-incremental',
      api.post_check(
          post_process.MustRun,
          'upload code coverage data (code coverage llvm json).upload incremental coverage to gerrit.filter to changed files only.write cleaned and filtered file'
      ),
      cq=True,
      input_properties={
          '$chromeos/code_coverage': dict(project='chromiumos/platform2')
      },
  )

  yield api.build_menu.test(
      'non-cq-uploads-absolute-to-code-search-and-chromium',
      api.post_check(
          post_process.DoesNotRun,
          'upload code coverage data (code coverage llvm json).upload incremental coverage to gerrit'
      ),
      api.post_check(
          post_process.MustRun,
          'upload code coverage data (code coverage llvm json).upload absolute coverage to Code Search'
      ),
      api.post_check(
          post_process.MustRun,
          'upload code coverage data (code coverage llvm json).upload absolute coverage to chromium coverage'
      ),
      cq=False,
      input_properties={
          '$chromeos/code_coverage': dict(project='chromiumos/platform2')
      },
  )

  yield api.build_menu.test(
      'non-cq-should-write-cleaned-coverage-file-for-absolute-code-search',
      api.post_check(
          post_process.MustRun,
          'upload code coverage data (code coverage llvm json).upload absolute coverage to Code Search.writing cleaned coverage file'
      ),
      cq=False,
      input_properties={
          '$chromeos/code_coverage': dict(project='chromiumos/platform2')
      },
  )

  yield api.build_menu.test(
      'non-cq-should-not-write-cleaned-coverage-file-for-chromium-coverage',
      api.post_check(
          post_process.DoesNotRun,
          'upload code coverage data (code coverage llvm json).upload absolute coverage to chromium coverage.writing cleaned coverage file'
      ),
      cq=False,
      input_properties={
          '$chromeos/code_coverage': dict(project='chromiumos/platform2')
      },
  )
