# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests to verify sysroot_archive.parse_archive_path."""

from PB.recipe_modules.chromeos.sysroot_archive.tests.parse_archive_path import ParseArchivePathTestProperties
from RECIPE_MODULES.chromeos.sysroot_archive.api import ArchivePathInfo
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'sysroot_archive',
]


PROPERTIES = ParseArchivePathTestProperties


def RunSteps(api, properties):
  result = api.sysroot_archive.parse_archive_path(properties.input_path)
  expected_result = ArchivePathInfo(
      chromeos_version=properties.expected_chromeos_version,
      cl_count=properties.expected_cl_count)
  api.assertions.assertEqual(result, expected_result)


def GenTests(api):
  yield api.test(
      'normal-version-with-cl-diff',
      api.properties(
          ParseArchivePathTestProperties(
              input_path='gs://foo/bar/R120-15650.0.0~15-abc/sysroot.tar.zst',
              expected_chromeos_version='R120-15650.0.0',
              expected_cl_count=15,
          )),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'normal-version-without-cl-diff',
      api.properties(
          ParseArchivePathTestProperties(
              input_path='gs://foo/bar/R120-15650.0.0-abc/sysroot.tar.zst',
              expected_chromeos_version='R120-15650.0.0',
          )),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'snapshot-version-with-cl-diff',
      api.properties(
          ParseArchivePathTestProperties(
              input_path='gs://foo/bar/R120-15650.0.0-12345~15-abc/sysroot.tar.zst',
              expected_chromeos_version='R120-15650.0.0-12345',
              expected_cl_count=15,
          )),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'snapshot-version-without-cl-diff',
      api.properties(
          ParseArchivePathTestProperties(
              input_path='gs://foo/bar/R120-15650.0.0-12345-abc/sysroot.tar.zst',
              expected_chromeos_version='R120-15650.0.0-12345',
          )),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'none',
      api.properties(
          ParseArchivePathTestProperties(
              input_path='gs://foo/bar/moo/sysroot.tar.zst',
          )),
      api.expect_exception('ValueError'),
      api.post_process(post_process.DropExpectation),
  )
