# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests to verify sysroot_archive.find_best_archive."""

from PB.chromiumos import common as common_pb2
from PB.recipe_modules.chromeos.sysroot_archive.tests.find_best_archive import FindBestArchiveTestProperties
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'sysroot_archive',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = FindBestArchiveTestProperties


def RunSteps(api, properties):
  build_target = common_pb2.BuildTarget(name=properties.board_name)
  result = api.sysroot_archive.find_best_archive(build_target)
  if properties.expected_none:
    api.assertions.assertIsNone(result)
  else:
    api.assertions.assertEqual(result, properties.expected_result)


def GenTests(api):
  yield api.test(
      'use_sysroot_archive-off',
      api.sysroot_archive.get_sysroot_archive_properties(
          api, True, False, 'R120-15650.0.0', 'R120-15651.0.0', 0),
      api.properties(
          FindBestArchiveTestProperties(
              board_name='board1',
              expected_none=True,
          )),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-match',
      api.sysroot_archive.get_gsutil_list_testdata(api),
      api.sysroot_archive.get_sysroot_archive_properties(
          api, True, True, 'R120-15651.0.0', 'R120-15652.0.0', 0),
      api.properties(
          FindBestArchiveTestProperties(
              board_name='board1',
              expected_none=True,
          )),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'empty-gsutil-list-result',
      api.sysroot_archive.get_gsutil_list_empty_testdata(api),
      api.sysroot_archive.get_sysroot_archive_properties(
          api, True, True, 'R120-15650.0.0', 'R120-15651.0.0', 0),
      api.properties(
          FindBestArchiveTestProperties(
              board_name='board1',
              expected_none=True,
          )),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'match-same-version',
      api.sysroot_archive.get_gsutil_list_testdata(api),
      api.sysroot_archive.get_sysroot_archive_properties(
          api, True, True, 'R120-15650.0.0', 'R120-15651.0.0', 15),
      api.properties(
          FindBestArchiveTestProperties(
              board_name='board1',
              expected_result='gs://foo/board1/R120-15650.0.0~15-abc/sysroot.tar.zst',
          )),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'match-behind-version',
      api.sysroot_archive.get_gsutil_list_testdata(api),
      api.sysroot_archive.get_sysroot_archive_properties(
          api, True, True, 'R120-15650.0.0', 'R120-15651.0.0', 14),
      api.properties(
          FindBestArchiveTestProperties(
              board_name='board1',
              expected_result='gs://foo/board1/R120-15650.0.0~15-abc/sysroot.tar.zst',
          )),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'match-before-version',
      api.sysroot_archive.get_gsutil_list_testdata(api),
      api.sysroot_archive.get_sysroot_archive_properties(
          api, True, True, 'R120-15650.0.0', 'R120-15651.0.0', 7),
      api.properties(
          FindBestArchiveTestProperties(
              board_name='board1',
              expected_result='gs://foo/board1/R120-15650.0.0-abc/sysroot.tar.zst',
          )),
      api.post_process(post_process.DropExpectation),
  )
